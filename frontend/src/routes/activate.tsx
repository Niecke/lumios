// activate.tsx — the /activate page
//
// Reads ?token= from the URL, calls POST /api/v1/auth/activate,
// and shows a success or error message.

import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { authApi } from "../api/auth";
import { getApiErrorMessage } from "../api/errors";
import { LanguageSwitcher } from "../components/LanguageSwitcher";

export const Route = createFileRoute("/activate")({
  component: ActivatePage,
});

type State = "pending" | "success" | "error" | "expired";

function ActivatePage() {
  const { t } = useTranslation();
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
      setErrorMsg(t("activate.noToken"));
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
          setErrorMsg(getApiErrorMessage(err, t));
          setState("error");
        }
      });
  }, [t]);

  const handleResend = (e: { preventDefault(): void }) => {
    e.preventDefault();
    setResending(true);
    setResendError(null);
    authApi
      .resendActivation({ email: resendEmail })
      .then(() => setResendSuccess(true))
      .catch((err) => setResendError(getApiErrorMessage(err, t)))
      .finally(() => setResending(false));
  };

  return (
    <main className="login-page">
      <LanguageSwitcher className="lang-switch--corner" />
      <div className="login-box">
        {state === "pending" && (
          <>
            <h2>{t("activate.activating")}</h2>
            <p className="login-pending">{t("activate.wait")}</p>
          </>
        )}
        {state === "success" && (
          <>
            <h2>{t("activate.successTitle")}</h2>
            <p style={{ textAlign: "center", lineHeight: 1.6 }}>
              {email ? t("activate.successWithEmail", { email }) : t("activate.success")}
            </p>
            <Link
              to="/login"
              className="btn btn-contained"
              style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }}
            >
              {t("login.signIn")}
            </Link>
          </>
        )}
        {(state === "expired" || state === "error") && (
          <>
            <h2>{state === "expired" ? t("activate.expiredTitle") : t("activate.failedTitle")}</h2>
            {state === "error" && <div className="flash">{errorMsg ?? t("errors.unknown")}</div>}
            <p style={{ textAlign: "center", lineHeight: 1.6, marginTop: "1rem" }}>
              {state === "expired" ? t("activate.expiredText") : t("activate.invalidText")}{" "}
              {t("activate.enterEmail")}
            </p>
            {resendSuccess ? (
              <p style={{ textAlign: "center", marginTop: "0.75rem", color: "var(--color-success, green)" }}>
                {t("login.resendDone")}
              </p>
            ) : (
              <form className="login-form" onSubmit={handleResend}>
                <div className="text-field">
                  <label htmlFor="resend-email">{t("common.email")}</label>
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
                  {resending ? t("common.sending") : t("login.resend")}
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
              {t("activate.backToSignIn")}
            </Link>
          </>
        )}
      </div>
    </main>
  );
}
