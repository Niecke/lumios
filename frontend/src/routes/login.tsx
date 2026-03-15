// login.tsx — the /login page
//
// Authentication is handled entirely in the browser via Google Identity
// Services (GIS). We render our own button and call prompt() on click —
// this avoids loading Google's iframe-based button which requires the origin
// to be verified before the button even appears.
//
// GIS calls handleCredential with a signed Google ID token which we forward
// to the backend (/api/v1/auth/google/verify).

import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { authApi, tokenStore, isGsiInitialized, markGsiInitialized, resetGsiInitialized } from "../api/auth";

interface GsiPromptNotification {
  isNotDisplayed(): boolean;
  isSkippedMoment(): boolean;
  getNotDisplayedReason(): string;
}

// Minimal type declaration for the GIS library loaded via index.html
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }): void;
          prompt(
            callback?: (notification: GsiPromptNotification) => void
          ): void;
        };
      };
    };
  }
}

// GIS initialization flag is managed in auth.ts so that logout can reset it.

export const Route = createFileRoute("/login")({
  beforeLoad: () => {
    // Already authenticated → the index route's beforeLoad will verify and
    // redirect to / on its own; nothing to do here.
  },
  component: LoginPage,
});

function LoginPage() {
  const router = useRouter();
  // Keep the callback in a ref so initialize() always calls the latest version
  // even though it is only registered once.
  const handleCredentialRef = useRef<
    ((r: { credential: string }) => void) | undefined
  >(undefined);
  const [error, setError] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    const err = params.get("error");
    if (err) window.history.replaceState(null, "", window.location.pathname);
    return err ? err.replace(/_/g, " ") : null;
  });
  const [pending, setPending] = useState(false);

  async function handleCredential(response: { credential: string }) {
    // GIS may fire the callback without a credential in error/initialization edge cases
    if (!response.credential) return;
    setError(null);
    setPending(true);
    try {
      await authApi.googleVerify(response.credential);
      router.navigate({ to: "/", replace: true });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Login failed");
      setPending(false);
    }
  }

  // Keep the ref current on every render
  handleCredentialRef.current = handleCredential;

  useEffect(() => {
    if (tokenStore.get()) {
      router.navigate({ to: "/", replace: true });
      return;
    }

    // No valid token — ensure GIS is (re-)initialized so prompt() works.
    // This handles the case where a session expired without going through
    // the explicit logout flow (which normally resets the flag).
    resetGsiInitialized();

    function initGsi() {
      if (!window.google || isGsiInitialized()) return;
      markGsiInitialized();
      window.google.accounts.id.initialize({
        client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID as string,
        callback: (r) => handleCredentialRef.current?.(r),
      });
    }

    if (window.google) {
      initGsi();
    } else {
      const script = document.querySelector(
        'script[src*="accounts.google.com/gsi"]'
      );
      script?.addEventListener("load", initGsi);
      return () => script?.removeEventListener("load", initGsi);
    }
  }, [router]);

  function handleGoogleSignIn() {
    window.google?.accounts.id.prompt((notification) => {
      if (notification.isNotDisplayed()) {
        setError(
          `Google Sign-In could not be shown (${notification.getNotDisplayedReason()}). ` +
            "Make sure your browser allows pop-ups and third-party cookies."
        );
      }
    });
  }

  return (
    <main className="login-page">
      <div className="login-box">
        <h2>Lumios</h2>
        {error && <div className="flash">{error}</div>}
        {pending ? (
          <p className="login-pending">Signing in…</p>
        ) : (
          <button className="btn btn-google" onClick={handleGoogleSignIn}>
            Sign in with Google
          </button>
        )}
      </div>
    </main>
  );
}
