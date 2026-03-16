// login.tsx — the /login page
//
// Authentication uses Google Identity Services (GIS) in redirect mode.
// Clicking the Google button redirects to Google, which POSTs the credential
// to the backend callback endpoint. The backend verifies it, creates a JWT,
// and redirects back here with ?token=... which the SPA picks up.

import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { authApi, tokenStore, isGsiInitialized, markGsiInitialized, resetGsiInitialized } from "../api/auth";

// Minimal type declaration for the GIS library loaded via index.html
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
            ux_mode?: string;
            login_uri?: string;
          }): void;
          renderButton(
            parent: HTMLElement,
            options: {
              theme?: string;
              size?: string;
              width?: number;
              text?: string;
            }
          ): void;
        };
      };
    };
  }
}

export const Route = createFileRoute("/login")({
  beforeLoad: () => {},
  component: LoginPage,
});

function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);

  // On mount: check for token or error from the redirect callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const err = params.get("error");

    if (token) {
      tokenStore.set(token);
      window.history.replaceState(null, "", "/login");
      setPending(true);
      authApi.me().then(
        () => router.navigate({ to: "/", replace: true }),
        () => {
          tokenStore.clear();
          setError("Session invalid. Please sign in again.");
          setPending(false);
        }
      );
      return;
    }

    if (err) {
      window.history.replaceState(null, "", "/login");
      setError(err.replace(/_/g, " "));
    }

    if (tokenStore.get()) {
      router.navigate({ to: "/", replace: true });
      return;
    }

    resetGsiInitialized();

    const loginUri = `${window.location.origin}/api/v1/auth/google/callback`;

    function initGsi() {
      if (!window.google || isGsiInitialized()) return;
      markGsiInitialized();

      window.google.accounts.id.initialize({
        client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID as string,
        callback: () => {},
        ux_mode: "redirect",
        login_uri: loginUri,
      });

      if (googleBtnRef.current) {
        window.google.accounts.id.renderButton(googleBtnRef.current, {
          theme: "outline",
          size: "large",
          text: "signin_with",
        });
      }
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

  return (
    <main className="login-page">
      <div className="login-box">
        <h2>Lumios</h2>
        {error && <div className="flash">{error}</div>}
        {pending ? (
          <p className="login-pending">Signing in…</p>
        ) : (
          <div className="google-btn-wrapper" ref={googleBtnRef} />
        )}
      </div>
    </main>
  );
}
