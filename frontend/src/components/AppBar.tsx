// AppBar.tsx — sticky top navigation shared across all authenticated pages

import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { authApi } from "../api/auth";

interface AppBarProps {
  name?: string;
  picture?: string;
}

export function AppBar({ name, picture }: AppBarProps) {
  const navigate = useNavigate();

  const logout = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => navigate({ to: "/login" }),
  });

  return (
    <header className="app-bar">
      <Link to="/" className="app-bar__brand">
        Lumios
      </Link>

      <Link to="/account" className="btn btn-text app-bar__account-btn">
        {picture ? (
          <img
            className="app-bar__avatar"
            src={picture}
            alt=""
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="material-icons">account_circle</span>
        )}
        {name ?? "Account"}
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
