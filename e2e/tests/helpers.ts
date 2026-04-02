import type { APIRequestContext } from "@playwright/test";

export const API = "/api/v1";

// Seeded test credentials (created by `flask seed-test-data`)
export const PHOTOGRAPHER_EMAIL = "photographer@test.com";
export const PHOTOGRAPHER_PASSWORD = "TestPass123!";
export const ADMIN_EMAIL = "admin@test.com";
export const ADMIN_PASSWORD = "AdminPass123!";

/**
 * Login and return the JWT bearer token.
 */
export async function login(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<string> {
  const resp = await request.post(`${API}/auth/login`, {
    data: { email, password },
  });
  if (!resp.ok()) {
    throw new Error(
      `Login failed for ${email}: ${resp.status()} ${await resp.text()}`,
    );
  }
  const body = await resp.json();
  return body.token as string;
}

/**
 * Return an Authorization header object for the given token.
 */
export function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

// A valid 10×10 grey JPEG (629 bytes) generated with Pillow.
// Used to satisfy the file-upload endpoint without needing a fixture file.
// Generated with: Image.new("RGB", (10, 10), color=(128, 128, 128))
const _TINY_JPEG_B64 =
  "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8L" +
  "CwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUF" +
  "BQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4e" +
  "Hh4eHh4eHh4eHh4eHh7/wAARCAAKAAoDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEA" +
  "AAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMU" +
  "EGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0" +
  "RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmq" +
  "KjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8v" +
  "P09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgEC" +
  "BAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRC" +
  "hYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dX" +
  "Z3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMn" +
  "K0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwAooooA/9k=";

export const TINY_JPEG = Buffer.from(_TINY_JPEG_B64, "base64");
