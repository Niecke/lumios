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


def test_success_with_non_json_body_is_not_a_failure(app, brevo_key):
    resp = MagicMock(ok=True, status_code=202)
    resp.json.side_effect = ValueError("not json")
    with (
        patch.object(mail.requests, "post", return_value=resp),
        patch.object(mail, "sentry_sdk") as sentry,
    ):
        _send(app)  # must not raise, so the job is not retried

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

    def test_supported_language_is_passed_to_the_activation_job(self, pending_user):
        with patch("worker.send_activation_email_task") as task:
            mail.process_resend_activation("pending@test.com", "1.2.3.4", "en")

        task.configure.return_value.defer.assert_called_once_with(
            user_id=pending_user.id, lang="en"
        )

    def test_invalid_language_is_not_passed(self, pending_user):
        with patch("worker.send_activation_email_task") as task:
            mail.process_resend_activation("pending@test.com", "1.2.3.4", "fr")

        task.configure.return_value.defer.assert_called_once_with(user_id=pending_user.id)
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


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------

GOLDEN_REGISTRATION_DE = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'><style>\n"
    "  body { font-family: Arial, sans-serif; color: #222; background: #f9f9f9; margin: 0; padding: 0; }\n"
    "  .wrap { max-width: 560px; margin: 32px auto; background: #fff;\n"
    "          border-radius: 6px; padding: 32px 40px; }\n"
    "  h2 { color: #1a1a1a; margin-top: 0; }\n"
    "  p  { line-height: 1.6; }\n"
    "  .foot { margin-top: 32px; font-size: 12px; color: #888; border-top: 1px solid #eee;\n"
    "          padding-top: 12px; }\n"
    "</style></head><body><div class='wrap'>\n"
    "        <h2>Willkommen bei Lumios!</h2>\n"
    "        <p>Ihr Konto wurde erfolgreich eingerichtet.<br>\n"
    "           Sie können sich jetzt mit <strong>a@test.com</strong> anmelden.</p>\n"
    "        <a href=\"{url}/login\" style=\"{style}\">Zur Anmeldung</a>\n"
    "        <p>Falls Sie diese E-Mail nicht erwartet haben, können Sie sie ignorieren.</p>\n"
    "    <p class='foot'>Lumios · lumios.niecke-it.de</p></div></body></html>"
)

# (sender, args, {lang: (subject marker, body marker)})
_MAILS = {
    "registration": (
        lambda lang: mail.send_registration_email("a@test.com", lang),
        {"de": "Willkommen bei Lumios", "en": "Welcome to Lumios"},
        {"de": "Zur Anmeldung", "en": "Sign in"},
    ),
    "cancellation": (
        lambda lang: mail.send_account_cancellation_email("a@test.com", lang),
        {"de": "Ihr Lumios-Konto wurde deaktiviert", "en": "Your Lumios account has been deactivated"},
        {"de": "Datenschutzerklärung", "en": "privacy policy"},
    ),
    "agb": (
        lambda lang: mail.send_agb_change_email("a@test.com", "2.0", "Summary", None, lang),
        {"de": "AGB-Änderung: 2.0", "en": "Terms of Service update: 2.0"},
        {"de": "AGB lesen", "en": "Read the Terms"},
    ),
    "gallery": (
        lambda lang: mail.send_gallery_finished_email("a@test.com", "Lib", "uu", 3, lang),
        {"de": "Galerie abgeschlossen: Lib (3 Fotos ausgewählt)", "en": "Library completed: Lib (3 photos selected)"},
        {"de": "Galerie öffnen", "en": "Open library"},
    ),
}


def _captured(call):
    with patch.object(mail, "_send") as send:
        call()
    send.assert_called_once()
    return send.call_args.args


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("name", list(_MAILS))
def test_mail_renders_in_the_language(name, lang):
    sender, subjects, bodies = _MAILS[name]
    to, subject, html = _captured(lambda: sender(lang))
    assert to == "a@test.com"
    assert subjects[lang] in subject
    assert bodies[lang] in html
    for other in {"de", "en"} - {lang}:
        assert bodies[other] not in html
    assert "{" not in html.split("</style>")[1]


@pytest.mark.parametrize("name", list(_MAILS))
@pytest.mark.parametrize("lang", ["fr", "", None, 1])
def test_unknown_language_renders_german(name, lang):
    sender, subjects, _ = _MAILS[name]
    _to, subject, _html = _captured(lambda: sender(lang))
    assert subjects["de"] in subject


def test_german_registration_is_unchanged():
    _to, subject, html = _captured(lambda: mail.send_registration_email("a@test.com"))
    assert subject == "Willkommen bei Lumios – Ihr Konto ist bereit"
    expected = GOLDEN_REGISTRATION_DE.replace("{url}", mail.FRONTEND_URL).replace(
        "{style}", mail._BTN_STYLE
    )
    assert html == expected


class TestAgbDate:
    def test_date_is_localised(self):
        for lang, expected in (("de", "1. Dezember 2026"), ("en", "December 1, 2026")):
            _to, _s, html = _captured(
                lambda: mail.send_agb_change_email("a@test.com", "2.0", "S", "2026-12-01", lang)
            )
            assert expected in html

    @pytest.mark.parametrize("value", [None, "", "not-a-date", "2026-13-40"])
    def test_no_or_bad_date_leaves_out_the_sentence(self, value):
        _to, _s, html = _captured(
            lambda: mail.send_agb_change_email("a@test.com", "2.0", "S", value, "en")
        )
        assert "take effect on" not in html
        assert "Read the Terms" in html


class TestGalleryNumbers:
    def test_singular_and_plural(self):
        _t, subject, _h = _captured(
            lambda: mail.send_gallery_finished_email("a@test.com", "Lib", "u", 1, "en")
        )
        assert "(1 photo selected)" in subject
        _t, subject, _h = _captured(
            lambda: mail.send_gallery_finished_email("a@test.com", "Lib", "u", 1, "de")
        )
        assert "(1 Foto ausgewählt)" in subject

    def test_number_format_follows_the_language(self):
        _t, subject, _h = _captured(
            lambda: mail.send_gallery_finished_email("a@test.com", "Lib", "u", 1234, "de")
        )
        assert "1.234 Fotos" in subject
        _t, subject, _h = _captured(
            lambda: mail.send_gallery_finished_email("a@test.com", "Lib", "u", 1234, "en")
        )
        assert "1,234 photos" in subject


class TestActivationLanguage:
    def test_stored_language_wins_over_the_fallback(self, pending_user):
        pending_user.language = "en"
        db.session.commit()
        _to, subject, _h = _captured(lambda: mail.send_activation_email(pending_user.id, "de"))
        assert subject == "Lumios – activate your account"

    def test_fallback_is_used_without_a_stored_language(self, pending_user):
        _to, subject, html = _captured(lambda: mail.send_activation_email(pending_user.id, "en"))
        assert subject == "Lumios – activate your account"
        assert "Activate account" in html

    def test_german_without_any_language(self, pending_user):
        _to, subject, _h = _captured(lambda: mail.send_activation_email(pending_user.id))
        assert subject == "Lumios – Konto aktivieren"

    def test_unknown_fallback_is_german(self, pending_user):
        _to, subject, _h = _captured(lambda: mail.send_activation_email(pending_user.id, "fr"))
        assert subject == "Lumios – Konto aktivieren"
