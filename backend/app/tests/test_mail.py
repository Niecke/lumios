"""Failure reporting of services.mail._send to Sentry."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from services import mail

RECIPIENT = "secret.recipient@example.com"


@pytest.fixture
def brevo_key():
    with patch.object(mail, "BREVO_API_KEY", "test-key"):
        yield


def _send(app):
    with app.app_context():
        mail._send(RECIPIENT, "Subject", "<p>hi</p>")


def test_brevo_error_captured_to_sentry(app, brevo_key):
    resp = MagicMock(ok=False, status_code=400, text="bad request")
    with (
        patch.object(mail.requests, "post", return_value=resp),
        patch.object(mail, "sentry_sdk") as sentry,
    ):
        _send(app)  # must not raise

    sentry.capture_message.assert_called_once()
    args, kwargs = sentry.capture_message.call_args
    assert "400" in args[0]
    assert kwargs["level"] == "error"
    sentry.new_scope.return_value.__enter__.return_value.set_tag.assert_called_with(
        "brevo_status", 400
    )


def test_exception_captured_to_sentry(app, brevo_key):
    exc = requests.ConnectionError("network down")
    with (
        patch.object(mail.requests, "post", side_effect=exc),
        patch.object(mail, "sentry_sdk") as sentry,
    ):
        _send(app)  # must not raise

    sentry.capture_exception.assert_called_once_with(exc)


def test_sentry_payload_has_no_recipient(app, brevo_key):
    resp = MagicMock(ok=False, status_code=500, text="oops")
    with (
        patch.object(mail.requests, "post", return_value=resp),
        patch.object(mail, "sentry_sdk") as sentry,
    ):
        _send(app)

    scope = sentry.new_scope.return_value.__enter__.return_value
    payload = repr(sentry.capture_message.call_args) + repr(scope.mock_calls)
    assert RECIPIENT not in payload


def test_success_reports_nothing(app, brevo_key):
    resp = MagicMock(ok=True, status_code=201)
    resp.json.return_value = {"messageId": "x"}
    with (
        patch.object(mail.requests, "post", return_value=resp),
        patch.object(mail, "sentry_sdk") as sentry,
    ):
        _send(app)

    sentry.capture_message.assert_not_called()
    sentry.capture_exception.assert_not_called()
