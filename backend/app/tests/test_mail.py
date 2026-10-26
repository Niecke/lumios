"""Delivery, failure reporting and enqueueing of services.mail."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from datetime import datetime, timezone

from sqlalchemy import select

import worker
from models import AuditLog, AuditLogType, User, db
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
        with pytest.raises(mail.PermanentMailError):
            _send(app)

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
        with pytest.raises(mail.MailDeliveryError):
            _send(app)

    sentry.capture_exception.assert_called_once_with(exc)


def test_sentry_payload_has_no_recipient(app, brevo_key):
    resp = MagicMock(ok=False, status_code=500, text="oops")
    with (
        patch.object(mail.requests, "post", return_value=resp),
        patch.object(mail, "sentry_sdk") as sentry,
    ):
        with pytest.raises(mail.MailDeliveryError):
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


@pytest.mark.parametrize(
    "status, permanent",
    [(400, True), (401, True), (404, True), (429, False), (500, False), (503, False)],
)
def test_only_permanent_errors_are_not_retried(app, brevo_key, status, permanent):
    resp = MagicMock(ok=False, status_code=status, text="x")
    with (
        patch.object(mail.requests, "post", return_value=resp),
        patch.object(mail, "sentry_sdk"),
    ):
        with pytest.raises(mail.MailDeliveryError) as info:
            _send(app)

    assert isinstance(info.value, mail.PermanentMailError) is permanent
    job = type("J", (), {"attempts": 0})()
    decision = worker.MAIL_RETRY.get_retry_decision(exception=info.value, job=job)
    assert (decision is None) is permanent


def test_timeout_is_retried(app, brevo_key):
    with (
        patch.object(mail.requests, "post", side_effect=requests.Timeout("slow")),
        patch.object(mail, "sentry_sdk"),
    ):
        with pytest.raises(mail.MailDeliveryError) as info:
            _send(app)

    job = type("J", (), {"attempts": 0})()
    assert worker.MAIL_RETRY.get_retry_decision(exception=info.value, job=job)


def test_send_skips_when_api_key_unset(app):
    with (
        patch.object(mail, "BREVO_API_KEY", ""),
        patch.object(mail.requests, "post") as post,
    ):
        _send(app)  # must not raise

    post.assert_not_called()


@pytest.fixture
def pending_user(app):
    user = User(
        email="pending@test.com",
        active=False,
        activation_pending=True,
        activation_token="secret-token",
        activation_token_created_at=datetime.now(timezone.utc),
    )
    db.session.add(user)
    db.session.commit()
    return user


class TestSendActivationEmail:
    def test_builds_link_from_the_stored_token(self, pending_user):
        with patch.object(mail, "_send") as send:
            mail.send_activation_email(pending_user.id)

        send.assert_called_once()
        to, _subject, html = send.call_args.args
        assert to == "pending@test.com"
        assert f"{mail.FRONTEND_URL}/activate?token=secret-token" in html

    def test_noop_for_active_deleted_or_tokenless_account(self, pending_user):
        with patch.object(mail, "_send") as send:
            mail.send_activation_email(999999)
            pending_user.activation_token = None
            db.session.commit()
            mail.send_activation_email(pending_user.id)
            pending_user.activation_token = "t"
            pending_user.activation_pending = False
            pending_user.active = True
            db.session.commit()
            mail.send_activation_email(pending_user.id)
            pending_user.activation_pending = True
            pending_user.deleted_at = datetime.now(timezone.utc)
            db.session.commit()
            mail.send_activation_email(pending_user.id)

        send.assert_not_called()


class TestProcessResendActivation:
    def test_pending_user_gets_new_token_audit_entry_and_job(self, pending_user):
        with patch("worker.send_activation_email_task") as task:
            mail.process_resend_activation("pending@test.com", "1.2.3.4")

        user = db.session.get(User, pending_user.id)
        assert user.activation_token not in (None, "secret-token")
        task.configure.return_value.defer.assert_called_once_with(user_id=user.id)
        (entry,) = db.session.execute(
            select(AuditLog).where(
                AuditLog.audit_type == AuditLogType.activation_token_resent
            )
        ).scalars()
        assert entry.ip_address == "1.2.3.4"

    def test_unknown_active_and_deleted_addresses_do_nothing(
        self, pending_user, regular_user
    ):
        with patch("worker.send_activation_email_task") as task:
            mail.process_resend_activation("nobody@test.com", "1.2.3.4")
            mail.process_resend_activation(regular_user.email.lower(), "1.2.3.4")
            pending_user.deleted_at = datetime.now(timezone.utc)
            db.session.commit()
            mail.process_resend_activation("pending@test.com", "1.2.3.4")

        task.configure.assert_not_called()
        assert db.session.execute(select(AuditLog)).first() is None


class TestEnqueueFailure:
    def test_failed_defer_is_reported_not_raised(self, app):
        with (
            app.app_context(),
            patch.object(
                worker.send_registration_email_task,
                "configure",
                side_effect=RuntimeError("db down"),
            ),
            patch.object(mail, "sentry_sdk") as sentry,
        ):
            assert mail.notify_registration("a@test.com") is False

        sentry.capture_exception.assert_called_once()
