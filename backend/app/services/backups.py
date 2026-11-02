"""Status of the off-site backups (database archives, photo mirror) for the admin pages.

The buckets are listed read-only over the S3 API. The result is cached in Redis for a
few minutes so a page reload never repeats the (possibly slow) listing. A failing or
missing source never raises: it yields ``unavailable`` / ``not_configured``.
"""

import re
from datetime import datetime, timezone

import boto3
from botocore.config import Config as BotoConfig

from config import (
    BACKUP_CACHE_TTL,
    BACKUP_DATABASE_ACCESS_KEY,
    BACKUP_DATABASE_BUCKET,
    BACKUP_DATABASE_SECRET_KEY,
    BACKUP_GCS_ENDPOINT,
    BACKUP_OVERDUE_SECONDS,
    BACKUP_PHOTOS_ACCESS_KEY,
    BACKUP_PHOTOS_BUCKET,
    BACKUP_PHOTOS_SECRET_KEY,
)
from services.redis_client import cache_get, cache_set

CACHE_KEY = "backups:status"
MAX_ARCHIVES = 30
ARCHIVE_PATTERN = re.compile(r"^lumios-postgres-.+\.tar$")
LAST_SYNC_KEY = ".last_sync"
ERROR_MAX_LENGTH = 200


def _get_gcs_client(endpoint: str, access_key: str, secret_key: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=BotoConfig(
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 1},
            signature_version="s3v4",
        ),
    )


def _iter_objects(client, bucket: str):
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        yield from page.get("Contents", [])


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _timing(last: datetime | None, now: datetime) -> dict:
    if last is None:
        return {"last_backup": None, "age_hours": None, "is_overdue": True}
    age = (now - last).total_seconds()
    return {
        "last_backup": last.strftime("%Y-%m-%d %H:%M"),
        "age_hours": round(age / 3600, 1),
        "is_overdue": age > BACKUP_OVERDUE_SECONDS,
    }


def _check_database_backups(client, bucket: str, now: datetime) -> dict:
    archives = []
    for obj in _iter_objects(client, bucket):
        name = obj["Key"].rsplit("/", 1)[-1]
        if ARCHIVE_PATTERN.match(name):
            archives.append(
                {
                    "name": name,
                    "modified": _aware(obj["LastModified"]),
                    "size": int(obj["Size"]),
                }
            )
    archives.sort(key=lambda a: a["modified"], reverse=True)
    result = {
        "status": "ok",
        "total_size": sum(a["size"] for a in archives),
        "archive_count": len(archives),
        "archives": [
            {
                "name": a["name"],
                "created": a["modified"].strftime("%Y-%m-%d %H:%M"),
                "size": a["size"],
            }
            for a in archives[:MAX_ARCHIVES]
        ],
    }
    result.update(_timing(archives[0]["modified"] if archives else None, now))
    return result


def _parse_marker(body: str) -> datetime | None:
    try:
        return _aware(datetime.strptime(body.strip(), "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def _check_photo_backups(client, bucket: str, now: datetime) -> dict:
    total_size = 0
    file_count = 0
    newest = None
    marker = None
    for obj in _iter_objects(client, bucket):
        modified = _aware(obj["LastModified"])
        if obj["Key"] == LAST_SYNC_KEY:
            marker = modified
            try:
                body = client.get_object(Bucket=bucket, Key=LAST_SYNC_KEY)["Body"]
                marker = _parse_marker(body.read(64).decode("ascii", "ignore")) or modified
            except Exception:
                pass
            continue
        total_size += int(obj["Size"])
        file_count += 1
        if newest is None or modified > newest:
            newest = modified
    result = {"status": "ok", "total_size": total_size, "file_count": file_count}
    result.update(_timing(marker or newest, now))
    return result


def _safe_error(ex: Exception) -> str:
    """Error text for the UI: exception class and message, no endpoint URLs or keys."""
    text = re.sub(r"https?://\S+", "<url>", f"{type(ex).__name__}: {ex}")
    return text[:ERROR_MAX_LENGTH]


def _run(name: str, bucket: str, access_key: str, secret_key: str, check, now) -> dict:
    if not (bucket and access_key and secret_key):
        return {"name": name, "status": "not_configured",
                "detail": "Backup bucket or read-only keys are not set"}
    try:
        client = _get_gcs_client(BACKUP_GCS_ENDPOINT, access_key, secret_key)
        result = check(client, bucket, now)
    except Exception as ex:
        return {"name": name, "status": "unavailable", "detail": _safe_error(ex)}
    result["name"] = name
    result["detail"] = ""
    return result


def get_backup_status() -> dict:
    cached = cache_get(CACHE_KEY)
    if cached:
        return cached
    now = datetime.now(timezone.utc)
    status = {
        "database": _run(
            "backup-database", BACKUP_DATABASE_BUCKET, BACKUP_DATABASE_ACCESS_KEY,
            BACKUP_DATABASE_SECRET_KEY, _check_database_backups, now,
        ),
        "photos": _run(
            "backup-photos", BACKUP_PHOTOS_BUCKET, BACKUP_PHOTOS_ACCESS_KEY,
            BACKUP_PHOTOS_SECRET_KEY, _check_photo_backups, now,
        ),
    }
    # Only cache a complete answer; a transient failure should be retried on reload.
    if all(s["status"] != "unavailable" for s in status.values()):
        cache_set(CACHE_KEY, status, BACKUP_CACHE_TTL)
    return status


def get_backup_summary() -> list[dict]:
    """One line per backup job for the admin overview."""
    status = get_backup_status()
    return [status["database"], status["photos"]]


def has_backup_problem(status: dict) -> bool:
    """True when a configured backup is overdue or its source is unreachable."""
    for s in status.values():
        if s["status"] == "unavailable" or (s["status"] == "ok" and s["is_overdue"]):
            return True
    return False
