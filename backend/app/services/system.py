"""Aggregates build info and dependency health for the admin System page."""

import platform
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import gunicorn
import requests
from sqlalchemy import desc, select, text

from config import (
    APP_VERSION,
    BUILD_TIMESTAMP,
    FRONTEND_URL,
    GIT_HASH,
    LANDINGPAGE_URL,
    S3_BUCKET,
)
from models import JobRun, db
from services import storage
from services.redis_client import get_redis

JOB_NAMES = ["purge-deleted-accounts", "purge-audit-logs"]
JOB_OVERDUE_SECONDS = 36 * 3600
REMOTE_TIMEOUT_SECONDS = 1.5
DETAIL_MAX_LENGTH = 200


def _timed(name: str, func) -> dict:
    start = time.perf_counter()
    try:
        func()
    except Exception as ex:
        return {
            "name": name,
            "status": "failed",
            "ms": round((time.perf_counter() - start) * 1000, 1),
            "detail": f"{type(ex).__name__}: {ex}"[:DETAIL_MAX_LENGTH],
        }
    return {
        "name": name,
        "status": "ok",
        "ms": round((time.perf_counter() - start) * 1000, 1),
        "detail": "",
    }


def _check_database() -> dict:
    result = _timed("PostgreSQL", lambda: db.session.execute(text("SELECT 1")))
    if result["status"] == "failed":
        db.session.rollback()
    return result


def _check_redis() -> dict:
    r = get_redis()
    if r is None:
        return {
            "name": "Redis",
            "status": "not_configured",
            "ms": None,
            "detail": "REDIS_URL is not set",
        }
    return _timed("Redis", r.ping)


def _check_storage() -> dict:
    return _timed(
        "Object storage", lambda: storage._client.head_bucket(Bucket=S3_BUCKET)
    )


def _alembic_revision() -> str | None:
    try:
        return db.session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    except Exception:
        db.session.rollback()
        return None


def _remote_build(name: str, base_url: str) -> dict:
    build = {
        "name": name,
        "reachable": False,
        "commit": None,
        "version": None,
        "built_at": None,
    }
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/version.json", timeout=REMOTE_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        data = resp.json()
        build.update(
            reachable=True,
            commit=data.get("commit"),
            version=data.get("version"),
            built_at=data.get("built_at"),
        )
    except Exception:
        pass
    return build


def _job_status(name: str, now: datetime) -> dict:
    run = db.session.execute(
        select(JobRun)
        .where(JobRun.job_name == name)
        .order_by(desc(JobRun.ran_at))
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        return {"name": name, "run": None, "age_hours": None,
                "last_failed": False, "is_overdue": True}
    ran_at = run.ran_at if run.ran_at.tzinfo else run.ran_at.replace(tzinfo=timezone.utc)
    age_seconds = (now - ran_at).total_seconds()
    last_failed = run.status != "success"
    return {
        "name": name,
        "run": run,
        "age_hours": round(age_seconds / 3600, 1),
        "last_failed": last_failed,
        "is_overdue": last_failed or age_seconds > JOB_OVERDUE_SECONDS,
    }


def _backend_build() -> dict:
    return {
        "name": "Backend",
        "reachable": True,
        "commit": GIT_HASH,
        "version": APP_VERSION,
        "built_at": BUILD_TIMESTAMP,
    }


def _verdict(checks: list, commit_mismatch: bool, jobs: list) -> tuple[str, str]:
    if any(c["status"] == "failed" for c in checks):
        return "degraded", "A dependency is failing"
    if commit_mismatch:
        return "warning", "Components run different commits"
    if any(j["is_overdue"] for j in jobs):
        return "warning", "A scheduled job is overdue"
    return "ok", "Everything is running"


def get_dashboard_status() -> dict:
    """Cheap local checks only (DB, jobs); no network calls, safe on every dashboard load."""
    checks = [_check_database()]
    jobs = [_job_status(name, datetime.now(timezone.utc)) for name in JOB_NAMES]
    verdict, summary = _verdict(checks, False, jobs)
    return {"verdict": verdict, "summary": summary, "backend": _backend_build()}


def get_system_status() -> dict:
    checks = [_check_database(), _check_redis()]
    # Storage and the remote version fetches are network-bound: run them concurrently.
    with ThreadPoolExecutor(max_workers=3) as pool:
        storage_f = pool.submit(_check_storage)
        frontend_f = pool.submit(_remote_build, "Frontend", FRONTEND_URL)
        landing_f = pool.submit(_remote_build, "Landing page", LANDINGPAGE_URL)
        checks.append(storage_f.result())
        builds = [_backend_build(), frontend_f.result(), landing_f.result()]
    backend = builds[0]
    commits = {b["commit"] for b in builds if b["reachable"] and b["commit"]}
    commit_mismatch = len(commits) > 1

    jobs = [_job_status(name, datetime.now(timezone.utc)) for name in JOB_NAMES]

    runtime = {
        "python": platform.python_version(),
        "gunicorn": gunicorn.__version__,
        "migration": _alembic_revision(),
    }

    verdict, summary = _verdict(checks, commit_mismatch, jobs)

    return {
        "verdict": verdict,
        "summary": summary,
        "checks": checks,
        "builds": builds,
        "commit_mismatch": commit_mismatch,
        "jobs": jobs,
        "runtime": runtime,
        "backend": backend,
    }
