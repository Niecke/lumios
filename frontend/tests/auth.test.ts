import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

const local = new Map<string, string>();
(globalThis as any).localStorage = {
  getItem: (k: string) => local.get(k) ?? null,
  setItem: (k: string, v: string) => void local.set(k, v),
  removeItem: (k: string) => void local.delete(k),
};
const store = new Map<string, string>();
(globalThis as any).sessionStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
};

const {
  authApi,
  chooseLanguage,
  tokenStore,
  isGsiInitialized,
  markGsiInitialized,
} = await import("../src/api/auth.ts");

function mockFetch(status: number, body?: unknown) {
  globalThis.fetch = (async () =>
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: body === undefined ? {} : { "content-type": "application/json" },
    })) as typeof fetch;
}

// Records every call and answers with the given account language.
function mockAccount(language: string | null) {
  const calls: { method: string; path: string; body: any }[] = [];
  globalThis.fetch = (async (path: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ method: init?.method ?? "GET", path, body });
    if (path.endsWith("/login")) return json({ token: "fresh-token" });
    if (body?.language) language = body.language;
    return json({ email: "a@example.com", language });
  }) as typeof fetch;
  return calls;
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

const patches = (calls: { method: string }[]) => calls.filter((c) => c.method === "PATCH");

const { default: i18n } = await import("../src/i18n/index.ts");

beforeEach(async () => {
  await authApi.logout();
  local.clear();
  await i18n.changeLanguage("de");
  store.clear();
  tokenStore.set("stale-token");
  markGsiInitialized();
});

test("authApi.me() clears tokenStore on 401", async () => {
  mockFetch(401, { error: "Token expired" });
  await assert.rejects(authApi.me(), { status: 401 });
  assert.equal(tokenStore.get(), null);
  assert.equal(isGsiInitialized(), false);
});

test("authApi.me() preserves token on 200", async () => {
  mockFetch(200, { email: "a@example.com" });
  await authApi.me();
  assert.equal(tokenStore.get(), "stale-token");
});

test("authApi.me() does not clear token on 500", async () => {
  mockFetch(500, { error: "boom" });
  await assert.rejects(authApi.me(), { status: 500 });
  assert.equal(tokenStore.get(), "stale-token");
});

test("authApi.changePassword() does not clear token on wrong current password (401)", async () => {
  mockFetch(401, { error: "Current password is incorrect" });
  await assert.rejects(authApi.changePassword("x", "y"), { status: 401 });
  assert.equal(tokenStore.get(), "stale-token");
});

test("authApi.logout() clears tokenStore and resets GSI state", async () => {
  await authApi.logout();
  assert.equal(tokenStore.get(), null);
  assert.equal(isGsiInitialized(), false);
});

test("authApi.me() waits for a pending language update and keeps a failed choice", async () => {
  const { currentLocale, setLocale } = await import("../src/i18n/index.ts");
  setLocale("en");
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  const calls: string[] = [];
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    calls.push(init?.method ?? "GET");
    if (init?.method === "PATCH") {
      await gate;
      return new Response(JSON.stringify({ error: "boom" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ email: "a@example.com", language: "de" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;

  const update = authApi.updateMe({ language: "en" }).catch(() => {});
  const me = authApi.me();
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(calls, ["PATCH"]); // me() has not fetched yet
  release();
  await update;
  await me;
  assert.deepEqual(calls, ["PATCH", "GET"]);
  assert.equal(currentLocale(), "en"); // failed save does not revert to the stored "de"
});

test("logout forgets an unsaved language, so me() applies the account language again", async () => {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ error: "boom" }), {
      status: 500,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
  await authApi.updateMe({ language: "en" }).catch(() => {});

  await authApi.logout();
  tokenStore.set("next-session");
  mockAccount("en");
  await authApi.me();
  assert.equal(i18n.language, "en");
});

test("login: an account without a language takes the choice made in this browser", async () => {
  local.set("lumios_locale", "en");
  await i18n.changeLanguage("en");
  const calls = mockAccount(null);

  const user = await authApi.loginPassword("a@example.com", "pw");

  assert.equal(user.language, "en");
  assert.equal(i18n.language, "en"); // not reset to German
  assert.deepEqual(patches(calls).map((c: any) => c.body), [{ language: "en" }]);
});

test("login: no choice in this browser leaves the account without a language", async () => {
  const calls = mockAccount(null);
  const user = await authApi.loginPassword("a@example.com", "pw");
  assert.equal(user.language, null);
  assert.equal(patches(calls).length, 0);
});

test("login: a language set on the account wins over the local choice", async () => {
  local.set("lumios_locale", "en");
  await i18n.changeLanguage("en");
  const calls = mockAccount("de");

  await authApi.loginPassword("a@example.com", "pw");

  assert.equal(i18n.language, "de");
  assert.equal(patches(calls).length, 0);
});

test("me() outside a login never saves the local language to the account", async () => {
  local.set("lumios_locale", "en");
  await i18n.changeLanguage("en");
  const calls = mockAccount(null);

  await authApi.me();

  assert.equal(i18n.language, "en");
  assert.equal(patches(calls).length, 0);
});

test("register and registerGoogle send the current language", async () => {
  await i18n.changeLanguage("en");
  const calls = mockAccount(null);
  await authApi.register("a@example.com", "pw");
  await authApi.registerGoogle("credential");
  assert.deepEqual(calls.map((c) => c.body.language), ["en", "en"]);
});

test("a switcher outside the photographer's area only changes the local language", async () => {
  const calls = mockAccount("de");

  chooseLanguage("en", false); // logged in, on a public gallery

  assert.equal(calls.length, 0);
  assert.equal(local.get("lumios_locale"), "en");
  assert.equal(i18n.language, "en");
  // languageUnsaved stays untouched: the account language still applies on the next me().
  await authApi.me();
  assert.equal(i18n.language, "de");
});

test("a switcher in the photographer's area saves to the account when logged in", async () => {
  const calls = mockAccount("de");
  chooseLanguage("en", true);
  assert.deepEqual(patches(calls).map((c: any) => c.body), [{ language: "en" }]);

  await authApi.logout();
  const anonymous = mockAccount(null);
  chooseLanguage("de", true);
  assert.equal(anonymous.length, 0);
});
