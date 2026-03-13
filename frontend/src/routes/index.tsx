// index.tsx — the dashboard at /
//
// This is the main protected page. beforeLoad calls /api/v1/auth/me to verify
// the stored JWT. If the token is missing or expired the user is sent to /login.

import { createFileRoute, redirect, useRouter } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { authApi, type UserInfo } from "../api/auth";

export const Route = createFileRoute("/")({
  // Guard: verify the token before rendering. The returned user is passed to
  // the component via Route.useRouteContext().
  beforeLoad: async () => {
    try {
      const user = await authApi.me();
      return { user };
    } catch {
      // Token missing, expired, or invalid → send to login
      throw redirect({ to: "/login" });
    }
  },
  component: Dashboard,
});

function Dashboard() {
  const { user } = Route.useRouteContext() as { user: UserInfo };
  const router = useRouter();

  const logout = useMutation({
    mutationFn: authApi.logout,
    // After clearing the token, navigate to login
    onSuccess: () => router.navigate({ to: "/login" }),
  });

  return (
    <div>
      <nav>
        <span>{user.email}</span>
        <button onClick={() => logout.mutate()} disabled={logout.isPending}>
          Logout
        </button>
      </nav>
      <main>
        <h1>Dashboard</h1>
        <p>Roles: {user.roles.join(", ") || "none"}</p>
      </main>
    </div>
  );
}
