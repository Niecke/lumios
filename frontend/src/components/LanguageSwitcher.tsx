// LanguageSwitcher.tsx — DE | EN toggle.
//
// Stores the choice in localStorage. With saveToAccount (only the photographer's
// own area) a logged-in photographer also gets it on the account, so it follows
// them to other devices.

import { useTranslation } from "react-i18next";
import { chooseLanguage } from "../api/auth";
import { SUPPORTED_LOCALES, currentLocale, type Locale } from "../i18n";

export function LanguageSwitcher({
  className = "",
  saveToAccount = false,
}: {
  className?: string;
  saveToAccount?: boolean;
}) {
  const { t } = useTranslation(); // re-renders on a language change
  const active = currentLocale();

  function choose(lang: Locale) {
    if (lang !== active) chooseLanguage(lang, saveToAccount);
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
