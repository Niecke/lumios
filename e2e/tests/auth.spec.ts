import { test, expect } from "@playwright/test";
import {
  API,
  PHOTOGRAPHER_EMAIL,
  PHOTOGRAPHER_PASSWORD,
  login,
  bearer,
} from "./helpers";

test("POST /auth/login with valid credentials returns JWT", async ({
  request,
}) => {
  const resp = await request.post(`${API}/auth/login`, {
    data: { email: PHOTOGRAPHER_EMAIL, password: PHOTOGRAPHER_PASSWORD },
  });
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(typeof body.token).toBe("string");
  expect(body.token.length).toBeGreaterThan(0);
  expect(body.email).toBe(PHOTOGRAPHER_EMAIL);
  expect(body.roles).toContain("photographer");
});

test("POST /auth/login with wrong password returns 401", async ({
  request,
}) => {
  const resp = await request.post(`${API}/auth/login`, {
    data: { email: PHOTOGRAPHER_EMAIL, password: "WrongPassword!" },
  });
  expect(resp.status()).toBe(401);
});

test("POST /auth/login with unknown email returns 401", async ({ request }) => {
  const resp = await request.post(`${API}/auth/login`, {
    data: { email: "nobody@example.com", password: "any" },
  });
  expect(resp.status()).toBe(401);
});

test("GET /auth/me with valid JWT returns user info", async ({ request }) => {
  const token = await login(request, PHOTOGRAPHER_EMAIL, PHOTOGRAPHER_PASSWORD);
  const resp = await request.get(`${API}/auth/me`, {
    headers: bearer(token),
  });
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.email).toBe(PHOTOGRAPHER_EMAIL);
  expect(body.account_type).toBe("local");
});

test("GET /auth/me without token returns 401", async ({ request }) => {
  const resp = await request.get(`${API}/auth/me`);
  expect(resp.status()).toBe(401);
});

test("GET /libraries returns empty list for a fresh photographer", async ({
  request,
}) => {
  const token = await login(request, PHOTOGRAPHER_EMAIL, PHOTOGRAPHER_PASSWORD);
  const resp = await request.get(`${API}/libraries`, {
    headers: bearer(token),
  });
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(Array.isArray(body.libraries)).toBe(true);
});

test("POST /libraries creates a library and DELETE removes it", async ({
  request,
}) => {
  const token = await login(request, PHOTOGRAPHER_EMAIL, PHOTOGRAPHER_PASSWORD);

  // Create
  const create = await request.post(`${API}/libraries`, {
    headers: bearer(token),
    data: { name: "Auth-test library" },
  });
  expect(create.status()).toBe(201);
  const lib = await create.json();
  expect(lib.name).toBe("Auth-test library");
  expect(typeof lib.id).toBe("number");
  expect(typeof lib.uuid).toBe("string");

  // Delete
  const del = await request.delete(`${API}/libraries/${lib.id}`, {
    headers: bearer(token),
  });
  expect(del.status()).toBe(204);
});
