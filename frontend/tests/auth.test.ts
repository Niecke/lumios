import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

const store = new Map<string, string>();
(globalThis as any).sessionStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
};

const {
  authApi,
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

beforeEach(() => {
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
