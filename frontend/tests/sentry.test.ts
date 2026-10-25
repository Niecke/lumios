import { test } from "node:test";
import assert from "node:assert/strict";

(globalThis as any).window = { __CONFIG__: { GOOGLE_CLIENT_ID: "x", LANDING_URL: "x", APP_URL: "x" } };

const { scrubString, scrubEvent, initSentry } = await import("../src/sentry.ts");

const UUID = "123e4567-e89b-12d3-a456-426614174000";
const JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl";

test("scrubString redacts emails, JWTs and UUIDs", () => {
  assert.equal(
    scrubString(`a.b@example.com ${JWT} /library/${UUID}`),
    "[REDACTED_EMAIL] [REDACTED_JWT] /library/[REDACTED_UUID]",
  );
});

test("scrubEvent strips headers, cookies, user data and URLs", () => {
  const event = scrubEvent({
    type: undefined,
    user: { id: "7", email: "a@b.at", ip_address: "1.2.3.4" },
    request: {
      url: `https://x.test/library/${UUID}`,
      headers: { Authorization: `Bearer ${JWT}`, Cookie: "s=1", Accept: "*/*" },
      cookies: { s: "1" },
    },
    breadcrumbs: [{ message: `GET /library/${UUID}` }],
  });
  assert.deepEqual(event.user, { id: "7" });
  assert.equal(event.request?.url, "https://x.test/library/[REDACTED_UUID]");
  assert.equal(event.request?.headers?.Authorization, "[REDACTED]");
  assert.equal(event.request?.headers?.Cookie, "[REDACTED]");
  assert.equal(event.request?.headers?.Accept, "*/*");
  assert.equal(event.request?.cookies, undefined);
  assert.equal(event.breadcrumbs?.[0].message, "GET /library/[REDACTED_UUID]");
});

test("initSentry does nothing without a DSN", () => {
  initSentry();
  assert.equal((globalThis as any).window.sendSentryTestEvent, undefined);
});
