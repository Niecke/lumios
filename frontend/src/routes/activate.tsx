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

  const handleResend = () => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") ?? "";
    setResending(true);
    setResendError(null);
    authApi
      .resendActivation(token)
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
        {state === "expired" && (
          <>
            <h2>Link expired</h2>
            <p style={{ textAlign: "center", lineHeight: 1.6 }}>
              Your activation link has expired. Click below to receive a new one.
            </p>
            {resendSuccess ? (
              <p style={{ textAlign: "center", marginTop: "0.75rem", color: "var(--color-success, green)" }}>
                A new activation email has been sent. Please check your inbox.
              </p>
            ) : (
              <button
                className="btn btn-contained"
                style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }}
                onClick={handleResend}
                disabled={resending}
              >
                {resending ? "Sending…" : "Resend activation email"}
              </button>
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
        {state === "error" && (
          <>
            <h2>Activation failed</h2>
            <div className="flash">{errorMsg ?? "Unknown error"}</div>
            <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.875rem" }}>
              The link may have already been used or is invalid.
            </p>
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
