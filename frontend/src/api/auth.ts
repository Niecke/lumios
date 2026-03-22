// auth.ts — all communication with the backend auth API
//
// Login flow:
//   1. Google Identity Services (GIS) runs in the browser and hands us a
//      signed ID token (credential).
//   2. We decode the token payload client-side to read display fields
//      (name, picture, …) without verifying the signature — display only.
//   3. We POST the credential to the backend which verifies it with Google's
//      JWKS and returns a lumios JWT.
//   4. Both the JWT and the Google profile are stored in sessionStorage so
//      they are cleared automatically when the tab closes.

// Shape returned by /api/v1/auth/me and /api/v1/auth/google/verify
export interface UserInfo {
  email: string;
  roles: string[];
  max_libraries: number | null;
  name?: string;
  picture?: string;
}

// Google profile fields decoded from the ID token (display only)
export interface GoogleProfile {
  name: string;
  email: string;
  picture: string;
  given_name?: string;
  family_name?: string;
}

const TOKEN_KEY = "lumios_token";
const PROFILE_KEY = "lumios_google_profile";

// GIS must only be initialized once per session. This flag is reset on logout
// so that a fresh initialize() call happens on the next login page visit.
let _gsiInitialized = false;
export function isGsiInitialized() {
  return _gsiInitialized;
}
export function markGsiInitialized() {
  _gsiInitialized = true;
}
export function resetGsiInitialized() {
  _gsiInitialized = false;
}

export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export const googleProfileStore = {
  get: (): GoogleProfile | null => {
    const raw = sessionStorage.getItem(PROFILE_KEY);
    return raw ? (JSON.parse(raw) as GoogleProfile) : null;
  },
  set: (p: GoogleProfile) =>
    sessionStorage.setItem(PROFILE_KEY, JSON.stringify(p)),
  clear: () => sessionStorage.removeItem(PROFILE_KEY),
};

// Decode the base64url-encoded JWT payload without verifying the signature.
// Used only to extract display fields from the Google ID token.
function decodeJwtPayload(token: string): Record<string, unknown> {
  try {
    const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(b64)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

// Internal helper: fetch JSON from the API, attaching the Bearer token.
async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = tokenStore.get();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(path, { ...init, headers });

  // Only parse as JSON when the response actually is JSON — otherwise a Flask
  // HTML error page would throw a misleading "Unexpected token '<'" error.
  const contentType = res.headers.get("content-type") ?? "";
  const data = contentType.includes("application/json") ? await res.json() : null;

  if (!res.ok) {
    throw new Error(
      (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`
    );
  }
  return data as T;
}

export const authApi = {
  // Verify the current JWT and return user info (guards protected routes).
  me: () => apiFetch<UserInfo>("/api/v1/auth/me"),

  // Exchange a Google ID token for a lumios JWT.
  // Also extracts and stores Google profile data for the info page.
  googleVerify: async (credential: string): Promise<UserInfo> => {
    const idPayload = decodeJwtPayload(credential);
    const profile: GoogleProfile = {
      name: String(idPayload.name ?? ""),
      email: String(idPayload.email ?? ""),
      picture: String(idPayload.picture ?? ""),
      given_name: idPayload.given_name ? String(idPayload.given_name) : undefined,
      family_name: idPayload.family_name ? String(idPayload.family_name) : undefined,
    };

    const data = await apiFetch<UserInfo & { token: string }>(
      "/api/v1/auth/google/verify",
      { method: "POST", body: JSON.stringify({ credential }) }
    );

    tokenStore.set(data.token);
    googleProfileStore.set(profile);
    return { email: data.email, roles: data.roles, max_libraries: data.max_libraries };
  },

  // Exchange a one-time login code (from the OAuth redirect) for a JWT.
  exchangeCode: async (code: string): Promise<void> => {
    const data = await apiFetch<{ token: string }>("/api/v1/auth/exchange", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
    tokenStore.set(data.token);
  },

  logout: () => {
    tokenStore.clear();
    googleProfileStore.clear();
    resetGsiInitialized();
    return Promise.resolve({ ok: true });
  },
};
