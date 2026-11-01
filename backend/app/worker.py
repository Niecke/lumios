"""Background worker: Procrastinate app, queues and task definitions.

Jobs live in PostgreSQL, so they survive a restart of the backend or a worker.
Each pipeline is its own queue with its own worker Deployment (entrypoint.py
worker --queue <name>), so heavy work cannot starve light work:

    default  short jobs (mail, ...)
    video    ffmpeg probing and thumbnail extraction, one job at a time
    photo    quick image thumbnails/previews; prepared, not used yet
"""

import asyncio
import atexit
import logging
import re
import socket
import threading

from datetime import datetime, timedelta, timezone

from procrastinate import App, PsycopgConnector, RetryStrategy
from procrastinate.jobs import Status
from sqlalchemy import delete

from config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)

logger = logging.getLogger(__name__)

QUEUE_DEFAULT = "default"
QUEUE_VIDEO = "video"
QUEUE_PHOTO = "photo"
QUEUES = (QUEUE_DEFAULT, QUEUE_VIDEO, QUEUE_PHOTO)

# Total runs of a video job, the first one included
VIDEO_MAX_RUNS = 3
# Procrastinate counts retries in job.attempts (0 on the first run)
VIDEO_RETRY = RetryStrategy(max_attempts=VIDEO_MAX_RUNS - 1, wait=5, exponential_wait=2)

# Total runs of a mail job, the first one included
MAIL_MAX_RUNS = 3


class MailRetryStrategy(RetryStrategy):
    """Backoff for mail jobs, except when Brevo refuses the mail for good."""

    def get_retry_decision(self, *, exception, job):
        from services.mail import PermanentMailError

        if isinstance(exception, PermanentMailError):
            return None
        return super().get_retry_decision(exception=exception, job=job)


MAIL_RETRY = MailRetryStrategy(max_attempts=MAIL_MAX_RUNS - 1, wait=5, exponential_wait=2)

worker_app = App(
    connector=PsycopgConnector(
        kwargs={
            "host": POSTGRES_HOST,
            "port": POSTGRES_PORT,
            "user": POSTGRES_USER,
            "password": POSTGRES_PASSWORD,
            "dbname": POSTGRES_DB,
        },
        min_size=1,
        max_size=10,
    ),
    import_paths=["worker"],
)

# Error text shown on the admin Workers page: one short line, no URLs, paths or keys
ERROR_MAX_LENGTH = 200

HEARTBEAT_INTERVAL_SECONDS = 10
# Rows of pods that are gone for good (new pod names on every rollout) are dropped after this
HEARTBEAT_PRUNE_SECONDS = 24 * 3600

_flask_app = None


def get_flask_app():
    """The Flask app jobs run in (database session, config); built once per process."""
    global _flask_app
    if _flask_app is None:
        from main import create_app

        _flask_app = create_app()
    return _flask_app


def open_for_defer() -> None:
    """Open the sync connection pool of this process; a no-op once open."""
    worker_app.open()


def close_worker_app() -> None:
    """Close the sync connection pool opened by open_for_defer(); safe to call repeatedly.

    An open psycopg_pool.ConnectionPool that is garbage collected during interpreter
    shutdown fails with PythonFinalizationError, so it is closed explicitly. The sync
    connector is closed directly: PsycopgConnector.close() raises NotImplementedError
    once the async pool was used. open_for_defer() creates a fresh pool afterwards.
    """
    connector = worker_app.connector
    sync_connector = getattr(connector, "_sync_connector", None)
    if sync_connector is None:
        return
    try:
        sync_connector.close()
    finally:
        connector._sync_connector = None


atexit.register(close_worker_app)


def summarize_error(exc: BaseException) -> str:
    """One truncated line of an exception, safe to show to admins."""
    lines = [line for line in str(exc).splitlines() if line.strip()]
    text = f"{type(exc).__name__}: {lines[-1].strip() if lines else ''}"
    text = re.sub(r"\w+://\S+", "<url>", text)
    text = " ".join("<path>" if "/" in word else word for word in text.split())
    return text[:ERROR_MAX_LENGTH]


def record_job_error(job_id: int, queue_name: str, task_name: str, message: str) -> None:
    """Remember the last error of a job for the admin Workers page (runs in an app context)."""
    from models import WorkerJobError, db

    try:
        row = db.session.get(WorkerJobError, job_id)
        if row is None:
            row = WorkerJobError(job_id=job_id)
            db.session.add(row)
        row.queue_name = queue_name
        row.task_name = task_name
        row.error_message = message[:ERROR_MAX_LENGTH]
        row.created_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not record the error of job %s", job_id)


def clear_job_error(job_id: int) -> None:
    from models import WorkerJobError, db

    try:
        db.session.execute(delete(WorkerJobError).where(WorkerJobError.job_id == job_id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not clear the error of job %s", job_id)


def beat_heartbeat(queue_name: str, hostname: str, started_at: datetime) -> None:
    """Upsert this pod's row in worker_heartbeats (runs in an app context)."""
    from models import WorkerHeartbeat, db

    try:
        row = db.session.get(WorkerHeartbeat, hostname)
        if row is None:
            row = WorkerHeartbeat(hostname=hostname, started_at=started_at)
            db.session.add(row)
        row.queue_name = queue_name
        now = datetime.now(timezone.utc)
        row.last_heartbeat = now
        db.session.execute(
            delete(WorkerHeartbeat).where(
                WorkerHeartbeat.last_heartbeat
                < now - timedelta(seconds=HEARTBEAT_PRUNE_SECONDS)
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not write the heartbeat of %s", hostname)
    finally:
        db.session.remove()


def remove_heartbeat(hostname: str) -> None:
    from models import WorkerHeartbeat, db

    try:
        db.session.execute(
            delete(WorkerHeartbeat).where(WorkerHeartbeat.hostname == hostname)
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not remove the heartbeat of %s", hostname)
    finally:
        db.session.remove()


def start_heartbeat(queue_name: str) -> tuple[threading.Event, threading.Thread]:
    """Write a heartbeat for this pod every few seconds until the returned event is set."""
    hostname = socket.gethostname()
    started_at = datetime.now(timezone.utc)
    stop = threading.Event()
    flask_app = get_flask_app()

    def loop() -> None:
        with flask_app.app_context():
            while True:
                beat_heartbeat(queue_name, hostname, started_at)
                if stop.wait(HEARTBEAT_INTERVAL_SECONDS):
                    break
            remove_heartbeat(hostname)

    thread = threading.Thread(target=loop, name="worker-heartbeat", daemon=True)
    thread.start()
    return stop, thread


@worker_app.task(
    queue=QUEUE_VIDEO,
    name="process_video",
    retry=VIDEO_RETRY,
    pass_context=True,
)
def process_video_task(context, video_uuid: str) -> None:
    """Probe a finalized video and extract its thumbnail.

    Errors propagate so Procrastinate retries with backoff; after the last run
    the job stays in status ``failed`` (the dead letter) and the video is marked
    failed, so the photographer sees it instead of an eternal "processing".
    """
    from models import Video, VideoProcessingStatus, db
    from services.videos import process_video
    from sqlalchemy import select

    with get_flask_app().app_context():
        try:
            process_video(video_uuid)
            clear_job_error(context.job.id)
        except Exception as exc:
            db.session.rollback()
            record_job_error(
                context.job.id, QUEUE_VIDEO, "process_video", summarize_error(exc)
            )
            if context.job.attempts >= VIDEO_MAX_RUNS - 1:
                video = db.session.execute(
                    select(Video).where(Video.uuid == video_uuid)
                ).scalar_one_or_none()
                if video is not None:
                    video.processing_status = VideoProcessingStatus.failed
                    db.session.commit()
                logger.error("Video job %s exhausted its retries", video_uuid)
            raise
        finally:
            db.session.remove()


def _run_mail_job(context, task_name: str, fn, **kwargs) -> None:
    """Run one mail job in an app context; errors propagate so the job is retried."""
    from models import db

    with get_flask_app().app_context():
        try:
            fn(**kwargs)
            clear_job_error(context.job.id)
        except Exception as exc:
            db.session.rollback()
            record_job_error(
                context.job.id, QUEUE_DEFAULT, task_name, summarize_error(exc)
            )
            logger.error(
                "Mail job %s (%s) failed in run %d: %s",
                context.job.id,
                task_name,
                context.job.attempts + 1,
                type(exc).__name__,
            )
            raise
        finally:
            db.session.remove()


def _mail_task(name: str):
    return worker_app.task(
        queue=QUEUE_DEFAULT, name=name, retry=MAIL_RETRY, pass_context=True
    )


@_mail_task("send_registration_email")
def send_registration_email_task(context, user_email: str) -> None:
    from services.mail import send_registration_email

    _run_mail_job(
        context, "send_registration_email", send_registration_email, user_email=user_email
    )


@_mail_task("send_activation_email")
def send_activation_email_task(context, user_id: int) -> None:
    from services.mail import send_activation_email

    _run_mail_job(context, "send_activation_email", send_activation_email, user_id=user_id)


@_mail_task("resend_activation")
def resend_activation_task(context, email: str, ip: str) -> None:
    from services.mail import process_resend_activation

    _run_mail_job(
        context, "resend_activation", process_resend_activation, email=email, ip=ip
    )


@_mail_task("send_admin_new_account_email")
def send_admin_new_account_email_task(context, user_email: str, account_type: str) -> None:
    from services.mail import send_admin_new_account_email

    _run_mail_job(
        context,
        "send_admin_new_account_email",
        send_admin_new_account_email,
        user_email=user_email,
        account_type=account_type,
    )


@_mail_task("send_account_cancellation_email")
def send_account_cancellation_email_task(context, user_email: str) -> None:
    from services.mail import send_account_cancellation_email

    _run_mail_job(
        context,
        "send_account_cancellation_email",
        send_account_cancellation_email,
        user_email=user_email,
    )


@_mail_task("send_agb_change_email")
def send_agb_change_email_task(
    context, user_email: str, agb_version: str, summary: str
) -> None:
    from services.mail import send_agb_change_email

    _run_mail_job(
        context,
        "send_agb_change_email",
        send_agb_change_email,
        user_email=user_email,
        agb_version=agb_version,
        summary=summary,
    )


@_mail_task("send_gallery_finished_email")
def send_gallery_finished_email_task(
    context,
    photographer_email: str,
    library_name: str,
    library_uuid: str,
    liked_count: int,
) -> None:
    from services.mail import send_gallery_finished_email

    _run_mail_job(
        context,
        "send_gallery_finished_email",
        send_gallery_finished_email,
        photographer_email=photographer_email,
        library_name=library_name,
        library_uuid=library_uuid,
        liked_count=liked_count,
    )


@_mail_task("send_new_support_ticket_email")
def send_new_support_ticket_email_task(
    context, ticket_id: int, subject: str, user_email: str
) -> None:
    from services.mail import send_new_support_ticket_email

    _run_mail_job(
        context,
        "send_new_support_ticket_email",
        send_new_support_ticket_email,
        ticket_id=ticket_id,
        subject=subject,
        user_email=user_email,
    )


def _mark_video_failed(video_uuid: str) -> None:
    from models import Video, VideoProcessingStatus, db
    from sqlalchemy import select

    with get_flask_app().app_context():
        video = db.session.execute(
            select(Video).where(Video.uuid == video_uuid)
        ).scalar_one_or_none()
        if video is not None:
            video.processing_status = VideoProcessingStatus.failed
            db.session.commit()
        db.session.remove()


def _record_stalled_error(job) -> None:
    with get_flask_app().app_context():
        record_job_error(
            job.id, job.queue, job.task_name, "Worker died while running the job"
        )
        from models import db

        db.session.remove()


async def recover_stalled_jobs_now() -> int:
    """Retry or fail jobs whose worker died mid-run (killed pod, OOM, node loss).

    A job of a dead worker stays in ``doing`` until someone looks at it. It gets
    the retry policy of its task; once that is used up it ends in ``failed``
    like any other job that kept failing. Returns the number of jobs handled.
    """
    manager = worker_app.job_manager
    handled = 0
    for job in await manager.get_stalled_jobs():
        strategy = worker_app.tasks[job.task_name].retry_strategy
        decision = (
            strategy.get_retry_decision(exception=RuntimeError("worker died"), job=job)
            if strategy
            else None
        )
        if decision:
            await manager.retry_job(job, retry_at=decision.retry_at)
        else:
            await manager.finish_job(job, status=Status.FAILED, delete_job=False)
            await asyncio.to_thread(_record_stalled_error, job)
            if job.task_name == "process_video":
                await asyncio.to_thread(_mark_video_failed, job.task_kwargs["video_uuid"])
        logger.warning("Recovered stalled job %s (%s)", job.id, job.task_name)
        handled += 1
    return handled


@worker_app.periodic(cron="*/5 * * * *")
@worker_app.task(
    queue=QUEUE_DEFAULT,
    name="recover_stalled_jobs",
    queueing_lock="recover_stalled_jobs",
)
async def recover_stalled_jobs(timestamp: int) -> None:
    await recover_stalled_jobs_now()


def check_worker_health() -> int:
    """0 when the queue database answers and the Procrastinate schema is there."""
    try:
        with worker_app.open():
            if not worker_app.check_connection():
                return 1
        return 0
    except Exception:
        logger.exception("Worker health check failed")
        return 1
