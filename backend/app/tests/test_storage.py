from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

import config
from services import storage


def _not_found():
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")


@pytest.fixture
def fake_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(storage, "_client", client)
    monkeypatch.setattr(storage, "_bucket_verified", False)
    return client


def test_default_s3_endpoint(monkeypatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    import importlib

    try:
        reloaded = importlib.reload(config)
        assert reloaded.S3_ENDPOINT_URL == "http://s3:7070"
    finally:
        importlib.reload(config)


def test_ensure_bucket_creates_missing_bucket_and_sets_cors(fake_client, monkeypatch):
    monkeypatch.setattr(storage, "DEBUG", True)
    fake_client.head_bucket.side_effect = _not_found()

    storage.ensure_bucket()

    fake_client.create_bucket.assert_called_once_with(Bucket=storage.S3_BUCKET)
    fake_client.put_bucket_cors.assert_called_once()


def test_ensure_bucket_skips_create_and_cors_when_not_debug(fake_client, monkeypatch):
    monkeypatch.setattr(storage, "DEBUG", False)

    storage.ensure_bucket()

    fake_client.create_bucket.assert_not_called()
    fake_client.put_bucket_cors.assert_not_called()


def test_set_bucket_cors_swallows_errors(fake_client):
    fake_client.put_bucket_cors.side_effect = RuntimeError("not supported")

    storage._set_bucket_cors_for_dev()  # must not raise
