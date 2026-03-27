// errorReporting.ts — captures unhandled JS errors and forwards them to the
// backend, which logs them in Cloud Error Reporting format.
//
// Two global hooks are installed:
//   window.onerror          — synchronous errors and cross-origin script errors
//   unhandledrejection      — unhandled Promise rejections
//
// Call initErrorReporting() once at app startup (main.tsx), before any other
// code runs, so errors during initialisation are also captured.

const ENDPOINT = "/api/v1/public/client-errors";

function send(payload: {
  message: string;
  stack: string;
  url: string;
  line_number: number;
  col_number: number;
}): void {
  try {
    // keepalive: true lets the request complete even if the page unloads
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {
      // silently discard network failures — never throw from the error reporter
    });
  } catch {
    // never throw from the error reporter
  }
}

export function initErrorReporting(): void {
  window.onerror = (event, source, lineno, colno, error) => {
    send({
      message: error?.message ?? String(event),
      stack: error?.stack ?? "",
      url: source ?? window.location.href,
      line_number: lineno ?? 0,
      col_number: colno ?? 0,
    });
    return false; // preserve default browser error handling
  };

  window.addEventListener("unhandledrejection", (event) => {
    const error = event.reason instanceof Error ? event.reason : null;
    send({
      message: error?.message ?? String(event.reason),
      stack: error?.stack ?? "",
      url: window.location.href,
      line_number: 0,
      col_number: 0,
    });
  });
}
