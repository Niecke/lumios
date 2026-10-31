// login.tsx — the /login page
//
// Authentication uses Google Identity Services (GIS) in redirect mode.
// Clicking the Google button redirects to Google, which POSTs the credential
// to the backend callback endpoint. The backend verifies it, creates a JWT,
// and redirects back here with ?token=... which the SPA picks up.

import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { authApi, tokenStore, isGsiInitialized, markGsiInitialized, resetGsiInitialized } from "../api/auth";
import { useTranslation } from "react-i18next";
import { config } from "../config";
import { getApiErrorMessage } from "../api/errors";
import { LanguageSwitcher } from "../components/LanguageSwitcher";

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
  const { t } = useTranslation();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [notActivated, setNotActivated] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendDone, setResendDone] = useState(false);
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
            setError(t("login.sessionInvalid"));
            setPending(false);
          }
        ),
        () => {
          setError(t("login.failed"));
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
      if (!config.GOOGLE_CLIENT_ID || !window.google || isGsiInitialized()) return;
      markGsiInitialized();

      window.google.accounts.id.initialize({
        client_id: config.GOOGLE_CLIENT_ID,
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
  }, [router, t]);

  async function handlePasswordLogin(e: { preventDefault(): void }) {
    e.preventDefault();
    setError(null);
    setResendDone(false);
    setNotActivated(false);
    setLocalPending(true);
    try {
      await authApi.loginPassword(email, password);
      await authApi.me();
      router.navigate({ to: "/", replace: true });
    } catch (err) {
      const message = (err as Error).message;
      setError(getApiErrorMessage(err, t));
      setNotActivated(/not yet activated/i.test(message));
      setLocalPending(false);
    }
  }

  async function handleResendActivation() {
    setResending(true);
    try {
      await authApi.resendActivation({ email });
      setResendDone(true);
    } catch (err) {
      setError(getApiErrorMessage(err, t));
    } finally {
      setResending(false);
    }
  }

  return (
    <main className="login-page">
      <LanguageSwitcher className="lang-switch--corner" />
      <div className="login-box">
        <h2>Lumios</h2>
        {error && <div className="flash">{error}</div>}
        {notActivated &&
          (resendDone ? (
            <p style={{ textAlign: "center", fontSize: "0.875rem" }}>
              {t("login.resendDone")}
            </p>
          ) : (
            <button
              type="button"
              className="btn btn-outlined"
              style={{ width: "100%", justifyContent: "center", marginBottom: "1rem" }}
              onClick={handleResendActivation}
              disabled={resending}
            >
              {resending ? t("common.sending") : t("login.resend")}
            </button>
          ))}
        {pending ? (
          <p className="login-pending">{t("login.signingIn")}</p>
        ) : (
          <>
            <div className="google-btn-wrapper" ref={googleBtnRef} />
            <div className="divider">{t("login.or")}</div>
            <form className="login-form" onSubmit={handlePasswordLogin}>
              <div className="text-field">
                <label htmlFor="login-email">{t("common.email")}</label>
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
                <label htmlFor="login-password">{t("common.password")}</label>
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
                {localPending ? t("login.signingIn") : t("login.signIn")}
              </button>
            </form>
            <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.875rem" }}>
              {t("login.noAccount")}{" "}
              <Link to="/register" style={{ color: "var(--clr-primary)" }}>
                {t("login.createOne")}
              </Link>
            </p>
          </>
        )}
      </div>
    </main>
  );
}
