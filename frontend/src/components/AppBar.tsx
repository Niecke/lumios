// AppBar.tsx — sticky top navigation shared across all authenticated pages

import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { authApi, googleProfileStore } from "../api/auth";

interface AppBarProps {
  email: string;
}

export function AppBar({ email }: AppBarProps) {
  const navigate = useNavigate();
  const profile = googleProfileStore.get();

  const logout = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => navigate({ to: "/login" }),
  });

  return (
    <header className="app-bar">
      <Link to="/" className="app-bar__brand">
        Lumios
      </Link>

      {profile?.picture && (
        <img
          className="app-bar__avatar"
          src={profile.picture}
          alt=""
          referrerPolicy="no-referrer"
        />
      )}
      <span className="app-bar__name">{profile?.name ?? email}</span>

      <Link to="/account" className="btn btn-text">
        <span className="material-icons">account_circle</span>
        Account
      </Link>

      <button
        className="btn btn-outlined"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
      >
        {logout.isPending ? "…" : "Logout"}
      </button>
    </header>
  );
}
