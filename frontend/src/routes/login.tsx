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
  const [localPending, setLocalPending] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const googleBtnRef = useRef<HTMLDivElement>(null);

  // On mount: check for code or error from the redirect callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const err = params.get("error");

    if (code) {
      window.history.replaceState(null, "", "/login");
      setPending(true);
      authApi.exchangeCode(code).then(
        () => authApi.me().then(
          () => router.navigate({ to: "/", replace: true }),
          () => {
            tokenStore.clear();
            setError("Session invalid. Please sign in again.");
            setPending(false);
          }
        ),
        () => {
          setError("Login failed. Please try again.");
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

  async function handlePasswordLogin(e: { preventDefault(): void }) {
    e.preventDefault();
    setError(null);
    setLocalPending(true);
    try {
      await authApi.loginPassword(email, password);
      await authApi.me();
      router.navigate({ to: "/", replace: true });
    } catch (err) {
      setError((err as Error).message);
      setLocalPending(false);
    }
  }

  return (
    <main className="login-page">
      <div className="login-box">
        <h2>Lumios</h2>
        {error && <div className="flash">{error}</div>}
        {pending ? (
          <p className="login-pending">Signing in…</p>
        ) : (
          <>
            <div className="google-btn-wrapper" ref={googleBtnRef} />
            <div className="divider">or</div>
            <form className="login-form" onSubmit={handlePasswordLogin}>
              <div className="text-field">
                <label htmlFor="login-email">Email</label>
                <input
                  id="login-email"
                  //type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="text-field">
                <label htmlFor="login-password">Password</label>
                <input
                  id="login-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              <button
                type="submit"
                className="btn btn-contained"
                disabled={localPending}
                style={{ width: "100%", justifyContent: "center", fontSize: "1rem", fontWeight: 600 }}
              >
                {localPending ? "Signing in…" : "Sign in"}
              </button>
            </form>
          </>
        )}
      </div>
    </main>
  );
}
