// account.tsx — photographer account info page at /account
//
// Shows Google profile (avatar, name, email), assigned roles, and a progress
// bar for library usage (libraries used / max libraries).

import { createFileRoute, redirect } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { authApi, googleProfileStore, type UserInfo } from "../api/auth";
import { librariesApi } from "../api/libraries";
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

interface LibraryProgressProps {
  count: number;
  max: number | null;
}

function LibraryProgress({ count, max }: LibraryProgressProps) {
  const pct = max ? Math.min(100, (count / max) * 100) : 0;
  const fillClass =
    pct >= 100 ? "progress-fill--full" : pct >= 75 ? "progress-fill--warning" : "";

  return (
    <div className="progress-section">
      <div className="progress-header">
        <span className="progress-header__label">Libraries</span>
        <span className="progress-header__count">
          {count} / {max ?? "∞"}
        </span>
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${fillClass}`}
          style={{ width: max ? `${pct}%` : "0%" }}
        />
      </div>
      <p className="progress-caption">
        {max === null
          ? "No library limit set."
          : pct >= 100
          ? "Limit reached — delete a library to create a new one."
          : `${max - count} slot${max - count === 1 ? "" : "s"} remaining.`}
      </p>
    </div>
  );
}

// ── Account page ──────────────────────────────────────────────────────────────

function AccountPage() {
  const { user } = Route.useRouteContext() as { user: UserInfo };
  const profile = googleProfileStore.get();

  const { data: libraryData } = useQuery({
    queryKey: ["libraries"],
    queryFn: librariesApi.list,
  });

  const count = libraryData?.count ?? 0;
  const max = libraryData?.max_libraries ?? user.max_libraries;

  const displayName = profile?.name ?? user.email;

  return (
    <>
      <AppBar email={user.email} />

      <main className="page-content">
        <div className="page-header">
          <h1>Account</h1>
        </div>

        <div className="account-layout">
          <div className="account-card">
            <div className="account-card__header">
              {profile?.picture ? (
                <img
                  className="account-avatar"
                  src={profile.picture}
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
              {profile?.given_name && (
                <div className="info-row">
                  <span className="info-row__label">First name</span>
                  <span>{profile.given_name}</span>
                </div>
              )}
              {profile?.family_name && (
                <div className="info-row">
                  <span className="info-row__label">Last name</span>
                  <span>{profile.family_name}</span>
                </div>
              )}
              <div className="info-row">
                <span className="info-row__label">Roles</span>
                <span style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                  {user.roles.length > 0
                    ? user.roles.map((r) => (
                        <span key={r} className="chip">
                          {r}
                        </span>
                      ))
                    : "—"}
                </span>
              </div>
            </div>

            <LibraryProgress count={count} max={max} />
          </div>
        </div>
      </main>
    </>
  );
}
