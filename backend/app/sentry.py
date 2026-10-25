"""Sentry error tracking: initialisation and the privacy scrubber.

Disabled while SENTRY_DSN is empty (local dev, CI). Every event passes through
scrub_event() before it leaves the process.
"""

import re

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from config import (
    SENTRY_DSN,
    SENTRY_ENVIRONMENT,
    SENTRY_RELEASE,
    SENTRY_TRACES_SAMPLE_RATE,
)

REDACTED = "[REDACTED]"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_QUERY_SECRET_RE = re.compile(r"([?&](?:token|code)=)[^&#\s]*")

_SENSITIVE_HEADERS = {"authorization", "cookie", "x-forwarded-for", "x-real-ip"}


def scrub_string(value: str) -> str:
    """Redact JWTs, emails, UUIDs (share links) and token/code query values."""
    value = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", value)
    value = _JWT_RE.sub("[REDACTED_JWT]", value)
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    return _UUID_RE.sub("[REDACTED_UUID]", value)


def _scrub_value(value):
    if isinstance(value, str):
        return scrub_string(value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v) for v in value]
    return value


def _scrub_headers(headers):
    if isinstance(headers, dict):
        return {
            k: REDACTED if k.lower() in _SENSITIVE_HEADERS else _scrub_value(v)
            for k, v in headers.items()
        }
    if isinstance(headers, list):
        return [
            [h[0], REDACTED if str(h[0]).lower() in _SENSITIVE_HEADERS else _scrub_value(h[1])]
            for h in headers
        ]
    return headers


def scrub_event(event, hint=None):
    """before_send hook: strip personal data from an event, never drop it."""
    user = event.get("user")
    if user:
        for key in ("ip_address", "email", "username"):
            user.pop(key, None)

    request = event.get("request")
    if request:
        if "headers" in request:
            request["headers"] = _scrub_headers(request["headers"])
        if "cookies" in request:
            request["cookies"] = REDACTED
        # Bodies can carry passwords or image/file payloads: never send them.
        if "data" in request:
            request["data"] = REDACTED
        for key in ("url", "query_string"):
            if isinstance(request.get(key), str):
                request[key] = scrub_string(request[key])
        if "env" in request:
            request["env"] = {
                k: v for k, v in request["env"].items() if k not in ("REMOTE_ADDR",)
            }

    for key in ("contexts", "extra", "tags"):
        if event.get(key):
            event[key] = _scrub_value(event[key])

    for key in ("message", "transaction"):
        if isinstance(event.get(key), str):
            event[key] = scrub_string(event[key])
    logentry = event.get("logentry")
    if logentry:
        if isinstance(logentry.get("message"), str):
            logentry["message"] = scrub_string(logentry["message"])
        if isinstance(logentry.get("params"), (list, tuple, dict)):
            logentry["params"] = _scrub_value(logentry["params"])

    for exc in (event.get("exception") or {}).get("values") or []:
        if isinstance(exc.get("value"), str):
            exc["value"] = scrub_string(exc["value"])

    for crumb in (event.get("breadcrumbs") or {}).get("values") or []:
        if isinstance(crumb.get("message"), str):
            crumb["message"] = scrub_string(crumb["message"])
        if "data" in crumb:
            crumb["data"] = _scrub_value(crumb["data"])

    return event


def init_sentry(app) -> None:
    if not SENTRY_DSN:
        app.logger.info("Sentry: disabled", extra={"log_type": "startup"})
        return
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT or None,
        release=SENTRY_RELEASE,
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        # Frame locals carry recipients, tokens and form input.
        include_local_variables=False,
        before_send=scrub_event,
        before_send_transaction=scrub_event,
        # Failures are reported explicitly (mail, jobs). Logged errors stay
        # breadcrumbs, otherwise every logger.exception() is reported twice.
        integrations=[LoggingIntegration(event_level=None)],
    )
    app.logger.info(
        f"Sentry: enabled ({SENTRY_ENVIRONMENT or 'no environment'})",
        extra={"log_type": "startup"},
    )
