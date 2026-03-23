# mail.py — transactional email service
#
# TODO: Replace dummy implementation with Brevo transactional API.
#       All function signatures and log messages below document exactly what
#       each email should contain so the real implementation is straightforward.

from flask import current_app


def notify_new_support_ticket(ticket_id: int, subject: str, user_email: str) -> None:
    """Notify the admin that a new support ticket has been submitted.

    TODO: Send a Brevo transactional email to the admin address with:
      - Subject: f"[Lumios Support] New ticket #{ticket_id}: {subject}"
      - Body: ticket subject, body, and the submitting user's email
    """
    current_app.logger.info(
        "MAIL notify_new_support_ticket: ticket_id=%d subject=%r from=%s",
        ticket_id,
        subject,
        user_email,
        extra={"log_type": "mail"},
    )
