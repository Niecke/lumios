/**
 * Share-link (customer) flow integration tests.
 *
 * These tests cover the critical unauthenticated customer path:
 *   1. Open a public library by UUID
 *   2. Toggle the "liked" state of an image
 *   3. Finish / mark selection complete
 *
 * Test data is set up in beforeAll via the authenticated photographer API and
 * torn down in afterAll. No external mocks — real backend + real DB + real MinIO.
 */
import { test, expect, type APIRequestContext } from "@playwright/test";
import {
  API,
  PHOTOGRAPHER_EMAIL,
  PHOTOGRAPHER_PASSWORD,
  login,
  bearer,
  TINY_JPEG,
} from "./helpers";

// Shared state populated in beforeAll
let token: string;
let libraryId: number;
let libraryUuid: string;
let imageUuid: string;

test.beforeAll(async ({ request }) => {
  token = await login(request, PHOTOGRAPHER_EMAIL, PHOTOGRAPHER_PASSWORD);

  // Create a library for this test run
  const libResp = await request.post(`${API}/libraries`, {
    headers: bearer(token),
    data: { name: "Share-link test library" },
  });
  expect(libResp.status()).toBe(201);
  const lib = await libResp.json();
  libraryId = lib.id;
  libraryUuid = lib.uuid;

  // Upload a tiny JPEG so we can test the like + finish flow
  const uploadResp = await request.post(
    `${API}/libraries/${libraryId}/images`,
    {
      headers: bearer(token),
      multipart: {
        file: {
          name: "test.jpg",
          mimeType: "image/jpeg",
          buffer: TINY_JPEG,
        },
      },
    },
  );
  expect(uploadResp.status()).toBe(201);
  const img = await uploadResp.json();
  imageUuid = img.uuid;
});

test.afterAll(async ({ request }) => {
  if (libraryId) {
    await request.delete(`${API}/libraries/${libraryId}`, {
      headers: bearer(token),
    });
  }
});

// ---------------------------------------------------------------------------
// Public library access
// ---------------------------------------------------------------------------

test("GET public library returns library metadata and images", async ({
  request,
}) => {
  const resp = await request.get(
    `${API}/public/libraries/${libraryUuid}`,
  );
  expect(resp.status()).toBe(200);
  const body = await resp.json();

  expect(body.library.uuid).toBe(libraryUuid);
  expect(body.library.name).toBe("Share-link test library");
  expect(Array.isArray(body.images)).toBe(true);
  expect(body.total).toBe(1);

  const img = body.images[0];
  expect(img.uuid).toBe(imageUuid);
  expect(img.customer_state).toBe("none");
  // Preview / thumb URLs must be present (no originals served to customers)
  expect(typeof img.preview_url).toBe("string");
  expect(typeof img.thumb_url).toBe("string");
  expect(img.preview_url).not.toContain("originals");
});

test("GET public library returns 404 for unknown UUID", async ({ request }) => {
  const resp = await request.get(
    `${API}/public/libraries/00000000-0000-0000-0000-000000000000`,
  );
  expect(resp.status()).toBe(404);
});

test("GET private library returns 404", async ({ request }) => {
  // Make the library private via the photographer API
  const patch = await request.patch(`${API}/libraries/${libraryId}`, {
    headers: bearer(token),
    data: { is_private: true },
  });
  expect(patch.status()).toBe(200);

  // Public endpoint should now return 404
  const pub = await request.get(
    `${API}/public/libraries/${libraryUuid}`,
  );
  expect(pub.status()).toBe(404);

  // Restore to public for remaining tests
  const restore = await request.patch(`${API}/libraries/${libraryId}`, {
    headers: bearer(token),
    data: { is_private: false },
  });
  expect(restore.status()).toBe(200);
});

// ---------------------------------------------------------------------------
// Image state (customer "likes")
// ---------------------------------------------------------------------------

test("PATCH image state to liked updates customer_state", async ({
  request,
}) => {
  const resp = await request.patch(
    `${API}/public/libraries/${libraryUuid}/images/${imageUuid}/state`,
    { data: { customer_state: "liked" } },
  );
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.uuid).toBe(imageUuid);
  expect(body.customer_state).toBe("liked");
});

test("PATCH image state to none removes the like", async ({ request }) => {
  const resp = await request.patch(
    `${API}/public/libraries/${libraryUuid}/images/${imageUuid}/state`,
    { data: { customer_state: "none" } },
  );
  expect(resp.status()).toBe(200);
  expect((await resp.json()).customer_state).toBe("none");
});

test("PATCH image state with invalid value returns 400", async ({ request }) => {
  const resp = await request.patch(
    `${API}/public/libraries/${libraryUuid}/images/${imageUuid}/state`,
    { data: { customer_state: "invalid_value" } },
  );
  expect(resp.status()).toBe(400);
});

// ---------------------------------------------------------------------------
// Finish (mark selection complete)
// ---------------------------------------------------------------------------

test("POST finish without any liked images returns 422", async ({ request }) => {
  // Ensure image is in 'none' state first
  await request.patch(
    `${API}/public/libraries/${libraryUuid}/images/${imageUuid}/state`,
    { data: { customer_state: "none" } },
  );

  const resp = await request.post(
    `${API}/public/libraries/${libraryUuid}/finish`,
  );
  expect(resp.status()).toBe(422);
});

test("POST finish with at least one liked image succeeds", async ({
  request,
}) => {
  // Like the image first
  await request.patch(
    `${API}/public/libraries/${libraryUuid}/images/${imageUuid}/state`,
    { data: { customer_state: "liked" } },
  );

  const resp = await request.post(
    `${API}/public/libraries/${libraryUuid}/finish`,
  );
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.uuid).toBe(libraryUuid);
  expect(typeof body.finished_at).toBe("string");
});

test("POST finish on an already-finished library returns 409", async ({
  request,
}) => {
  // Library is already finished from the previous test
  const resp = await request.post(
    `${API}/public/libraries/${libraryUuid}/finish`,
  );
  expect(resp.status()).toBe(409);
});
