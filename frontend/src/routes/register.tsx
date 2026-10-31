// register.tsx — the /register page
//
// Supports two registration paths:
//   1. Google: GIS popup/callback mode → POST /api/v1/auth/google/register
//   2. Local:  email + password form   → POST /api/v1/auth/register
//
// Both paths require the user to accept the AGB and Datenschutzerklärung
// before the registration call is made.

import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { config } from "../config";
import { getApiErrorMessage } from "../api/errors";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { authApi, isGsiInitialized, markGsiInitialized, resetGsiInitialized } from "../api/auth";

const LANDING_URL = config.LANDING_URL;

export const Route = createFileRoute("/register")({
  component: RegisterPage,
});

function RegisterPage() {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const [successEmail, setSuccessEmail] = useState<string | null>(null);
  const [localPending, setLocalPending] = useState(false);
  const [googlePending, setGooglePending] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [agbAccepted, setAgbAccepted] = useState(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    resetGsiInitialized();

    function handleGoogleCredential(response: { credential: string }) {
      if (!agbAccepted) {
        setError(t("register.acceptFirst"));
        return;
      }
      setError(null);
      setGooglePending(true);
      authApi
        .registerGoogle(response.credential)
        .then(() => setSuccessEmail(t("register.yourGoogleAccount")))
        .catch((err) => {
          setError(getApiErrorMessage(err, t));
          setGooglePending(false);
        });
    }

    function initGsi() {
      if (!config.GOOGLE_CLIENT_ID || !window.google || isGsiInitialized()) return;
      markGsiInitialized();

      window.google.accounts.id.initialize({
        client_id: config.GOOGLE_CLIENT_ID,
        callback: handleGoogleCredential,
      });

      if (googleBtnRef.current) {
        window.google.accounts.id.renderButton(googleBtnRef.current, {
          theme: "outline",
          size: "large",
          text: "signup_with",
        });
      }
    }

    if (window.google) {
      initGsi();
    } else {
      const script = document.querySelector('script[src*="accounts.google.com/gsi"]');
      script?.addEventListener("load", initGsi);
      return () => script?.removeEventListener("load", initGsi);
    }
  // Re-initialise GIS when agbAccepted changes so the callback closure is fresh.
  }, [agbAccepted, t]);

  async function handleLocalRegister(e: { preventDefault(): void }) {
    e.preventDefault();
    setError(null);

    if (!agbAccepted) {
      setError(t("register.acceptRequired"));
      return;
    }
    if (password !== confirmPassword) {
      setError(t("register.passwordMismatch"));
      return;
    }

    setLocalPending(true);
    try {
      await authApi.register(email, password);
      setSuccessEmail(email);
    } catch (err) {
      setError(getApiErrorMessage(err, t));
      setLocalPending(false);
    }
  }

  if (successEmail) {
    return (
      <main className="login-page">
        <LanguageSwitcher className="lang-switch--corner" />
        <div className="login-box">
          <h2>{t("register.checkEmail")}</h2>
          <p style={{ textAlign: "center", lineHeight: 1.6 }}>
            <Trans
              i18nKey="register.activationSent"
              values={{ email: successEmail }}
              components={{ strong: <strong /> }}
            />
          </p>
          <Link
            to="/login"
            className="btn btn-outlined"
            style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }}
          >
            {t("activate.backToSignIn")}
          </Link>
        </div>
      </main>
    );
  }

  const agbLabel = (
    <span style={{ fontSize: "0.875rem" }}>
      {t("register.accept")}{" "}
      <a href={`${LANDING_URL}/agb.html`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--clr-primary)" }}>
        {t("register.terms")}
      </a>
      ,{" "}
      <a href={`${LANDING_URL}/datenschutz.html`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--clr-primary)" }}>
        {t("register.privacy")}
      </a>
      {t("register.andThe")}{" "}
      <a href={`${LANDING_URL}/avv.html`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--clr-primary)" }}>
        {t("register.avv")}
      </a>
    </span>
  );

  return (
    <main className="login-page">
      <LanguageSwitcher className="lang-switch--corner" />
      <div className="login-box">
        <h2>{t("register.title")}</h2>
        {error && <div className="flash">{error}</div>}

        {/* AGB checkbox — shared gate for both paths */}
        <label style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", marginBottom: "1rem", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={agbAccepted}
            onChange={(e) => setAgbAccepted(e.target.checked)}
            style={{ marginTop: "2px", flexShrink: 0 }}
          />
          {agbLabel}
        </label>

        {/* Google sign-up button */}
        {googlePending ? (
          <p className="login-pending" style={{ textAlign: "center" }}>{t("register.registering")}</p>
        ) : (
          <div
            style={{ cursor: agbAccepted ? undefined : "not-allowed" }}
            title={agbAccepted ? undefined : t("register.acceptFirstHint")}
          >
            <div
              className="google-btn-wrapper"
              ref={googleBtnRef}
              style={{ opacity: agbAccepted ? 1 : 0.4, pointerEvents: agbAccepted ? "auto" : "none", transition: "opacity 0.2s" }}
            />
          </div>
        )}

        <div className="divider">{t("login.or")}</div>

        <form className="login-form" onSubmit={handleLocalRegister}>
          <div className="text-field">
            <label htmlFor="reg-email">{t("common.email")}</label>
            <input
              id="reg-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="text-field">
            <label htmlFor="reg-password">{t("common.password")}</label>
            <input
              id="reg-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <div className="text-field">
            <label htmlFor="reg-confirm">{t("register.confirmPassword")}</label>
            <input
              id="reg-confirm"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </div>
          <span
            title={agbAccepted ? undefined : t("register.acceptFirstHint")}
            style={{ display: "block", cursor: agbAccepted ? undefined : "not-allowed" }}
          >
            <button
              type="submit"
              className="btn btn-contained"
              disabled={localPending}
              style={{ width: "100%", justifyContent: "center", fontSize: "1rem", fontWeight: 600, pointerEvents: agbAccepted ? undefined : "none" }}
            >
              {localPending ? t("register.creating") : t("register.title")}
            </button>
          </span>
        </form>

        <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.875rem" }}>
          {t("register.haveAccount")}{" "}
          <Link to="/login" style={{ color: "var(--clr-primary)" }}>
            {t("login.signIn")}
          </Link>
        </p>
      </div>
    </main>
  );
}
