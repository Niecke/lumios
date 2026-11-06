"""Apply pending AGB/AVV acceptance. Used by the CLI command and the daily worker task."""

from datetime import datetime, timezone

import sentry_sdk
from flask import current_app
from sqlalchemy import select, update

from models import AgbUpdate, JobRun, User, db

JOB_NAME = "apply-agb-acceptance"


def apply_agb_acceptance_now() -> int:
    """Apply every AgbUpdate whose effective_at has passed and that is not yet applied.

    Bulk-updates every active user's agb_version and agb_accepted_at and marks the
    AgbUpdate as applied. Idempotent: an applied update is never picked up again, and
    nothing happens before the effective date. Returns the number of updates applied.
    Records a JobRun row; on failure the error is reported to Sentry, recorded and re-raised.
    """
    now = datetime.now(timezone.utc)

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
                JobRun(job_name=JOB_NAME, ran_at=now, status="success", records_affected=0)
            )
            db.session.commit()
            return 0

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
                job_name=JOB_NAME,
                ran_at=now,
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
        return len(pending)
    except Exception as exc:
        current_app.logger.exception(
            "apply-agb-acceptance: failed", extra={"log_type": "cleanup"}
        )
        sentry_sdk.capture_exception(exc)
        sentry_sdk.flush(timeout=2.0)
        db.session.rollback()
        db.session.add(
            JobRun(job_name=JOB_NAME, ran_at=now, status="error", error_message=str(exc))
        )
        db.session.commit()
        raise
