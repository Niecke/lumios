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

type State = "pending" | "success" | "error";

function ActivatePage() {
  const [state, setState] = useState<State>("pending");
  const [email, setEmail] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

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
        setErrorMsg((err as Error).message);
        setState("error");
      });
  }, []);

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
        {state === "error" && (
          <>
            <h2>Activation failed</h2>
            <div className="flash">{errorMsg ?? "Unknown error"}</div>
            <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.875rem" }}>
              The link may have already been used or has expired.
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
