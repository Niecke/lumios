"""Background worker: Procrastinate app, queues and task definitions.

Jobs live in PostgreSQL, so they survive a restart of the backend or a worker.
Each pipeline is its own queue with its own worker Deployment (entrypoint.py
worker --queue <name>), so heavy work cannot starve light work:

    default  short jobs (mail, ...)
    video    ffmpeg probing and thumbnail extraction, one job at a time
    photo    quick image thumbnails/previews; prepared, not used yet
"""

import asyncio
import logging

from procrastinate import App, PsycopgConnector, RetryStrategy
from procrastinate.jobs import Status

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
        except Exception:
            db.session.rollback()
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
