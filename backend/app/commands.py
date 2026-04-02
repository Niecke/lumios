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
    Role,
    Library,
    Image,
    Notification,
    SupportTicket,
    SupportTicketComment,
    roles_users,
    JobRun,
    AuditLog,
    AgbUpdate,
)
from sqlalchemy import update
import services.storage as storage

ACCOUNT_RETENTION_DAYS = 30
AUDIT_LOG_RETENTION_DAYS = 90


@click.command("purge-deleted-accounts")
@with_appcontext
def purge_deleted_accounts() -> None:
    """Hard-delete accounts soft-deleted more than 30 days ago.

    For each qualifying user, removes all associated DB rows and GCS objects
    (photos, previews, thumbnails). GCS failures are logged and skipped so that
    DB cleanup always completes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=ACCOUNT_RETENTION_DAYS)
    ran_at = datetime.now(timezone.utc)

    try:
        users = (
            db.session.execute(
                select(User).where(
                    User.deleted_at.isnot(None), User.deleted_at <= cutoff
                )
            )
            .scalars()
            .all()
        )

        if not users:
            current_app.logger.info(
                "purge-deleted-accounts: no accounts to purge",
                extra={"log_type": "cleanup"},
            )
            db.session.add(
                JobRun(
                    job_name="purge-deleted-accounts",
                    ran_at=ran_at,
                    status="success",
                    records_affected=0,
                )
            )
            db.session.commit()
            return

        current_app.logger.info(
            "purge-deleted-accounts: purging %d account(s) deleted before %s",
            len(users),
            cutoff.date(),
            extra={"log_type": "cleanup"},
        )

        for user in users:
            _purge_user(user)

        db.session.add(
            JobRun(
                job_name="purge-deleted-accounts",
                ran_at=ran_at,
                status="success",
                records_affected=len(users),
            )
        )
        db.session.commit()

        current_app.logger.info(
            "purge-deleted-accounts: complete",
            extra={"log_type": "cleanup"},
        )
    except Exception as exc:
        current_app.logger.exception(
            "purge-deleted-accounts: failed", extra={"log_type": "cleanup"}
        )
        db.session.rollback()
        db.session.add(
            JobRun(
                job_name="purge-deleted-accounts",
                ran_at=ran_at,
                status="error",
                error_message=str(exc),
            )
        )
        db.session.commit()
        raise SystemExit(1) from exc


@click.command("purge-audit-logs")
@with_appcontext
def purge_audit_logs() -> None:
    """Delete audit log entries older than 90 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=AUDIT_LOG_RETENTION_DAYS)
    ran_at = datetime.now(timezone.utc)

    try:
        result = db.session.execute(
            delete(AuditLog).where(AuditLog.audit_date < cutoff)
        )
        count = result.rowcount

        current_app.logger.info(
            "purge-audit-logs: deleted %d row(s) older than %s",
            count,
            cutoff.date(),
            extra={"log_type": "cleanup"},
        )

        db.session.add(
            JobRun(
                job_name="purge-audit-logs",
                ran_at=ran_at,
                status="success",
                records_affected=count,
            )
        )
        db.session.commit()
    except Exception as exc:
        current_app.logger.exception(
            "purge-audit-logs: failed", extra={"log_type": "cleanup"}
        )
        db.session.rollback()
        db.session.add(
            JobRun(
                job_name="purge-audit-logs",
                ran_at=ran_at,
                status="error",
                error_message=str(exc),
            )
        )
        db.session.commit()
        raise SystemExit(1) from exc


@click.command("apply-agb-acceptance")
@with_appcontext
def apply_agb_acceptance() -> None:
    """Apply pending AGB/AVV acceptance to all active users.

    For each AgbUpdate whose effective_at has passed and that has not yet been
    applied, bulk-updates every active user's agb_version and agb_accepted_at,
    then marks the AgbUpdate as applied.

    Run daily via Cloud Scheduler alongside purge-deleted-accounts.
    """
    now = datetime.now(timezone.utc)
    ran_at = now

    try:
        pending = (
            db.session.execute(
                select(AgbUpdate).where(
                    AgbUpdate.effective_at <= now,
                    AgbUpdate.applied_at.is_(None),
                )
            )
            .scalars()
            .all()
        )

        if not pending:
            current_app.logger.info(
                "apply-agb-acceptance: no pending updates",
                extra={"log_type": "cleanup"},
            )
            db.session.add(
                JobRun(
                    job_name="apply-agb-acceptance",
                    ran_at=ran_at,
                    status="success",
                    records_affected=0,
                )
            )
            db.session.commit()
            return

        total_affected = 0
        for agb_update in pending:
            result = db.session.execute(
                update(User)
                .where(User.deleted_at.is_(None), User.active.is_(True))
                .values(
                    agb_version=agb_update.version,
                    agb_accepted_at=agb_update.effective_at,
                )
            )
            affected = result.rowcount
            agb_update.applied_at = now
            total_affected += affected

            current_app.logger.info(
                "apply-agb-acceptance: applied version=%r to %d user(s)",
                agb_update.version,
                affected,
                extra={"log_type": "audit"},
            )

        db.session.add(
            JobRun(
                job_name="apply-agb-acceptance",
                ran_at=ran_at,
                status="success",
                records_affected=total_affected,
            )
        )
        db.session.commit()

        current_app.logger.info(
            "apply-agb-acceptance: complete, %d update(s) applied",
            len(pending),
            extra={"log_type": "cleanup"},
        )
    except Exception as exc:
        current_app.logger.exception(
            "apply-agb-acceptance: failed", extra={"log_type": "cleanup"}
        )
        db.session.rollback()
        db.session.add(
            JobRun(
                job_name="apply-agb-acceptance",
                ran_at=ran_at,
                status="error",
                error_message=str(exc),
            )
        )
        db.session.commit()
        raise SystemExit(1) from exc


@click.command("seed-test-data")
@with_appcontext
def seed_test_data() -> None:
    """Seed test fixtures for integration tests. Only runs when DEBUG=true.

    Creates:
      - roles: photographer, admin
      - photographer@test.com / TestPass123!  (active, photographer role)
      - admin@test.com / AdminPass123!        (active, admin role)
    """
    from config import DEBUG

    if not DEBUG:
        click.echo("ERROR: seed-test-data only runs when DEBUG=true", err=True)
        raise SystemExit(1)

    def _get_or_create_role(name: str, description: str) -> Role:
        role = db.session.execute(
            select(Role).where(Role.name == name)
        ).scalar_one_or_none()
        if not role:
            role = Role(name=name, description=description)
            db.session.add(role)
            db.session.flush()
        return role

    photographer_role = _get_or_create_role("photographer", "Photographer")
    admin_role = _get_or_create_role("admin", "Administrator")

    def _get_or_create_user(email: str, password: str, roles: list) -> User:
        user = db.session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if not user:
            user = User(email=email, active=True)
            user.set_password(password)
            user.roles = roles
            db.session.add(user)
        return user

    _get_or_create_user("photographer@test.com", "TestPass123!", [photographer_role])
    _get_or_create_user("admin@test.com", "AdminPass123!", [admin_role])

    db.session.commit()
    click.echo("Test data seeded: photographer@test.com, admin@test.com")


def _purge_user(user: User) -> None:
    libraries = (
        db.session.execute(select(Library).where(Library.user_id == user.id))
        .scalars()
        .all()
    )

    for library in libraries:
        _purge_library(library)

    db.session.execute(delete(Notification).where(Notification.user_id == user.id))

    tickets = (
        db.session.execute(
            select(SupportTicket).where(SupportTicket.user_id == user.id)
        )
        .scalars()
        .all()
    )
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
    images = (
        db.session.execute(select(Image).where(Image.library_id == library.id))
        .scalars()
        .all()
    )

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
