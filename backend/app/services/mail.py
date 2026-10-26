# mail.py — transactional email service (Brevo)
#
# Mails are sent by the ``default`` worker (worker.py): the ``notify_*``
# functions only enqueue a job, the ``send_*`` functions build and send the mail
# inside the job. A failed delivery raises so the job is retried; after the last
# run it stays ``failed`` and shows on the admin Workers page.
# When BREVO_API_KEY is not set the call is logged and skipped — safe for
# local development without email credentials.

import hashlib
import secrets
from datetime import datetime, timezone

import requests
import sentry_sdk
from flask import current_app
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import func, select
from config import (
    ADMIN_EMAIL,
    BREVO_API_KEY,
    FRONTEND_URL,
    MAIL_SENDER_EMAIL,
    MAIL_SENDER_NAME,
)

_BREVO_CONTACTS_URL = "https://api.brevo.com/v3/contacts"

_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class MailDeliveryError(Exception):
    """A mail could not be delivered; the job is retried."""


class PermanentMailError(MailDeliveryError):
    """Brevo rejected the mail (4xx other than 429); retrying cannot help."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_BASE_STYLE = """
  body { font-family: Arial, sans-serif; color: #222; background: #f9f9f9; margin: 0; padding: 0; }
  .wrap { max-width: 560px; margin: 32px auto; background: #fff;
          border-radius: 6px; padding: 32px 40px; }
  h2 { color: #1a1a1a; margin-top: 0; }
  p  { line-height: 1.6; }
  .foot { margin-top: 32px; font-size: 12px; color: #888; border-top: 1px solid #eee;
          padding-top: 12px; }
"""

_BTN_STYLE = (
    "display:inline-block;margin-top:16px;padding:10px 20px;"
    "background:#2563eb;color:#ffffff;text-decoration:none;"
    "border-radius:4px;font-weight:bold;font-family:Arial,sans-serif;"
)


def _btn(href: str, label: str) -> str:
    """Render a CTA button with fully inline styles (survives email client CSS stripping)."""
    return f'<a href="{href}" style="{_BTN_STYLE}">{label}</a>'


def _html(body: str) -> str:
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_BASE_STYLE}</style></head>"
        f"<body><div class='wrap'>{body}"
        f"<p class='foot'>Lumios · lumios.niecke-it.de</p></div></body></html>"
    )


def _send(to_email: str, subject: str, html: str) -> None:
    """POST a single transactional email to Brevo.

    Raises MailDeliveryError when Brevo is configured and the delivery fails.
    """
    if not BREVO_API_KEY:
        current_app.logger.warning(
            "MAIL skipped (BREVO_API_KEY not set): to=%s subject=%r",
            to_email,
            subject,
            extra={"log_type": "mail"},
        )
        return
    try:
        resp = requests.post(
            _BREVO_URL,
            json={
                "sender": {"name": MAIL_SENDER_NAME, "email": MAIL_SENDER_EMAIL},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html,
            },
            headers={"api-key": BREVO_API_KEY, "content-type": "application/json"},
            timeout=10,
        )
    except Exception as exc:
        current_app.logger.exception(
            "MAIL delivery failed: to=%s subject=%r",
            to_email,
            subject,
            extra={"log_type": "mail"},
        )
        sentry_sdk.capture_exception(exc)
        raise MailDeliveryError(f"Brevo request failed: {type(exc).__name__}") from exc

    if resp.ok:
        current_app.logger.info(
            "MAIL sent: to=%s subject=%r messageId=%s",
            to_email,
            subject,
            resp.json().get("messageId", ""),
            extra={"log_type": "mail"},
        )
        return

    current_app.logger.error(
        "MAIL Brevo error: status=%d body=%r to=%s subject=%r",
        resp.status_code,
        resp.text[:300],
        to_email,
        subject,
        extra={"log_type": "mail"},
    )
    # No recipient in the event: only the status code.
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("brevo_status", resp.status_code)
        sentry_sdk.capture_message(
            f"Brevo email delivery failed with status {resp.status_code}",
            level="error",
        )
    # 4xx (except 429) means the mail itself is refused: do not retry it.
    error = (
        PermanentMailError
        if 400 <= resp.status_code < 500 and resp.status_code != 429
        else MailDeliveryError
    )
    raise error(f"Brevo answered with status {resp.status_code}")


def _enqueue(task, lock: str | None = None, **kwargs) -> bool:
    """Defer a mail job; never raises, the caller has usually committed already.

    Returns False when no job was queued because of an error. A duplicate
    (same ``lock`` still waiting in the queue) counts as queued.
    """
    # Imported here: worker.py imports this module for the job bodies.
    from worker import open_for_defer

    try:
        open_for_defer()
        task.configure(queueing_lock=lock).defer(**kwargs)
    except AlreadyEnqueued:
        pass
    except Exception as exc:
        current_app.logger.exception(
            "MAIL could not be queued: task=%s", task.name, extra={"log_type": "mail"}
        )
        sentry_sdk.capture_exception(exc)
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def send_registration_email(user_email: str) -> None:
    """Send a registration confirmation email to a newly created account."""
    html = _html(
        f"""
        <h2>Willkommen bei Lumios!</h2>
        <p>Ihr Konto wurde erfolgreich eingerichtet.<br>
           Sie können sich jetzt mit <strong>{user_email}</strong> anmelden.</p>
        {_btn(f"{FRONTEND_URL}/login", "Zur Anmeldung")}
        <p>Falls Sie diese E-Mail nicht erwartet haben, können Sie sie ignorieren.</p>
    """
    )
    _send(user_email, "Willkommen bei Lumios – Ihr Konto ist bereit", html)


def send_gallery_finished_email(
    photographer_email: str,
    library_name: str,
    library_uuid: str,
    liked_count: int,
) -> None:
    """Notify the photographer that a customer has finished reviewing their gallery."""
    plural = "Foto" if liked_count == 1 else "Fotos"
    gallery_url = f"{FRONTEND_URL}/libraries/{library_uuid}"
    html = _html(
        f"""
        <h2>Galerie abgeschlossen</h2>
        <p>Ihr Kunde hat die Galerie <strong>{library_name}</strong> abgeschlossen
           und <strong>{liked_count} {plural}</strong> ausgewählt.</p>
        {_btn(gallery_url, "Galerie öffnen")}
    """
    )
    _send(
        photographer_email,
        f"Galerie abgeschlossen: {library_name} ({liked_count} {plural} ausgewählt)",
        html,
    )


def send_account_cancellation_email(user_email: str) -> None:
    """Confirm to the user that their account has been deactivated."""
    html = _html(
        f"""
        <h2>Ihr Lumios-Konto wurde deaktiviert</h2>
        <p>Wir bestätigen, dass Ihr Konto (<strong>{user_email}</strong>)
           auf Ihren Wunsch hin deaktiviert wurde.</p>
        <p>Ihre Daten werden gemäß unserer Datenschutzerklärung behandelt.
           Bei Fragen wenden Sie sich bitte an unseren Support.</p>
    """
    )
    _send(user_email, "Ihr Lumios-Konto wurde deaktiviert", html)


def send_agb_change_email(user_email: str, agb_version: str, summary: str) -> None:
    """Notify a single user of an AGB or Datenschutz update (call per recipient).

    Callers are responsible for iterating over all affected users.
    AGB §13 requires this notification.
    """
    html = _html(
        f"""
        <h2>Aktualisierung unserer Allgemeinen Geschäftsbedingungen</h2>
        <p>Wir haben unsere AGB und/oder Datenschutzerklärung aktualisiert
           (<strong>{agb_version}</strong>).</p>
        <p><strong>Zusammenfassung der Änderungen:</strong><br>
           {summary}</p>
        <p>Die vollständigen Bedingungen finden Sie auf unserer Website:</p>
        {_btn(f"{FRONTEND_URL}/agb", "AGB lesen")}
        <p>Gemäß §13 unserer AGB sind Sie mit der weiteren Nutzung von Lumios
           nach Inkrafttreten der neuen Bedingungen einverstanden.</p>
    """
    )
    _send(user_email, f"Lumios AGB-Änderung: {agb_version}", html)


def send_activation_email(user_id: int) -> None:
    """Mail the one-time activation link of a pending account.

    The job only carries the user id, so the token never lands in the job
    table. A no-op once the account is active or deleted, so a re-run after a
    partial failure cannot send a second mail for a used link.
    """
    from models import User, db

    user = db.session.get(User, user_id)
    if (
        user is None
        or user.deleted_at is not None
        or not user.activation_pending
        or not user.activation_token
    ):
        return
    activation_link = f"{FRONTEND_URL}/activate?token={user.activation_token}"
    html = _html(
        f"""
        <h2>Willkommen bei Lumios!</h2>
        <p>Vielen Dank für Ihre Registrierung. Bitte aktivieren Sie Ihr Konto
           (<strong>{user.email}</strong>) durch Klick auf den folgenden Link.</p>
        {_btn(activation_link, "Konto aktivieren")}
        <p>Der Link ist 72 Stunden gültig. Falls Sie sich nicht registriert haben,
           können Sie diese E-Mail ignorieren.</p>
    """
    )
    _send(user.email, "Lumios – Konto aktivieren", html)


def process_resend_activation(email: str, ip: str) -> None:
    """Issue a fresh token and queue the mail, but only for a pending account.

    Runs in the worker, so the request takes the same time for pending, active
    and unknown addresses.
    """
    from models import AuditLog, AuditLogType, User, db

    user = db.session.execute(
        select(User).where(func.lower(User.email) == email, User.deleted_at.is_(None))
    ).scalar_one_or_none()
    if not user or not user.activation_pending or user.is_system:
        return

    user.activation_token = secrets.token_urlsafe(32)
    user.activation_token_created_at = datetime.now(timezone.utc)
    db.session.add(
        AuditLog(
            audit_type=AuditLogType.activation_token_resent,
            ip_address=ip,
            related_object_type="user",
            related_object_id=str(user.id),
        )
    )
    db.session.commit()

    # Not notify_activation_email: a failure to queue must fail this job so it is retried.
    from worker import open_for_defer, send_activation_email_task

    open_for_defer()
    send_activation_email_task.configure().defer(user_id=user.id)
    current_app.logger.info(
        "Activation email resent: %s", user.email, extra={"log_type": "audit"}
    )


def add_to_brevo_waitlist(email: str, list_id: int) -> bool:
    """Add an email address to a Brevo contact list (waitlist).

    Returns True on success, False on any error. Never raises.
    """
    if not BREVO_API_KEY:
        current_app.logger.warning(
            "WAITLIST skipped (BREVO_API_KEY not set): email=%s",
            email,
            extra={"log_type": "mail"},
        )
        return False
    if not list_id:
        current_app.logger.warning(
            "WAITLIST skipped (BREVO_WAITLIST_LIST_ID not set): email=%s",
            email,
            extra={"log_type": "mail"},
        )
        return False
    try:
        resp = requests.post(
            _BREVO_CONTACTS_URL,
            json={"email": email, "listIds": [list_id], "updateEnabled": True},
            headers={"api-key": BREVO_API_KEY, "content-type": "application/json"},
            timeout=10,
        )
        if resp.ok or resp.status_code == 400 and "already" in resp.text.lower():
            current_app.logger.info(
                "WAITLIST added: email=%s list=%d",
                email,
                list_id,
                extra={"log_type": "mail"},
            )
            return True
        current_app.logger.error(
            "WAITLIST Brevo error: status=%d body=%r email=%s",
            resp.status_code,
            resp.text[:300],
            email,
            extra={"log_type": "mail"},
        )
        return False
    except Exception:
        current_app.logger.exception(
            "WAITLIST request failed: email=%s", email, extra={"log_type": "mail"}
        )
        return False


def send_admin_new_account_email(user_email: str, account_type: str) -> None:
    """Notify the admin that a new account has been registered."""
    if not ADMIN_EMAIL:
        current_app.logger.warning(
            "MAIL skipped (ADMIN_EMAIL not set): new account %s",
            user_email,
            extra={"log_type": "mail"},
        )
        return
    html = _html(
        f"""
        <h2>Neues Konto registriert</h2>
        <p>Ein neues Konto wurde registriert:</p>
        <p><strong>E-Mail:</strong> {user_email}<br>
           <strong>Anmeldemethode:</strong> {account_type}</p>
        <p>Das Konto wartet auf Aktivierung.</p>
    """
    )
    _send(ADMIN_EMAIL, "Lumios – Neues Konto registriert", html)


def send_new_support_ticket_email(ticket_id: int, subject: str, user_email: str) -> None:
    """Notify the admin that a new support ticket has been submitted."""
    if not ADMIN_EMAIL:
        current_app.logger.warning(
            "MAIL skipped (ADMIN_EMAIL not set): support ticket #%d",
            ticket_id,
            extra={"log_type": "mail"},
        )
        return
    admin_url = f"/admin/support/{ticket_id}"
    html = _html(
        f"""
        <h2>[Lumios Support] Neues Ticket #{ticket_id}</h2>
        <p><strong>Von:</strong> {user_email}<br>
           <strong>Betreff:</strong> {subject}</p>
        {_btn(admin_url, "Ticket öffnen")}
    """
    )
    _send(
        ADMIN_EMAIL,
        f"[Lumios Support] Neues Ticket #{ticket_id}: {subject}",
        html,
    )


# ---------------------------------------------------------------------------
# Enqueueing API (called from request handlers)
# ---------------------------------------------------------------------------


def notify_registration(user_email: str) -> bool:
    from worker import send_registration_email_task

    return _enqueue(send_registration_email_task, user_email=user_email)


def notify_activation_email(user_id: int) -> bool:
    from worker import send_activation_email_task

    # One waiting mail per account: a second call collapses into it.
    return _enqueue(
        send_activation_email_task, lock=f"activation-{user_id}", user_id=user_id
    )


def notify_resend_activation(email: str, ip: str) -> bool:
    from worker import resend_activation_task

    # One waiting job per address, so a flood for one victim queues a single mail.
    digest = hashlib.sha256(email.encode()).hexdigest()[:32]
    return _enqueue(
        resend_activation_task, lock=f"resend-activation-{digest}", email=email, ip=ip
    )


def notify_admin_new_account(user_email: str, account_type: str) -> bool:
    from worker import send_admin_new_account_email_task

    return _enqueue(
        send_admin_new_account_email_task, user_email=user_email, account_type=account_type
    )


def notify_account_cancellation(user_email: str) -> bool:
    from worker import send_account_cancellation_email_task

    return _enqueue(send_account_cancellation_email_task, user_email=user_email)


def notify_agb_change(user_email: str, agb_version: str, summary: str) -> bool:
    """Queue the AGB notice for one recipient (callers iterate over the users)."""
    from worker import send_agb_change_email_task

    return _enqueue(
        send_agb_change_email_task,
        user_email=user_email,
        agb_version=agb_version,
        summary=summary,
    )


def notify_gallery_finished(
    photographer_email: str, library_name: str, library_uuid: str, liked_count: int
) -> bool:
    from worker import send_gallery_finished_email_task

    return _enqueue(
        send_gallery_finished_email_task,
        photographer_email=photographer_email,
        library_name=library_name,
        library_uuid=library_uuid,
        liked_count=liked_count,
    )


def notify_new_support_ticket(ticket_id: int, subject: str, user_email: str) -> bool:
    from worker import send_new_support_ticket_email_task

    return _enqueue(
        send_new_support_ticket_email_task,
        ticket_id=ticket_id,
        subject=subject,
        user_email=user_email,
    )
