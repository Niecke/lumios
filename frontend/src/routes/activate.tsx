// activate.tsx — the /activate page
//
// Reads ?token= from the URL, calls POST /api/v1/auth/activate,
// and shows a success or error message.

import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { authApi } from "../api/auth";

export const Route = createFileRoute("/activate")({
  component: ActivatePage,
});

type State = "pending" | "success" | "error" | "expired";

function ActivatePage() {
  const [state, setState] = useState<State>("pending");
  const [email, setEmail] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const [resendSuccess, setResendSuccess] = useState(false);
  const [resendError, setResendError] = useState<string | null>(null);
  const [resendEmail, setResendEmail] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") ?? "";

    if (!token) {
      setErrorMsg("No activation token found in the URL.");
      setState("error");
      return;
    }

    authApi
      .activate(token)
      .then((res) => {
        setEmail(res.email);
        setState("success");
      })
      .catch((err) => {
        if ((err as any).code === "token_expired") {
          setState("expired");
        } else {
          setErrorMsg((err as Error).message);
          setState("error");
        }
      });
  }, []);

  const handleResend = (e: { preventDefault(): void }) => {
    e.preventDefault();
    setResending(true);
    setResendError(null);
    authApi
      .resendActivation({ email: resendEmail })
      .then(() => setResendSuccess(true))
      .catch((err) => setResendError((err as Error).message))
      .finally(() => setResending(false));
  };

  return (
    <main className="login-page">
      <div className="login-box">
        {state === "pending" && (
          <>
            <h2>Activating your account…</h2>
            <p className="login-pending">Please wait.</p>
          </>
        )}
        {state === "success" && (
          <>
            <h2>Account activated!</h2>
            <p style={{ textAlign: "center", lineHeight: 1.6 }}>
              Your account{email ? ` (${email})` : ""} has been activated successfully.
              You can now sign in.
            </p>
            <Link
              to="/login"
              className="btn btn-contained"
              style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }}
            >
              Sign in
            </Link>
          </>
        )}
        {(state === "expired" || state === "error") && (
          <>
            <h2>{state === "expired" ? "Link expired" : "Activation failed"}</h2>
            {state === "error" && <div className="flash">{errorMsg ?? "Unknown error"}</div>}
            <p style={{ textAlign: "center", lineHeight: 1.6, marginTop: "1rem" }}>
              {state === "expired"
                ? "Your activation link has expired. "
                : "The link may have already been used or is invalid. "}
              Enter your email address to receive a new one.
            </p>
            {resendSuccess ? (
              <p style={{ textAlign: "center", marginTop: "0.75rem", color: "var(--color-success, green)" }}>
                If an account exists and is pending activation, a new activation link has been sent.
              </p>
            ) : (
              <form className="login-form" onSubmit={handleResend}>
                <div className="text-field">
                  <label htmlFor="resend-email">Email</label>
                  <input
                    id="resend-email"
                    autoComplete="email"
                    value={resendEmail}
                    onChange={(e) => setResendEmail(e.target.value)}
                    required
                  />
                </div>
                <button
                  type="submit"
                  className="btn btn-contained"
                  style={{ width: "100%", justifyContent: "center" }}
                  disabled={resending}
                >
                  {resending ? "Sending…" : "Resend activation email"}
                </button>
              </form>
            )}
            {resendError && (
              <div className="flash" style={{ marginTop: "0.75rem" }}>{resendError}</div>
            )}
            <Link
              to="/login"
              className="btn btn-outlined"
              style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }}
            >
              Back to sign in
            </Link>
          </>
        )}
      </div>
    </main>
  );
}
