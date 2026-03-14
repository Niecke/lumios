// index.tsx — user info page at /
//
// Shows the Google profile data fetched from the GIS ID token (name, picture,
// email, …) together with backend-specific info (roles, max_libraries).
// beforeLoad verifies the stored JWT; invalid/expired tokens send the user
// back to /login.

import { createFileRoute, redirect, useRouter } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { authApi, googleProfileStore, type UserInfo } from "../api/auth";

export const Route = createFileRoute("/")({
  beforeLoad: async () => {
    try {
      const user = await authApi.me();
      return { user };
    } catch {
      throw redirect({ to: "/login" });
    }
  },
  component: UserInfoPage,
});

function UserInfoPage() {
  const { user } = Route.useRouteContext() as { user: UserInfo };
  const router = useRouter();
  const profile = googleProfileStore.get();

  const logout = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => router.navigate({ to: "/login" }),
  });

  return (
    <div>
      <nav>
        <span>{user.email}</span>
        <button onClick={() => logout.mutate()} disabled={logout.isPending}>
          {logout.isPending ? "Logging out…" : "Logout"}
        </button>
      </nav>

      <main>
        <div className="profile-card">
          {profile?.picture && (
            <img
              className="profile-avatar"
              src={profile.picture}
              alt="Profile picture"
              referrerPolicy="no-referrer"
            />
          )}

          <h1>{profile?.name ?? user.email}</h1>

          <table className="profile-table">
            <tbody>
              <tr>
                <th>Email</th>
                <td>{user.email}</td>
              </tr>
              {profile?.given_name && (
                <tr>
                  <th>First name</th>
                  <td>{profile.given_name}</td>
                </tr>
              )}
              {profile?.family_name && (
                <tr>
                  <th>Last name</th>
                  <td>{profile.family_name}</td>
                </tr>
              )}
              <tr>
                <th>Roles</th>
                <td>{user.roles.join(", ") || "none"}</td>
              </tr>
              <tr>
                <th>Max libraries</th>
                <td>{user.max_libraries ?? "—"}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
