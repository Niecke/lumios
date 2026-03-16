import { createRootRoute, Outlet } from "@tanstack/react-router";

const gitHash = (import.meta.env.VITE_GIT_SHA || "dev").slice(0, 8);

export const Route = createRootRoute({
  component: () => (
    <>
      <div className="app-content">
        <Outlet />
      </div>
      <footer className="footer">
        <p>&copy; 2026 Lumios &middot; <span className="text-muted">{gitHash}</span></p>
      </footer>
    </>
  ),
});
