import { test } from "node:test";
import assert from "node:assert/strict";

const { QUERY_STALE_TIME_MS, QUERY_DEFAULT_OPTIONS } = await import("../src/queryDefaults.ts");

test("default staleTime is 30 seconds", () => {
  assert.equal(QUERY_STALE_TIME_MS, 30_000);
});

test("queries default staleTime uses the constant", () => {
  assert.equal(QUERY_DEFAULT_OPTIONS.queries.staleTime, QUERY_STALE_TIME_MS);
});

test("no other query defaults are set", () => {
  assert.deepEqual(Object.keys(QUERY_DEFAULT_OPTIONS.queries), ["staleTime"]);
});
