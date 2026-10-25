// Runtime configuration, written to /config.js by the container at startup.
// The VITE_* variables remain as an optional override for `npm run dev`.
interface AppConfig {
  GOOGLE_CLIENT_ID: string;
  LANDING_URL: string;
  APP_URL: string;
}

declare global {
  interface Window {
    __CONFIG__?: Partial<AppConfig>;
  }
}

const runtime = window.__CONFIG__ ?? {};

export const config: AppConfig = {
  GOOGLE_CLIENT_ID:
    runtime.GOOGLE_CLIENT_ID || (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) || "",
  LANDING_URL:
    runtime.LANDING_URL || (import.meta.env.VITE_LANDING_URL as string | undefined) || "",
  APP_URL: runtime.APP_URL || (import.meta.env.VITE_APP_URL as string | undefined) || "",
};
