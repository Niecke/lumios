// LanguageSwitcher.tsx — DE | EN toggle.
//
// Stores the choice in localStorage (setLocale) and, when a photographer is
// logged in, on the account so it follows them to other devices.

import { useTranslation } from "react-i18next";
import { authApi, tokenStore } from "../api/auth";
import { SUPPORTED_LOCALES, setLocale, currentLocale, type Locale } from "../i18n";

export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { t, i18n } = useTranslation();
  const active = i18n.language === "en" ? "en" : currentLocale();

  function choose(lang: Locale) {
    if (lang === active) return;
    setLocale(lang);
    if (tokenStore.get()) {
      // Best effort: the local choice already applies even if saving fails.
      authApi.updateMe({ language: lang }).catch(() => {});
    }
  }

  return (
    <div className={`lang-switch ${className}`.trim()} role="group" aria-label={t("language.label")}>
      {SUPPORTED_LOCALES.map((lang) => (
        <button
          key={lang}
          type="button"
          className={`lang-switch__btn${lang === active ? " lang-switch__btn--active" : ""}`}
          aria-pressed={lang === active}
          lang={lang}
          title={t(`language.${lang}`)}
          onClick={() => choose(lang)}
        >
          {lang.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
