// auth.ts — all communication with the backend auth API
//
// The backend uses JWT Bearer tokens (not cookies).
// After login the token is kept in sessionStorage and attached to every request.
// sessionStorage is cleared when the browser tab is closed.

// Shape of the user object returned by /api/v1/auth/me and /api/v1/auth/login
export interface UserInfo {
  email: string;
  roles: string[];
}

// The login endpoint also returns the JWT token itself
interface LoginResponse extends UserInfo {
  token: string;
}

// Key under which the JWT is stored in sessionStorage
const TOKEN_KEY = "lumios_token";

// Simple wrapper around sessionStorage so all token access goes through one place
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

// Internal helper: fetch JSON from the API.
// Automatically attaches the Bearer token when one is stored.
// Throws an Error with the server's error message when the response is not 2xx.
async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = tokenStore.get();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(path, { ...init, headers });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? "Request failed");
  return data as T;
}

// Public API methods used throughout the app
export const authApi = {
  // Fetch the currently logged-in user's info (uses the stored token).
  // Returns 401 if no valid token → routes use this to guard protected pages.
  me: () => apiFetch<UserInfo>("/api/v1/auth/me"),

  // Password login: sends credentials, stores the returned JWT, resolves with user info.
  login: async (email: string, password: string): Promise<UserInfo> => {
    const data = await apiFetch<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    tokenStore.set(data.token);
    return { email: data.email, roles: data.roles };
  },

  // Logout: just removes the token locally (JWT is stateless — no server call needed).
  logout: () => {
    tokenStore.clear();
    return Promise.resolve({ ok: true });
  },
};
