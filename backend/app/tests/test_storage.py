import os
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from services import storage


def _not_found():
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")


@pytest.fixture
def fake_client(app, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(storage, "_client", client)
    monkeypatch.setattr(storage, "_bucket_verified", False)
    return client


def test_default_s3_endpoint(app, monkeypatch):
    env = {k: v for k, v in os.environ.items() if k != "S3_ENDPOINT_URL"}
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import config; print(config.S3_ENDPOINT_URL)", app_dir],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "http://s3:7070"


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


def test_ensure_bucket_is_cached_after_first_call(fake_client, monkeypatch):
    monkeypatch.setattr(storage, "DEBUG", False)

    storage.ensure_bucket()
    storage.ensure_bucket()

    fake_client.head_bucket.assert_called_once()


def test_set_bucket_cors_swallows_errors(fake_client):
    fake_client.put_bucket_cors.side_effect = RuntimeError("not supported")

    storage._set_bucket_cors_for_dev()  # must not raise
