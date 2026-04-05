# mail.py — transactional email service (Brevo)
#
# All functions are fire-and-forget: they log on error but never raise.
# When BREVO_API_KEY is not set the call is logged and skipped — safe for
# local development without email credentials.

import requests
from flask import current_app
from config import (
    ADMIN_EMAIL,
    BREVO_API_KEY,
    FRONTEND_URL,
    MAIL_SENDER_EMAIL,
    MAIL_SENDER_NAME,
)

_BREVO_CONTACTS_URL = "https://api.brevo.com/v3/contacts"

_BREVO_URL = "https://api.brevo.com/v3/smtp/email"

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
    """POST a single transactional email to Brevo. Logs and returns on any error."""
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
        if resp.ok:
            current_app.logger.info(
                "MAIL sent: to=%s subject=%r messageId=%s",
                to_email,
                subject,
                resp.json().get("messageId", ""),
                extra={"log_type": "mail"},
            )
        else:
            current_app.logger.error(
                "MAIL Brevo error: status=%d body=%r to=%s subject=%r",
                resp.status_code,
                resp.text[:300],
                to_email,
                subject,
                extra={"log_type": "mail"},
            )
    except Exception:
        current_app.logger.exception(
            "MAIL delivery failed: to=%s subject=%r",
            to_email,
            subject,
            extra={"log_type": "mail"},
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def notify_registration(user_email: str) -> None:
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


def notify_gallery_finished(
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


def notify_account_cancellation(user_email: str) -> None:
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


def notify_agb_change(user_email: str, agb_version: str, summary: str) -> None:
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


def notify_activation_email(user_email: str, activation_link: str) -> None:
    """Send an account activation email with a one-time link."""
    html = _html(
        f"""
        <h2>Willkommen bei Lumios!</h2>
        <p>Vielen Dank für Ihre Registrierung. Bitte aktivieren Sie Ihr Konto
           (<strong>{user_email}</strong>) durch Klick auf den folgenden Link.</p>
        {_btn(activation_link, "Konto aktivieren")}
        <p>Der Link ist 72 Stunden gültig. Falls Sie sich nicht registriert haben,
           können Sie diese E-Mail ignorieren.</p>
    """
    )
    _send(user_email, "Lumios – Konto aktivieren", html)


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


def notify_admin_new_account(user_email: str, account_type: str) -> None:
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


def notify_new_support_ticket(ticket_id: int, subject: str, user_email: str) -> None:
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
