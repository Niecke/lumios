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
import { authApi, isGsiInitialized, markGsiInitialized, resetGsiInitialized } from "../api/auth";

const LANDING_URL = (import.meta.env.VITE_LANDING_URL as string | undefined) ?? "";

export const Route = createFileRoute("/register")({
  component: RegisterPage,
});

function RegisterPage() {
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
        setError("Please accept the Terms of Service and Privacy Policy before continuing.");
        return;
      }
      setError(null);
      setGooglePending(true);
      authApi
        .registerGoogle(response.credential)
        .then(() => setSuccessEmail("your Google account"))
        .catch((err) => {
          setError((err as Error).message);
          setGooglePending(false);
        });
    }

    function initGsi() {
      if (!window.google || isGsiInitialized()) return;
      markGsiInitialized();

      window.google.accounts.id.initialize({
        client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID as string,
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
  }, [agbAccepted]);

  async function handleLocalRegister(e: { preventDefault(): void }) {
    e.preventDefault();
    setError(null);

    if (!agbAccepted) {
      setError("Please accept the Terms of Service and Privacy Policy.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLocalPending(true);
    try {
      await authApi.register(email, password);
      setSuccessEmail(email);
    } catch (err) {
      setError((err as Error).message);
      setLocalPending(false);
    }
  }

  if (successEmail) {
    return (
      <main className="login-page">
        <div className="login-box">
          <h2>Check your email</h2>
          <p style={{ textAlign: "center", lineHeight: 1.6 }}>
            We sent an activation link to <strong>{successEmail}</strong>.
            Please click the link in the email to activate your account before signing in.
          </p>
          <Link
            to="/login"
            className="btn btn-outlined"
            style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }}
          >
            Back to sign in
          </Link>
        </div>
      </main>
    );
  }

  const agbLabel = (
    <span style={{ fontSize: "0.875rem" }}>
      I accept the{" "}
      <a href={`${LANDING_URL}/agb.html`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--clr-primary)" }}>
        Terms of Service
      </a>
      ,{" "}
      <a href={`${LANDING_URL}/datenschutz.html`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--clr-primary)" }}>
        Privacy Policy
      </a>
      , and the{" "}
      <a href={`${LANDING_URL}/avv.html`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--clr-primary)" }}>
        Data Processing Agreement (AVV)
      </a>
    </span>
  );

  return (
    <main className="login-page">
      <div className="login-box">
        <h2>Create account</h2>
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
          <p className="login-pending" style={{ textAlign: "center" }}>Registering…</p>
        ) : (
          <div
            style={{ cursor: agbAccepted ? undefined : "not-allowed" }}
            title={agbAccepted ? undefined : "Bitte akzeptiere zuerst die AGB und Datenschutzerklärung."}
          >
            <div
              className="google-btn-wrapper"
              ref={googleBtnRef}
              style={{ opacity: agbAccepted ? 1 : 0.4, pointerEvents: agbAccepted ? "auto" : "none", transition: "opacity 0.2s" }}
            />
          </div>
        )}

        <div className="divider">or</div>

        <form className="login-form" onSubmit={handleLocalRegister}>
          <div className="text-field">
            <label htmlFor="reg-email">Email</label>
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
            <label htmlFor="reg-password">Password</label>
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
            <label htmlFor="reg-confirm">Confirm password</label>
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
            title={agbAccepted ? undefined : "Bitte akzeptiere zuerst die AGB und Datenschutzerklärung."}
            style={{ display: "block", cursor: agbAccepted ? undefined : "not-allowed" }}
          >
            <button
              type="submit"
              className="btn btn-contained"
              disabled={localPending}
              style={{ width: "100%", justifyContent: "center", fontSize: "1rem", fontWeight: 600, pointerEvents: agbAccepted ? undefined : "none" }}
            >
              {localPending ? "Creating account…" : "Create account"}
            </button>
          </span>
        </form>

        <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.875rem" }}>
          Already have an account?{" "}
          <Link to="/login" style={{ color: "var(--clr-primary)" }}>
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
