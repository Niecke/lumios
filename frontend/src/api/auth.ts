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

import {
  applyAccountLocale,
  currentLocale,
  setLocale,
  storedLocale,
  type Locale,
} from "../i18n/index.ts";

// Shape returned by /api/v1/auth/me
export interface UserInfo {
  email: string;
  created_at: string | null;
  account_type: string | null;
  subscription: string | null;
  language: Locale | null; // null: the account has no preference yet
  storage_used_bytes: number;
  storage_limit_bytes: number | null;
  max_libraries: number | null;
  max_images_per_library: number | null;
  name?: string;
  picture?: string;
}

const TOKEN_KEY = "lumios_token";
// Set when a language was picked with a switcher in this tab (sessionStorage:
// gone when the tab closes, cleared on logout). Only such a choice is copied to
// an account without a language at login, never one left in localStorage by an
// earlier visitor of a shared browser.
const LOCALE_CHOSEN_KEY = "lumios_locale_chosen";

// me() waits this long at most for a language save in flight, so a stalled
// PATCH never holds up the route guards.
export const LANGUAGE_SAVE_WAIT_MS = 2000;

// Language update in flight: me() waits for it (bounded). Cleared when it settles.
let languageUpdate: Promise<unknown> | null = null;
// The account language applies once per page load and at login. After that a
// language chosen in this browser stays, whichever switcher it came from.
let accountLanguageApplied = false;
// A language whose save to the account failed: the next me() tries again, once.
let unsavedLanguage: Locale | null = null;

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

// Drop every piece of client-side session state. Used on logout and when the
// backend rejects the stored token, so the login page can initialise GIS again.
const sessionClearedListeners = new Set<() => void>();
export function onSessionCleared(fn: () => void) {
  sessionClearedListeners.add(fn);
  return () => {
    sessionClearedListeners.delete(fn);
  };
}

function clearAuthSession() {
  tokenStore.clear();
  sessionClearedListeners.forEach((fn) => fn());
  resetGsiInitialized();
  languageUpdate = null;
  accountLanguageApplied = false;
  unsavedLanguage = null;
  try {
    sessionStorage.removeItem(LOCALE_CHOSEN_KEY);
  } catch {
    // storage blocked: nothing stored
  }
}

function markLocaleChosen() {
  try {
    sessionStorage.setItem(LOCALE_CHOSEN_KEY, "1");
  } catch {
    // storage blocked: the choice is not copied to the account at login
  }
}

function localeChosenInThisTab(): boolean {
  try {
    return sessionStorage.getItem(LOCALE_CHOSEN_KEY) === "1";
  } catch {
    return false;
  }
}

// Wait for a pending save, but never longer than LANGUAGE_SAVE_WAIT_MS.
function waitForLanguageUpdate(update: Promise<unknown>): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, LANGUAGE_SAVE_WAIT_MS);
  });
  return Promise.race([update.then(() => {}, () => {}), timeout]).finally(() =>
    clearTimeout(timer)
  );
}

// Store the language on the account. A failed save is kept for one retry by the
// next me(); a failed retry is dropped, so a permanent error costs one extra
// request, not one per navigation.
function saveLanguage(language: Locale, isRetry: boolean) {
  accountLanguageApplied = true; // this choice is newer than the account's value
  unsavedLanguage = null;
  const request = apiFetch<UserInfo>("/api/v1/auth/me", {
    method: "PATCH",
    body: JSON.stringify({ language }),
  });
  languageUpdate = request;
  request.then(
    () => {
      if (languageUpdate === request) languageUpdate = null;
    },
    () => {
      if (languageUpdate !== request) return; // a newer update started
      languageUpdate = null;
      // Keep it for a retry, unless this was the retry or the session ended.
      if (!isRetry && tokenStore.get()) unsavedLanguage = language;
    }
  );
  return request;
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
    // An expired or invalid token must not survive: otherwise /login sees it
    // and redirects straight back to a protected route (redirect loop).
    // A wrong current password on change_password is also a 401 but the
    // session itself is still valid.
    if (
      res.status === 401 &&
      token &&
      (data as { error?: string } | null)?.error !== "Current password is incorrect"
    ) {
      clearAuthSession();
    }
    const err = new Error(
      (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`
    );
    (err as any).code = (data as { code?: string } | null)?.code;
    (err as any).status = res.status;
    throw err;
  }
  return data as T;
}

export const authApi = {
  // Verify the current JWT and return user info (guards protected routes).
  me: async () => {
    if (languageUpdate) await waitForLanguageUpdate(languageUpdate);
    const user = await apiFetch<UserInfo>("/api/v1/auth/me");
    if (!accountLanguageApplied) {
      accountLanguageApplied = true;
      applyAccountLocale(user.language);
    }
    const language = unsavedLanguage;
    unsavedLanguage = null;
    // Retry a failed save once, unless the language was switched again since.
    if (language !== null && language === currentLocale() && user.language !== language) {
      saveLanguage(language, true).catch(() => {});
      return { ...user, language };
    }
    return user;
  },

  // me() right after a login: an account without a language takes the choice made
  // with a switcher in this tab. No such choice means no save: the account stays
  // "no preference", even if localStorage holds an earlier visitor's language.
  meAfterLogin: async () => {
    accountLanguageApplied = false;
    const user = await authApi.me();
    const language = localeChosenInThisTab() ? storedLocale() : null;
    if (user.language !== null || language === null) return user;
    authApi.updateMe({ language }).catch(() => {}); // best effort, the UI keeps it anyway
    return { ...user, language };
  },

  // Store the UI language on the account (kept across devices).
  updateMe: (data: { language: Locale }) => saveLanguage(data.language, false),

  // Register a new local account (agb_accepted must be true). The language goes
  // along only if one was chosen in this browser: no choice, no account preference.
  register: (email: string, password: string) =>
    apiFetch<{ ok: boolean }>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, agb_accepted: true, language: storedLocale() ?? undefined }),
    }),

  // Register a new Google account (agb_accepted must be true).
  registerGoogle: (credential: string) =>
    apiFetch<{ ok: boolean }>("/api/v1/auth/google/register", {
      method: "POST",
      body: JSON.stringify({ credential, agb_accepted: true, language: storedLocale() ?? undefined }),
    }),

  // Activate an account using the token from the activation email.
  activate: (token: string) =>
    apiFetch<{ ok: boolean; email: string }>("/api/v1/auth/activate", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  // Request a fresh activation email by address, or by the token of an expired link.
  resendActivation: (target: { email: string } | { token: string }) =>
    apiFetch<{ ok: boolean }>("/api/v1/auth/resend-activation", {
      method: "POST",
      body: JSON.stringify(target),
    }),

  // Exchange a Google ID token for a lumios JWT.
  googleVerify: async (credential: string): Promise<UserInfo> => {
    const data = await apiFetch<UserInfo & { token: string }>(
      "/api/v1/auth/google/verify",
      { method: "POST", body: JSON.stringify({ credential }) }
    );

    tokenStore.set(data.token);
    return authApi.meAfterLogin();
  },

  // Exchange a one-time login code (from the OAuth redirect) for a JWT.
  exchangeCode: async (code: string): Promise<void> => {
    const data = await apiFetch<{ token: string }>("/api/v1/auth/exchange", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
    tokenStore.set(data.token);
  },

  // Authenticate with email and password, return a lumios JWT.
  loginPassword: async (email: string, password: string): Promise<UserInfo> => {
    const data = await apiFetch<{ token: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    tokenStore.set(data.token);
    return authApi.meAfterLogin();
  },

  // Change password for the authenticated local account.
  changePassword: (currentPassword: string, newPassword: string) =>
    apiFetch<{ ok: boolean }>("/api/v1/auth/change_password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  // Deactivate the authenticated account. Sets deleted_at; data is purged after 30 days.
  deactivateAccount: () =>
    apiFetch<{ ok: boolean }>("/api/v1/auth/account", { method: "DELETE" }),

  logout: () => {
    clearAuthSession();
    return Promise.resolve({ ok: true });
  },
};

// Switch the UI language. Only the photographer's own area (AppBar, account page)
// passes saveToAccount: public galleries and the auth pages stay local to the
// browser, they have no influence on a registered user.
export function chooseLanguage(lang: Locale, saveToAccount: boolean) {
  setLocale(lang);
  markLocaleChosen();
  if (saveToAccount && tokenStore.get()) {
    // Best effort: the local choice already applies even if saving fails.
    authApi.updateMe({ language: lang }).catch(() => {});
  }
}
