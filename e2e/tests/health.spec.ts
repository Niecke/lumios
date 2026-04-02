import { test, expect } from "@playwright/test";

test("GET /health returns healthy", async ({ request }) => {
  const resp = await request.get("/health");
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.status).toBe("healthy");
});
