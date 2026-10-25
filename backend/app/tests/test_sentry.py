"""Sentry initialisation and the privacy scrubber."""

from unittest.mock import patch

import sentry_sdk

import sentry
from sentry import scrub_event, scrub_string

UUID = "123e4567-e89b-12d3-a456-426614174000"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"


def test_sentry_disabled_by_default(app):
    assert not sentry.SENTRY_DSN
    assert not sentry_sdk.get_client().is_active()
    with patch("sentry_sdk.init") as init:
        sentry.init_sentry(app)
    init.assert_not_called()


def test_init_with_dsn_disables_pii_and_scrubs():
    with (
        patch.object(sentry, "SENTRY_DSN", "https://key@o1.ingest.de.sentry.io/1"),
        patch("sentry_sdk.init") as init,
    ):
        from flask import Flask

        sentry.init_sentry(Flask("t"))
    kwargs = init.call_args.kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["before_send"] is scrub_event


def test_scrubber_headers_and_cookies():
    event = {
        "request": {
            "headers": {
                "Authorization": f"Bearer {JWT}",
                "Cookie": "session=abc",
                "X-Forwarded-For": "203.0.113.7",
                "X-Real-IP": "203.0.113.7",
                "User-Agent": "pytest",
            },
            "cookies": {"session": "abc"},
        }
    }
    out = scrub_event(event)["request"]
    for name in ("Authorization", "Cookie", "X-Forwarded-For", "X-Real-IP"):
        assert out["headers"][name] == "[REDACTED]"
    assert out["headers"]["User-Agent"] == "pytest"
    assert out["cookies"] == "[REDACTED]"


def test_scrubber_emails_jwts_and_uuids():
    event = {
        "request": {
            "url": f"https://x.test/api/v1/public/libraries/{UUID}",
            "query_string": "email=a.b@example.com",
        },
        "logentry": {"message": f"user a.b@example.com token {JWT}"},
        "exception": {"values": [{"value": f"library {UUID} for a.b@example.com"}]},
        "breadcrumbs": {"values": [{"message": f"GET /libraries/{UUID}"}]},
    }
    out = scrub_event(event)
    assert out["request"]["url"].endswith("/[REDACTED_UUID]")
    assert out["request"]["query_string"] == "email=[REDACTED_EMAIL]"
    assert out["logentry"]["message"] == "user [REDACTED_EMAIL] token [REDACTED_JWT]"
    assert out["exception"]["values"][0]["value"] == (
        "library [REDACTED_UUID] for [REDACTED_EMAIL]"
    )
    assert out["breadcrumbs"]["values"][0]["message"] == "GET /libraries/[REDACTED_UUID]"


def test_scrub_string_leaves_plain_text():
    assert scrub_string("nothing to see") == "nothing to see"


def test_scrubber_user_data():
    event = {"user": {"id": "7", "email": "a@b.at", "ip_address": "1.2.3.4", "username": "x"}}
    assert scrub_event(event)["user"] == {"id": "7"}


def test_scrubber_request_body():
    event = {"request": {"data": {"password": "hunter2", "file": b"\xff\xd8\xff"}}}
    assert scrub_event(event)["request"]["data"] == "[REDACTED]"


def test_system_check_reports_sentry_status():
    from services import system

    with patch.object(system, "SENTRY_DSN", ""):
        assert system._check_sentry()["status"] == "not_configured"
    with patch.object(system, "SENTRY_DSN", "https://key@o1.ingest.de.sentry.io/1"):
        assert system._check_sentry()["status"] == "ok"
