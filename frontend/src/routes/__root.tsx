import { createRootRoute, Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { fetchVersion, formatFooterVersion } from "../api/version";
import { CookieBanner } from "../components/CookieBanner";
import { FeedbackWidget } from "../components/FeedbackWidget";

function Footer() {
  const { data } = useQuery({
    queryKey: ["version"],
    queryFn: fetchVersion,
    staleTime: Infinity,
  });
  return (
    <footer className="footer">
      <p>&copy; 2026 Lumios &middot; <span className="text-muted">{formatFooterVersion(data)}</span></p>
    </footer>
  );
}

export const Route = createRootRoute({
  component: () => (
    <>
      <div className="app-content">
        <Outlet />
      </div>
      <Footer />
      <CookieBanner />
      <FeedbackWidget />
    </>
  ),
});
