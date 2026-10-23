import { test } from "node:test";
import assert from "node:assert/strict";

const { fetchVersion, formatFooterVersion } = await import("../src/api/version.ts");

function mockFetch(impl: () => Promise<unknown>) {
  globalThis.fetch = impl as unknown as typeof fetch;
}

test("formatFooterVersion joins version and short commit", () => {
  assert.equal(
    formatFooterVersion({ commit: "abcdef1234567890", version: "v1.2.3", built_at: "t" }),
    "v1.2.3 · abcdef12",
  );
});

test("formatFooterVersion falls back to dev", () => {
  assert.equal(formatFooterVersion(), "dev · dev");
});

test("fetchVersion reads /version.json", async () => {
  mockFetch(async () => ({
    ok: true,
    json: async () => ({ commit: "abc", version: "v1", built_at: "now" }),
  }));
  assert.deepEqual(await fetchVersion(), { commit: "abc", version: "v1", built_at: "now" });
});

test("fetchVersion falls back to dev on HTTP error", async () => {
  mockFetch(async () => ({ ok: false, json: async () => ({}) }));
  assert.equal((await fetchVersion()).version, "dev");
});

test("fetchVersion falls back to dev on network error", async () => {
  mockFetch(async () => {
    throw new Error("offline");
  });
  assert.equal((await fetchVersion()).commit, "dev");
});
