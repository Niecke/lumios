import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

// Browser storage stand-ins; the i18n module reads localStorage on import.
const local = new Map<string, string>();
(globalThis as any).localStorage = {
  getItem: (k: string) => local.get(k) ?? null,
  setItem: (k: string, v: string) => void local.set(k, v),
  removeItem: (k: string) => void local.delete(k),
};
// A browser set to English must not change the default.
Object.defineProperty(globalThis, "navigator", { value: { language: "en-US" }, configurable: true });

const mod = await import("../src/i18n/index.ts");
const { default: i18n, detectLocale, setLocale, formatBytes, formatDate, formatTimeAgo } = mod;
const { getApiErrorMessage } = await import("../src/api/errors.ts");
const { authApi, tokenStore } = await import("../src/api/auth.ts");

const de = JSON.parse(readFileSync("src/i18n/locales/de.json", "utf8"));
const en = JSON.parse(readFileSync("src/i18n/locales/en.json", "utf8"));

beforeEach(async () => {
  local.clear();
  await i18n.changeLanguage("de");
});

function flatten(obj: Record<string, unknown>, prefix = ""): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object") Object.assign(out, flatten(v as Record<string, unknown>, key));
    else out[key] = v;
  }
  return out;
}

test("default locale is German, ignoring navigator.language", () => {
  assert.equal(detectLocale(), "de");
});

test("a stored locale is respected, an invalid one is not", () => {
  local.set("lumios_locale", "en");
  assert.equal(detectLocale(), "en");
  local.set("lumios_locale", "fr");
  assert.equal(detectLocale(), "de");
});

test("setLocale switches the language and persists it", () => {
  setLocale("en");
  assert.equal(i18n.language, "en");
  assert.equal(local.get("lumios_locale"), "en");
  assert.equal(i18n.t("nav.logout"), "Logout");
  setLocale("de");
  assert.equal(i18n.t("nav.logout"), "Abmelden");
});

test("message files have the same keys and no empty values", () => {
  const a = flatten(en);
  const b = flatten(de);
  assert.deepEqual(Object.keys(a).sort(), Object.keys(b).sort());
  for (const [file, flat] of [["en", a], ["de", b]] as const) {
    for (const [key, value] of Object.entries(flat)) {
      assert.ok(typeof value === "string" && value.trim() !== "", `${file}.json: empty value for ${key}`);
    }
  }
});

test("every key used in the source exists in the message files", () => {
  const keys = new Set(Object.keys(flatten(en)));
  const has = (k: string) => keys.has(k) || keys.has(`${k}_one`) || keys.has(`${k}_other`);
  const files: string[] = [];
  (function walk(dir: string) {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.tsx?$/.test(name) && !name.endsWith(".gen.ts")) files.push(p);
    }
  })("src");
  const missing: string[] = [];
  for (const file of files) {
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(/\bt\(\s*"([A-Za-z0-9_.]+)"|i18nKey="([^"]+)"|"(errors\.[A-Za-z]+)"/g)) {
      const key = m[1] ?? m[2] ?? m[3];
      if (!has(key)) missing.push(`${file}: ${key}`);
    }
    // keys built from a template literal: check the prefix has entries
    for (const m of src.matchAll(/\bt\(\s*`([A-Za-z0-9_.]+)\.\$\{/g)) {
      if (![...keys].some((k) => k.startsWith(`${m[1]}.`))) missing.push(`${file}: ${m[1]}.*`);
    }
  }
  assert.deepEqual(missing, []);
});

test("a key missing in German falls back to English and is marked", () => {
  i18n.addResource("en", "translation", "test.onlyEnglish", "English only");
  assert.equal(i18n.t("test.onlyEnglish"), "English only");
  assert.equal(i18n.t("test.onlyEnglish", { postProcess: "markFallback" }), "[EN] English only");
  assert.equal(i18n.t("nav.logout", { postProcess: "markFallback" }), "Abmelden");
});

test("dates, numbers and sizes follow the active locale", () => {
  assert.equal(formatBytes(1536, "de"), "1,5 KB");
  assert.equal(formatBytes(1536, "en"), "1.5 KB");
  assert.notEqual(formatDate("2026-03-05T12:00:00Z", "de"), formatDate("2026-03-05T12:00:00Z", "en"));
  assert.match(formatDate("2026-03-05T12:00:00Z", "de"), /2026/);
});

test("API error messages are translated, unknown ones pass through", async () => {
  const t = i18n.t.bind(i18n);
  const err = (message: string, code?: string) => Object.assign(new Error(message), { code });
  assert.equal(getApiErrorMessage(err("Library not found"), t), "Galerie nicht gefunden");
  assert.equal(getApiErrorMessage(err("x", "token_expired"), t), "Der Aktivierungslink ist abgelaufen");
  assert.equal(getApiErrorMessage(err("User not yet activated"), t), "Das Konto ist noch nicht aktiviert");
  assert.equal(getApiErrorMessage(err("name must be 255 characters or fewer"), t), "Maximal 255 Zeichen erlaubt");
  assert.equal(getApiErrorMessage(err("Request failed (500)"), t), "Anfrage fehlgeschlagen (500)");
  assert.equal(getApiErrorMessage(err("Something new"), t), "Something new");
  assert.equal(getApiErrorMessage(undefined, t), "Etwas ist schiefgelaufen");
  await i18n.changeLanguage("en");
  assert.equal(getApiErrorMessage(err("Library not found"), t), "Library not found");
  assert.equal(getApiErrorMessage(err("name must be 255 characters or fewer"), t), "Must be 255 characters or fewer");
});

test("relative times and notification texts are localized", async () => {
  const now = Date.parse("2026-03-05T12:00:00Z");
  const ago = (ms: number) => new Date(now - ms).toISOString();
  assert.equal(formatTimeAgo(ago(10_000), now), "gerade eben");
  assert.equal(formatTimeAgo(ago(5 * 60_000), now), "vor 5 Min.");
  assert.equal(formatTimeAgo(ago(2 * 3_600_000), now), "vor 2 Std.");
  assert.equal(formatTimeAgo(ago(3 * 86_400_000), now), "vor 3 Tagen");
  await i18n.changeLanguage("en");
  assert.equal(formatTimeAgo(ago(10_000), now), "just now");
  assert.equal(formatTimeAgo(ago(5 * 60_000), now), "5m ago");
  assert.equal(i18n.t("notifications.libraryMarked", { name: "Hochzeit" }),
    'Library "Hochzeit" was marked as finished by the customer');
  await i18n.changeLanguage("de");
  assert.equal(i18n.t("notifications.libraryViewed", { name: "Hochzeit" }),
    "Die Galerie „Hochzeit“ wurde von einem Kunden angesehen");
});

test("the account language wins after /auth/me", async () => {
  (globalThis as any).sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ email: "a@example.com", language: "en" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
  await authApi.me();
  assert.equal(i18n.language, "en");
  assert.equal(local.get("lumios_locale"), "en");
  assert.equal(tokenStore.get(), null);
});

test("no hard-coded user-facing strings are left in the components", () => {
  const files = [
    ...readdirSync("src/routes").map((f) => join("src/routes", f)),
    ...readdirSync("src/components").map((f) => join("src/components", f)),
  ].filter((f) => f.endsWith(".tsx"));
  const found: string[] = [];
  for (const file of files) {
    const src = readFileSync(file, "utf8");
    // JSX text between tags that contains letters: ">Some text<" (not {expressions})
    for (const m of src.matchAll(/>([^<>{}=;()&|]*[A-Za-z]{2,}[^<>{}=;()&|]*)</g)) {
      const text = m[1].trim();
      if (text && text !== "Lumios" && !/^[a-z_]+$/.test(text) && !/^[\s\-·…/%]*$/.test(text)) found.push(`${file}: text "${text}"`);
    }
    // user-visible attributes with a literal string
    for (const m of src.matchAll(/\b(title|placeholder|aria-label|alt)="([^"]*[A-Za-z]{2,}[^"]*)"/g)) {
      found.push(`${file}: ${m[1]}="${m[2]}"`);
    }
  }
  assert.deepEqual(found, []);
});
