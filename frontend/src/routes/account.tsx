// account.tsx — photographer account info page at /account
//
// Shows Google profile (avatar, name, email), account details (subscription,
// storage usage), and a progress bar for storage usage.

import { createFileRoute, redirect } from "@tanstack/react-router";
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

// ── Account page ──────────────────────────────────────────────────────────────

function AccountPage() {
  const { user } = Route.useRouteContext() as { user: UserInfo };

  const displayName = user.name ?? user.email;

  return (
    <>
      <AppBar name={user.name} picture={user.picture} />

      <main className="page-content">
        <div className="page-header">
          <h1>Account</h1>
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
        </div>
      </main>
    </>
  );
}
