// account.tsx — photographer account info page at /account
//
// Shows Google profile (avatar, name, email), account details (subscription,
// storage usage), and a progress bar for storage usage.

import { createFileRoute, redirect, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { getApiErrorMessage } from "../api/errors";
import { formatBytes, formatDate } from "../i18n";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { authApi, type UserInfo } from "../api/auth";
import { AppBar } from "../components/AppBar";

export const Route = createFileRoute("/account")({
  beforeLoad: async () => {
    try {
      const user = await authApi.me();
      return { user };
    } catch {
      throw redirect({ to: "/login" });
    }
  },
  component: AccountPage,
});

// ── Progress bar ──────────────────────────────────────────────────────────────

interface StorageProgressProps {
  used: number;
  limit: number | null;
}

function StorageProgress({ used, limit }: StorageProgressProps) {
  const { t } = useTranslation();
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  const fillClass =
    pct >= 100 ? "progress-fill--full" : pct >= 75 ? "progress-fill--warning" : "";

  return (
    <div className="progress-section">
      <div className="progress-header">
        <span className="progress-header__label">{t("account.storage")}</span>
        <span className="progress-header__count">
          {formatBytes(used)} / {limit != null ? formatBytes(limit) : "\u221e"}
        </span>
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${fillClass}`}
          style={{ width: limit ? `${pct}%` : "0%" }}
        />
      </div>
      <p className="progress-caption">
        {limit === null
          ? t("account.noLimit")
          : pct >= 100
          ? t("account.limitReached")
          : t("account.remaining", { size: formatBytes(limit - used) })}
      </p>
    </div>
  );
}

// ── Change password card (local accounts only) ────────────────────────────────

function ChangePasswordCard() {
  const { t } = useTranslation();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e: { preventDefault(): void }) {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError(t("account.passwordMismatch"));
      return;
    }
    setError(null);
    setSuccess(false);
    setPending(true);
    try {
      await authApi.changePassword(currentPassword, newPassword);
      setSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(getApiErrorMessage(err, t));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="account-card">
      <div style={{ padding: "1.25rem 1.5rem" }}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 500, marginBottom: "1rem" }}>
          {t("account.changePasswordTitle")}
        </h2>
        {error && (
          <div className="alert alert--error" style={{ marginBottom: "1rem" }}>
            {error}
          </div>
        )}
        {success && (
          <div className="alert alert--success" style={{ marginBottom: "1rem" }}>
            {t("account.passwordChanged")}
          </div>
        )}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div className="text-field">
            <label htmlFor="current-password">{t("account.currentPassword")}</label>
            <input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
          </div>
          <div className="text-field">
            <label htmlFor="new-password">{t("account.newPassword")}</label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
          </div>
          <div className="text-field">
            <label htmlFor="confirm-password">{t("account.confirmNewPassword")}</label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </div>
          <button
            type="submit"
            className="btn btn-contained"
            disabled={pending}
            style={{ alignSelf: "flex-start" }}
          >
            {pending ? t("common.saving") : t("account.changePassword")}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Deactivate account card (Danger Zone) ────────────────────────────────────

function DeactivateAccountCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleDeactivate() {
    setError(null);
    setPending(true);
    try {
      await authApi.deactivateAccount();
      authApi.logout();
      navigate({ to: "/login" });
    } catch (err) {
      setError(getApiErrorMessage(err, t));
      setPending(false);
    }
  }

  return (
    <div className="account-card" style={{ borderColor: "#dc2626" }}>
      <div style={{ padding: "1.25rem 1.5rem" }}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 500, marginBottom: "0.5rem", color: "#dc2626" }}>
          {t("account.dangerZone")}
        </h2>
        <p style={{ marginBottom: "1rem", color: "#555", fontSize: "0.9rem" }}>
          <Trans i18nKey="account.deactivateWarning" components={{ strong: <strong /> }} />
        </p>

        {error && (
          <div className="alert alert--error" style={{ marginBottom: "1rem" }}>
            {error}
          </div>
        )}

        {!confirming ? (
          <button
            type="button"
            className="btn btn-contained"
            style={{ background: "#dc2626", borderColor: "#dc2626" }}
            onClick={() => setConfirming(true)}
          >
            {t("account.deactivate")}
          </button>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <p style={{ fontWeight: 500, color: "#dc2626", margin: 0 }}>
              {t("account.deactivateConfirm")}
            </p>
            <div style={{ display: "flex", gap: "0.75rem" }}>
              <button
                type="button"
                className="btn btn-contained"
                style={{ background: "#dc2626", borderColor: "#dc2626" }}
                disabled={pending}
                onClick={handleDeactivate}
              >
                {pending ? t("account.deactivating") : t("account.deactivateYes")}
              </button>
              <button
                type="button"
                className="btn btn-text"
                disabled={pending}
                onClick={() => { setConfirming(false); setError(null); }}
              >
                {t("common.cancel")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Account page ──────────────────────────────────────────────────────────────

function AccountPage() {
  const { t, i18n } = useTranslation();
  const { user } = Route.useRouteContext() as { user: UserInfo };

  const displayName = user.name ?? user.email;

  return (
    <>
      <AppBar name={user.name} picture={user.picture} />

      <main className="page-content">
        <div className="page-header">
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <Link to="/" className="btn btn-text" style={{ padding: "0 0.5rem" }}>
              <span className="material-icons" style={{ fontSize: 20 }}>arrow_back</span>
            </Link>
            <h1>{t("account.title")}</h1>
          </div>
        </div>

        <div className="account-layout">
          <div className="account-card">
            <div className="account-card__header">
              {user.picture ? (
                <img
                  className="account-avatar"
                  src={user.picture}
                  alt={displayName}
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="account-avatar-placeholder">
                  <span className="material-icons">person</span>
                </div>
              )}
              <div className="account-card__name">{displayName}</div>
              <div className="account-card__email">{user.email}</div>
            </div>

            <div className="account-card__body">
              <div className="info-row">
                <span className="info-row__label">{t("account.subscription")}</span>
                <span className="chip">{user.subscription ?? "—"}</span>
              </div>
              <div className="info-row">
                <span className="info-row__label">{t("account.accountType")}</span>
                <span>{user.account_type ?? "—"}</span>
              </div>
              <div className="info-row">
                <span className="info-row__label">{t("account.memberSince")}</span>
                <span>
                  {user.created_at ? formatDate(user.created_at, i18n.language) : "—"}
                </span>
              </div>
              <div className="info-row">
                <span className="info-row__label">{t("account.language")}</span>
                <LanguageSwitcher />
              </div>
            </div>

            <StorageProgress used={user.storage_used_bytes} limit={user.storage_limit_bytes} />
          </div>

          {user.account_type === "local" && <ChangePasswordCard />}
          <DeactivateAccountCard />
        </div>
      </main>
    </>
  );
}
