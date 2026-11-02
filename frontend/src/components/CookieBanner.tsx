import { useState } from "react";
import { useTranslation } from "react-i18next";

const STORAGE_KEY = "cookie_banner_dismissed";

export function CookieBanner() {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(
    () => localStorage.getItem(STORAGE_KEY) !== "1"
  );

  if (!visible) return null;

  function dismiss() {
    localStorage.setItem(STORAGE_KEY, "1");
    setVisible(false);
  }

  return (
    <div className="cookie-banner" role="region" aria-label={t("cookie.label")}>
      <p className="cookie-banner__text">
        {t("cookie.text")}
      </p>
      <button className="cookie-banner__btn" onClick={dismiss}>
        {t("cookie.dismiss")}
      </button>
    </div>
  );
}
