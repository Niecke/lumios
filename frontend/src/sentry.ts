// sentry.ts — Sentry error tracking for the SPA.
//
// Off while config.SENTRY_DSN is empty (local dev, CI). Events are scrubbed in
// beforeSend: no tokens, cookies, email addresses or share-link UUIDs.

import * as Sentry from "@sentry/react";
import { config } from "./config.ts";

const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
const JWT_RE = /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*/g;
const UUID_RE = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g;

const SENSITIVE_HEADERS = new Set(["authorization", "cookie", "x-forwarded-for", "x-real-ip"]);
const PROD_ENVIRONMENT = "lumios";

export function scrubString(value: string): string {
  return value
    .replace(JWT_RE, "[REDACTED_JWT]")
    .replace(EMAIL_RE, "[REDACTED_EMAIL]")
    .replace(UUID_RE, "[REDACTED_UUID]");
}

function scrubValue(value: unknown): unknown {
  if (typeof value === "string") return scrubString(value);
  if (Array.isArray(value)) return value.map(scrubValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, scrubValue(v)]));
  }
  return value;
}

export function scrubEvent(event: Sentry.ErrorEvent): Sentry.ErrorEvent {
  if (event.user) {
    event.user = event.user.id ? { id: event.user.id } : undefined;
  }
  if (event.request) {
    const { headers, url, query_string } = event.request;
    if (headers) {
      event.request.headers = Object.fromEntries(
        Object.entries(headers).map(([k, v]) => [
          k,
          SENSITIVE_HEADERS.has(k.toLowerCase()) ? "[REDACTED]" : scrubString(v),
        ]),
      );
    }
    delete event.request.cookies;
    if (url) event.request.url = scrubString(url);
    if (typeof query_string === "string") event.request.query_string = scrubString(query_string);
  }
  if (event.message) event.message = scrubString(event.message);
  for (const exception of event.exception?.values ?? []) {
    if (exception.value) exception.value = scrubString(exception.value);
  }
  for (const crumb of event.breadcrumbs ?? []) {
    if (crumb.message) crumb.message = scrubString(crumb.message);
    if (crumb.data) crumb.data = scrubValue(crumb.data) as typeof crumb.data;
  }
  return event;
}

export function initSentry(): void {
  if (!config.SENTRY_DSN) return;
  Sentry.init({
    dsn: config.SENTRY_DSN,
    environment: config.SENTRY_ENVIRONMENT || undefined,
    release: config.APP_VERSION ? `lumios-frontend@${config.APP_VERSION}` : undefined,
    sendDefaultPii: false,
    tracesSampleRate: 0.0,
    beforeSend: scrubEvent,
  });

  // Test hook for verifying the setup from the browser console. Never exposed
  // in production, where the environment is the prod namespace.
  if (config.SENTRY_ENVIRONMENT && config.SENTRY_ENVIRONMENT !== PROD_ENVIRONMENT) {
    (window as unknown as Record<string, unknown>).sendSentryTestEvent = () =>
      Sentry.captureException(new Error("Deliberate frontend test error for Sentry verification"));
  }
}
