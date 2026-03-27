// account.tsx — photographer account info page at /account
//
// Shows Google profile (avatar, name, email), account details (subscription,
// storage usage), and a progress bar for storage usage.

import { createFileRoute, redirect, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

// ── Progress bar ──────────────────────────────────────────────────────────────

interface StorageProgressProps {
  used: number;
  limit: number | null;
}

function StorageProgress({ used, limit }: StorageProgressProps) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  const fillClass =
    pct >= 100 ? "progress-fill--full" : pct >= 75 ? "progress-fill--warning" : "";

  return (
    <div className="progress-section">
      <div className="progress-header">
        <span className="progress-header__label">Storage</span>
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
          ? "No storage limit set."
          : pct >= 100
          ? "Storage limit reached — delete photos to free up space."
          : `${formatBytes(limit - used)} remaining.`}
      </p>
    </div>
  );
}

// ── Change password card (local accounts only) ────────────────────────────────

function ChangePasswordCard() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e: { preventDefault(): void }) {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
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
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="account-card">
      <div style={{ padding: "1.25rem 1.5rem" }}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 500, marginBottom: "1rem" }}>
          Change Password
        </h2>
        {error && (
          <div className="alert alert--error" style={{ marginBottom: "1rem" }}>
            {error}
          </div>
        )}
        {success && (
          <div className="alert alert--success" style={{ marginBottom: "1rem" }}>
            Password changed successfully.
          </div>
        )}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div className="text-field">
            <label htmlFor="current-password">Current password</label>
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
            <label htmlFor="new-password">New password</label>
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
            <label htmlFor="confirm-password">Confirm new password</label>
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
            {pending ? "Saving…" : "Change password"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Account page ──────────────────────────────────────────────────────────────

function AccountPage() {
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
            <h1>Account</h1>
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
                <span className="info-row__label">Subscription</span>
                <span className="chip">{user.subscription ?? "—"}</span>
              </div>
              <div className="info-row">
                <span className="info-row__label">Account type</span>
                <span>{user.account_type ?? "—"}</span>
              </div>
              <div className="info-row">
                <span className="info-row__label">Member since</span>
                <span>
                  {user.created_at
                    ? new Date(user.created_at).toLocaleDateString()
                    : "—"}
                </span>
              </div>
            </div>

            <StorageProgress used={user.storage_used_bytes} limit={user.storage_limit_bytes} />
          </div>

          {user.account_type === "local" && <ChangePasswordCard />}
        </div>
      </main>
    </>
  );
}
