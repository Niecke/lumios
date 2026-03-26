"""
Flask CLI commands for background maintenance tasks.
Run via: flask <command-name>
"""

import click
from datetime import datetime, timezone, timedelta
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import select, delete

from models import (
    db,
    User,
    Library,
    Image,
    Notification,
    SupportTicket,
    SupportTicketComment,
    roles_users,
)
import services.storage as storage

ACCOUNT_RETENTION_DAYS = 30


@click.command("purge-deleted-accounts")
@with_appcontext
def purge_deleted_accounts() -> None:
    """Hard-delete accounts soft-deleted more than 30 days ago.

    For each qualifying user, removes all associated DB rows and GCS objects
    (photos, previews, thumbnails). GCS failures are logged and skipped so that
    DB cleanup always completes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=ACCOUNT_RETENTION_DAYS)

    users = db.session.execute(
        select(User).where(User.deleted_at.isnot(None), User.deleted_at <= cutoff)
    ).scalars().all()

    if not users:
        current_app.logger.info(
            "purge-deleted-accounts: no accounts to purge",
            extra={"log_type": "cleanup"},
        )
        return

    current_app.logger.info(
        "purge-deleted-accounts: purging %d account(s) deleted before %s",
        len(users),
        cutoff.date(),
        extra={"log_type": "cleanup"},
    )

    for user in users:
        _purge_user(user)

    db.session.commit()

    current_app.logger.info(
        "purge-deleted-accounts: complete",
        extra={"log_type": "cleanup"},
    )


def _purge_user(user: User) -> None:
    libraries = db.session.execute(
        select(Library).where(Library.user_id == user.id)
    ).scalars().all()

    for library in libraries:
        _purge_library(library)

    db.session.execute(delete(Notification).where(Notification.user_id == user.id))

    tickets = db.session.execute(
        select(SupportTicket).where(SupportTicket.user_id == user.id)
    ).scalars().all()
    for ticket in tickets:
        db.session.execute(
            delete(SupportTicketComment).where(
                SupportTicketComment.ticket_id == ticket.id
            )
        )
        db.session.delete(ticket)

    db.session.execute(delete(roles_users).where(roles_users.c.user_id == user.id))
    db.session.delete(user)

    current_app.logger.info(
        "purge-deleted-accounts: purged account %s",
        user.email,
        extra={"log_type": "audit"},
    )


def _purge_library(library: Library) -> None:
    images = db.session.execute(
        select(Image).where(Image.library_id == library.id)
    ).scalars().all()

    for image in images:
        for variant in ("originals", "previews", "thumbs"):
            key = image.storage_path(variant)
            try:
                storage.delete_object(key)
            except Exception as exc:
                current_app.logger.warning(
                    "purge-deleted-accounts: GCS delete failed for key %s: %s",
                    key,
                    exc,
                    extra={"log_type": "cleanup"},
                )
        db.session.delete(image)

    db.session.delete(library)
