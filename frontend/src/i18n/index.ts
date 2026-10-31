// i18n/index.ts — i18next setup: German is the default, English is available.
//
// The language is never taken from navigator.language: a first visit is always
// German. A choice made with setLocale() is kept in localStorage (visitors) and
// by LanguageSwitcher also on the user account (logged-in photographers).
// Relative imports carry a .ts extension so node --test can load this module.

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import de from "./locales/de.json" with { type: "json" };
import en from "./locales/en.json" with { type: "json" };

export const SUPPORTED_LOCALES = ["de", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
const DEFAULT_LOCALE: Locale = "de";
const LOCALE_STORAGE_KEY = "lumios_locale";

function isLocale(value: unknown): value is Locale {
  return SUPPORTED_LOCALES.includes(value as Locale);
}

// Stored choice, or German. localStorage may be missing (node tests, blocked storage).
export function detectLocale(): Locale {
  try {
    const stored = globalThis.localStorage?.getItem(LOCALE_STORAGE_KEY);
    if (isLocale(stored)) return stored;
  } catch {
    // storage blocked: fall through to the default
  }
  return DEFAULT_LOCALE;
}

const isDev = Boolean((import.meta as { env?: { DEV?: boolean } }).env?.DEV);

function applyDocumentLang(lang: Locale) {
  if (typeof document !== "undefined") document.documentElement.lang = lang;
}

// Dev only: prefix texts that came from the English fallback while German is active.
const markFallback = {
  type: "postProcessor" as const,
  name: "markFallback",
  process(value: string, key: string | string[], options: Record<string, unknown>) {
    const k = Array.isArray(key) ? key[0] : key;
    const lng = (options?.lng as string | undefined) ?? i18n.language;
    if (lng === "de" && !i18n.exists(k, { ...options, lng: "de", fallbackLng: false })) {
      return `[EN] ${value}`;
    }
    return value;
  },
};

// In development a key missing in German resolves to the English text with an
// "[EN] " prefix, so a missing translation is visible at a glance.
i18n.use(markFallback).use(initReactI18next).init({
  lng: detectLocale(),
  fallbackLng: "en",
  resources: { de: { translation: de }, en: { translation: en } },
  interpolation: { escapeValue: false },
  returnNull: false,
  saveMissing: isDev,
  missingKeyHandler: isDev
    ? (_lngs, _ns, key) => console.warn(`[i18n] missing translation: ${key}`)
    : undefined,
  postProcess: isDev ? ["markFallback"] : false,
});

applyDocumentLang(detectLocale());

// Switch the UI language and remember it in the browser.
export function setLocale(lang: Locale) {
  void i18n.changeLanguage(lang);
  try {
    globalThis.localStorage?.setItem(LOCALE_STORAGE_KEY, lang);
  } catch {
    // storage blocked: the choice only lasts for this page view
  }
  applyDocumentLang(lang);
}

// The account's language wins over the browser's: called with the value from /auth/me.
export function applyAccountLocale(lang: unknown) {
  if (isLocale(lang) && lang !== i18n.language) setLocale(lang);
}

export function currentLocale(): Locale {
  return isLocale(i18n.language) ? i18n.language : DEFAULT_LOCALE;
}

// ---- formatting for the active locale ----

export function formatDate(iso: string, lang: string = i18n.language): string {
  return new Date(iso).toLocaleDateString(lang, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatDateTime(iso: string, lang: string = i18n.language): string {
  return new Date(iso).toLocaleString(lang, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatBytes(bytes: number, lang: string = i18n.language): string {
  const nf = (n: number, digits: number) =>
    new Intl.NumberFormat(lang, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(n);
  if (bytes < 1024) return `${nf(bytes, 0)} B`;
  if (bytes < 1024 * 1024) return `${nf(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${nf(bytes / (1024 * 1024), 1)} MB`;
  return `${nf(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

// "just now", "5m ago" in the active language.
export function formatTimeAgo(iso: string, now: number = Date.now()): string {
  const mins = Math.floor((now - new Date(iso).getTime()) / 60000);
  if (mins < 1) return i18n.t("time.justNow");
  if (mins < 60) return i18n.t("time.minutesAgo", { count: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return i18n.t("time.hoursAgo", { count: hours });
  return i18n.t("time.daysAgo", { count: Math.floor(hours / 24) });
}

export default i18n;
