"""Aggregates queue and worker state for the admin Workers page, and its retry/discard actions."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text

from models import AuditLogType, Video, VideoProcessingStatus, WorkerHeartbeat, WorkerJobError, db
from services.audit import write_audit_log
from services.videos import get_video_step

HEARTBEAT_ALIVE_SECONDS = 30
# Queued longer than this without being picked up is worth a warning
QUEUE_STALE_SECONDS = 600

# Pipelines whose workers must run; "photo" is off by default and only matters with work waiting
REQUIRED_QUEUES = ("default", "video")


def _queues() -> tuple[str, ...]:
    from worker import QUEUES

    return QUEUES


def _target(args: dict | None) -> str | None:
    """What a job works on (video, user, ticket or recipient), never the rest of its payload."""
    args = args or {}
    for key in ("video_uuid", "user_id", "ticket_id", "user_email", "photographer_email", "email"):
        if args.get(key):
            return str(args[key])
    return None


def _pipeline_counts(now: datetime) -> dict[str, dict]:
    pipelines = {
        q: {"queued": 0, "running": 0, "failed": 0, "finished_24h": 0, "oldest_queued_age": None}
        for q in _queues()
    }
    rows = db.session.execute(
        text(
            "SELECT queue_name, status::text AS status, count(*) AS n "
            "FROM procrastinate_jobs GROUP BY queue_name, status"
        )
    )
    for queue, status, n in rows:
        if queue not in pipelines:
            continue
        key = {"todo": "queued", "doing": "running", "failed": "failed"}.get(status)
        if key:
            pipelines[queue][key] = n

    rows = db.session.execute(
        text(
            "SELECT j.queue_name, count(*) AS n FROM procrastinate_events e "
            "JOIN procrastinate_jobs j ON j.id = e.job_id "
            "WHERE e.type = 'succeeded' AND e.at >= :since GROUP BY j.queue_name"
        ),
        {"since": now - timedelta(hours=24)},
    )
    for queue, n in rows:
        if queue in pipelines:
            pipelines[queue]["finished_24h"] = n

    # A job scheduled for later (retry backoff) is not waiting yet
    rows = db.session.execute(
        text(
            "SELECT queue_name, min(coalesce(scheduled_at, "
            "(SELECT min(e.at) FROM procrastinate_events e "
            " WHERE e.job_id = procrastinate_jobs.id AND e.type = 'deferred'))) AS since "
            "FROM procrastinate_jobs "
            "WHERE status = 'todo' AND (scheduled_at IS NULL OR scheduled_at <= :now) "
            "GROUP BY queue_name"
        ),
        {"now": now},
    )
    for queue, since in rows:
        if queue in pipelines and since is not None:
            pipelines[queue]["oldest_queued_age"] = max(
                0, int((now - since).total_seconds())
            )
    return pipelines


def _liveness(now: datetime) -> dict[str, dict]:
    liveness = {q: {"alive": 0, "last_heartbeat": None, "pods": []} for q in _queues()}
    for hb in db.session.execute(select(WorkerHeartbeat)).scalars():
        if hb.queue_name not in liveness:
            continue
        beat = hb.last_heartbeat
        age = (now - beat).total_seconds()
        entry = liveness[hb.queue_name]
        is_alive = age <= HEARTBEAT_ALIVE_SECONDS
        entry["alive"] += 1 if is_alive else 0
        entry["pods"].append({"hostname": hb.hostname, "alive": is_alive, "age": int(age)})
        if entry["last_heartbeat"] is None or beat > entry["last_heartbeat"]:
            entry["last_heartbeat"] = beat
    for entry in liveness.values():
        entry["last_heartbeat_age"] = (
            None
            if entry["last_heartbeat"] is None
            else int((now - entry["last_heartbeat"]).total_seconds())
        )
    return liveness


def _running_jobs(now: datetime) -> list[dict]:
    rows = db.session.execute(
        text(
            "SELECT j.id, j.queue_name, j.task_name, j.args, j.attempts, "
            "(SELECT max(e.at) FROM procrastinate_events e "
            " WHERE e.job_id = j.id AND e.type = 'started') AS started_at "
            "FROM procrastinate_jobs j WHERE j.status = 'doing' ORDER BY j.id"
        )
    ).mappings()
    jobs = []
    for row in rows:
        target = _target(row["args"])
        step = get_video_step(target) if target and row["task_name"] == "process_video" else None
        started_at = row["started_at"]
        jobs.append(
            {
                "id": row["id"],
                "queue": row["queue_name"],
                "task": row["task_name"],
                "target": target,
                "attempts": row["attempts"],
                "started_at": started_at,
                "elapsed": None
                if started_at is None
                else int((now - started_at).total_seconds()),
                "step": step,
            }
        )
    return jobs


def _failed_jobs() -> list[dict]:
    rows = db.session.execute(
        text(
            "SELECT j.id, j.queue_name, j.task_name, j.args, j.attempts, "
            "(SELECT max(e.at) FROM procrastinate_events e "
            " WHERE e.job_id = j.id AND e.type = 'failed') AS failed_at, "
            "w.error_message "
            "FROM procrastinate_jobs j "
            "LEFT JOIN worker_job_errors w ON w.job_id = j.id "
            "WHERE j.status = 'failed' ORDER BY j.id DESC"
        )
    ).mappings()
    return [
        {
            "id": row["id"],
            "queue": row["queue_name"],
            "task": row["task_name"],
            "target": _target(row["args"]),
            "attempts": row["attempts"],
            "failed_at": row["failed_at"],
            "error": row["error_message"],
        }
        for row in rows
    ]


def _verdict(pipelines: dict[str, dict]) -> tuple[str, str]:
    for queue, p in pipelines.items():
        needed = queue in REQUIRED_QUEUES or p["queued"] or p["running"]
        if needed and p["alive"] == 0:
            return "error", f"No worker is alive for {queue}"
    if any(p["failed"] for p in pipelines.values()):
        return "warning", "Failed jobs need attention"
    if any(
        p["oldest_queued_age"] is not None and p["oldest_queued_age"] > QUEUE_STALE_SECONDS
        for p in pipelines.values()
    ):
        return "warning", "A job has been waiting for a long time"
    return "ok", "Workers are running"


def _pipelines(now: datetime) -> dict[str, dict]:
    counts = _pipeline_counts(now)
    liveness = _liveness(now)
    return {q: {**counts[q], **liveness[q]} for q in counts}


def get_workers_status() -> dict:
    now = datetime.now(timezone.utc)
    pipelines = _pipelines(now)
    verdict, summary = _verdict(pipelines)
    return {
        "verdict": verdict,
        "summary": summary,
        "pipelines": pipelines,
        "running": _running_jobs(now),
        "failed": _failed_jobs(),
    }


def get_dashboard_workers_summary() -> dict:
    """Counts only; cheap enough for every dashboard load."""
    pipelines = _pipelines(datetime.now(timezone.utc))
    verdict, summary = _verdict(pipelines)
    return {
        "verdict": verdict,
        "summary": summary,
        "running": sum(p["running"] for p in pipelines.values()),
        "queued": sum(p["queued"] for p in pipelines.values()),
        "failed": sum(p["failed"] for p in pipelines.values()),
    }


def _failed_job_row(job_id: int):
    return db.session.execute(
        text(
            "SELECT id, task_name, args FROM procrastinate_jobs "
            "WHERE id = :id AND status = 'failed'"
        ),
        {"id": job_id},
    ).mappings().first()


def retry_failed_job(job_id: int, admin_user_id: int) -> bool:
    """Queue a failed job again; False when it is not (or no longer) failed."""
    job = _failed_job_row(job_id)
    if job is None:
        return False

    from worker import open_for_defer, worker_app

    open_for_defer()
    worker_app.job_manager.retry_job_by_id(job_id, retry_at=datetime.now(timezone.utc))

    target = _target(job["args"])
    if job["task_name"] == "process_video" and target:
        video = db.session.execute(
            select(Video).where(Video.uuid == target)
        ).scalar_one_or_none()
        if video is not None:
            video.processing_status = VideoProcessingStatus.processing
    db.session.execute(delete(WorkerJobError).where(WorkerJobError.job_id == job_id))
    write_audit_log(
        AuditLogType.worker_job_retried,
        creator_id=admin_user_id,
        related_object_type="worker_job",
        related_object_id=str(job_id),
    )
    db.session.commit()
    return True


def discard_failed_job(job_id: int, admin_user_id: int) -> bool:
    """Remove a failed job (its events go with it); False when it is not failed."""
    if _failed_job_row(job_id) is None:
        return False

    db.session.execute(
        text("DELETE FROM procrastinate_jobs WHERE id = :id AND status = 'failed'"),
        {"id": job_id},
    )
    db.session.execute(delete(WorkerJobError).where(WorkerJobError.job_id == job_id))
    write_audit_log(
        AuditLogType.worker_job_discarded,
        creator_id=admin_user_id,
        related_object_type="worker_job",
        related_object_id=str(job_id),
    )
    db.session.commit()
    return True
