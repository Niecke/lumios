import { useState } from "react";

const STORAGE_KEY = "cookie_banner_dismissed";

export function CookieBanner() {
  const [visible, setVisible] = useState(
    () => localStorage.getItem(STORAGE_KEY) !== "1"
  );

  if (!visible) return null;

  function dismiss() {
    localStorage.setItem(STORAGE_KEY, "1");
    setVisible(false);
  }

  return (
    <div className="cookie-banner" role="region" aria-label="Cookie notice">
      <p className="cookie-banner__text">
        This site uses only essential cookies for session management and CSRF
        protection. No tracking or analytics.
      </p>
      <button className="cookie-banner__btn" onClick={dismiss}>
        Got it
      </button>
    </div>
  );
}
