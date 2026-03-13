// login.tsx — the /login page
//
// Handles two login methods:
//   1. Email + password  → POST /api/v1/auth/login
//   2. Google OAuth      → browser navigates to /api/v1/auth/google (backend handles the dance)
//
// After Google OAuth the backend redirects back to /login#token=JWT.
// The beforeLoad hook below intercepts that hash before the page renders,
// stores the token, and immediately redirects to the dashboard.

import { createFileRoute, useRouter, redirect } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { authApi, tokenStore } from "../api/auth";

export const Route = createFileRoute("/login")({
  // Runs before the component renders — used to catch the OAuth callback token.
  beforeLoad: ({ location }) => {
    // TanStack Router strips the leading "#" from location.hash.
    // We also fall back to window.location.hash in case the router normalised the URL.
    const hash = (location.hash ?? "").replace(/^#/, "");
    if (hash.startsWith("token=")) {
      tokenStore.set(hash.slice(6)); // "token=".length === 6
      throw redirect({ to: "/", replace: true });
    }
    const winHash = window.location.hash.replace(/^#/, "");
    if (winHash.startsWith("token=")) {
      tokenStore.set(winHash.slice(6));
      throw redirect({ to: "/", replace: true });
    }
  },
  component: LoginPage,
});

function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Read ?error=... set by the backend when Google OAuth fails, then clean the URL
  const [error, setError] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    const err = params.get("error");
    if (err) window.history.replaceState(null, "", window.location.pathname);
    return err ? err.replace(/_/g, " ") : null;
  });

  const login = useMutation({
    mutationFn: () => authApi.login(email, password),
    onSuccess: () => router.navigate({ to: "/" }),
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    login.mutate();
  }

  return (
    <main className="login-page">
      <div className="login-box">
        <h2>Lumios</h2>

        {/* Error banner — shown for both password failures and OAuth errors */}
        {error && <div className="flash">{error}</div>}

        {/* Password login form */}
        <form onSubmit={handleSubmit}>
          <input
            placeholder="E-Mail"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            type="password"
            placeholder="Password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button type="submit" disabled={login.isPending}>
            {login.isPending ? "Logging in…" : "Login"}
          </button>
        </form>

        <div className="divider">or</div>

        {/* Google OAuth — full browser navigation, not a fetch call.
            The backend handles the redirect to Google and the callback. */}
        <a href="/api/v1/auth/google" className="btn btn-google">
          Login with Google
        </a>
      </div>
    </main>
  );
}
