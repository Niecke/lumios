from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from services import backups

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _client(objects, marker_body=None):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"Contents": objects}]
    if marker_body is None:
        client.get_object.side_effect = RuntimeError("no marker body")
    else:
        client.get_object.return_value = {
            "Body": MagicMock(read=lambda n: marker_body.encode())
        }
    return client


def _archive(hours_ago, size=100, name=None):
    ts = NOW - timedelta(hours=hours_ago)
    return {
        "Key": name or f"lumios-postgres-{ts:%Y%m%dT%H%M%S}.tar",
        "LastModified": ts,
        "Size": size,
    }


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    for attr in (
        "BACKUP_DATABASE_BUCKET",
        "BACKUP_DATABASE_ACCESS_KEY",
        "BACKUP_DATABASE_SECRET_KEY",
        "BACKUP_PHOTOS_BUCKET",
        "BACKUP_PHOTOS_ACCESS_KEY",
        "BACKUP_PHOTOS_SECRET_KEY",
    ):
        monkeypatch.setattr(backups, attr, "x")
    monkeypatch.setattr(backups, "cache_get", lambda k: None)
    monkeypatch.setattr(backups, "cache_set", lambda *a, **kw: None)


def test_unconfigured(monkeypatch):
    monkeypatch.setattr(backups, "BACKUP_DATABASE_BUCKET", "")
    monkeypatch.setattr(backups, "BACKUP_PHOTOS_SECRET_KEY", "")
    with patch.object(backups, "_get_gcs_client") as get:
        status = backups.get_backup_status()
    assert status["database"]["status"] == "not_configured"
    assert status["photos"]["status"] == "not_configured"
    get.assert_not_called()


def test_database_backup_empty_bucket():
    r = backups._check_database_backups(_client([]), "b", NOW)
    assert r["archives"] == []
    assert r["total_size"] == 0
    assert r["is_overdue"] is True
    assert r["last_backup"] is None


def test_database_backup_newest_first_and_capped():
    objs = [_archive(h) for h in range(1, 41)]
    objs.append({"Key": "other.txt", "LastModified": NOW, "Size": 5})
    r = backups._check_database_backups(_client(list(reversed(objs))), "b", NOW)
    assert len(r["archives"]) == 30
    assert r["archive_count"] == 40
    created = [a["created"] for a in r["archives"]]
    assert created == sorted(created, reverse=True)
    assert r["age_hours"] == 1.0


def test_database_backup_size_sum():
    objs = [_archive(1, 100), _archive(30, 250)]
    r = backups._check_database_backups(_client(objs), "b", NOW)
    assert r["total_size"] == 350


def test_database_backup_overdue_threshold():
    assert backups._check_database_backups(_client([_archive(35)]), "b", NOW)["is_overdue"] is False
    assert backups._check_database_backups(_client([_archive(37)]), "b", NOW)["is_overdue"] is True


def test_photo_backup_with_last_sync():
    objs = [
        {"Key": "current/a.jpg", "LastModified": NOW - timedelta(days=9), "Size": 10},
        {"Key": "deleted/2026-10-01/b.jpg", "LastModified": NOW - timedelta(days=9), "Size": 5},
        {"Key": ".last_sync", "LastModified": NOW - timedelta(hours=2), "Size": 20},
    ]
    r = backups._check_photo_backups(_client(objs, "2026-11-02T09:00:00Z"), "b", NOW)
    assert r["total_size"] == 15
    assert r["file_count"] == 2
    assert r["age_hours"] == 3.0
    assert r["is_overdue"] is False


def test_photo_backup_fallback_newest_object():
    objs = [
        {"Key": "current/a.jpg", "LastModified": NOW - timedelta(hours=50), "Size": 10},
        {"Key": "current/b.jpg", "LastModified": NOW - timedelta(hours=40), "Size": 10},
    ]
    r = backups._check_photo_backups(_client(objs), "b", NOW)
    assert r["age_hours"] == 40.0
    assert r["is_overdue"] is True


def test_source_unavailable_is_sanitized():
    err = ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ListObjectsV2")
    with patch.object(backups, "_get_gcs_client", side_effect=err):
        status = backups.get_backup_status()
    assert status["database"]["status"] == "unavailable"
    assert "AccessDenied" in status["database"]["detail"]
    assert backups.has_backup_problem(status)


def test_error_text_hides_urls():
    msg = backups._safe_error(RuntimeError("cannot reach https://storage.googleapis.com/secret-bucket/key"))
    assert "googleapis" not in msg


def test_redis_caching_hit_skips_s3(monkeypatch):
    cached = {"database": {"status": "ok"}, "photos": {"status": "ok"}}
    monkeypatch.setattr(backups, "cache_get", lambda k: cached)
    with patch.object(backups, "_get_gcs_client") as get:
        assert backups.get_backup_status() == cached
    get.assert_not_called()


def test_redis_caching_stores_complete_result(monkeypatch):
    stored = {}
    monkeypatch.setattr(backups, "cache_set", lambda k, v, ttl: stored.update({k: v}))
    with patch.object(backups, "_get_gcs_client", return_value=_client([])):
        backups.get_backup_status()
    assert backups.CACHE_KEY in stored
