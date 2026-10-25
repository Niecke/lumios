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


def test_format_content_disposition_ascii():
    assert storage.format_content_disposition("photo.jpg") == 'attachment; filename="photo.jpg"'


def test_format_content_disposition_with_quotes():
    value = storage.format_content_disposition('my "photo".jpg')
    assert value == 'attachment; filename="my photo.jpg"; filename*=UTF-8\'\'my%20%22photo%22.jpg'


def test_format_content_disposition_unicode():
    value = storage.format_content_disposition("schöne küche.jpg")
    assert value.startswith('attachment; filename="schone kuche.jpg"; ')
    assert "filename*=UTF-8''sch%C3%B6ne%20k%C3%BCche.jpg" in value

    value = storage.format_content_disposition("日本語.png")
    assert value.startswith('attachment; filename="download.png"; ')
    assert "filename*=UTF-8''%E6%97%A5%E6%9C%AC%E8%AA%9E.png" in value


def test_format_content_disposition_crlf_and_path_traversal():
    value = storage.format_content_disposition("photo\r\nInjected: true.jpg")
    assert "\r" not in value and "\n" not in value
    assert 'filename="photoInjected: true.jpg"' in value

    assert storage.format_content_disposition("../../etc/passwd") == 'attachment; filename="passwd"'
    assert storage.format_content_disposition("C:\\evil\\photo.jpg") == 'attachment; filename="photo.jpg"'
    assert storage.format_content_disposition("/abs/photo.jpg") == 'attachment; filename="photo.jpg"'
    assert "\x00" not in storage.format_content_disposition("a\x00b.jpg")


@pytest.mark.parametrize("name", ["", "   ", "..", "...", "a/", None])
def test_format_content_disposition_empty_fallback(name):
    assert storage.format_content_disposition(name) == 'attachment; filename="download"'


def test_format_content_disposition_keeps_extension_fallback():
    assert storage.format_content_disposition(".jpg").startswith('attachment; filename="download.jpg"')


def test_get_presigned_download_url_formats_disposition(app, monkeypatch):
    public = MagicMock()
    public.generate_presigned_url.return_value = "https://signed"
    monkeypatch.setattr(storage, "_public_client", public)
    monkeypatch.setattr("services.redis_client.cache_get", lambda k: None)
    monkeypatch.setattr("services.redis_client.cache_set", lambda *a, **kw: None)

    assert storage.get_presigned_download_url("k", 'a "b".jpg') == "https://signed"
    params = public.generate_presigned_url.call_args.kwargs["Params"]
    assert params["ResponseContentDisposition"] == storage.format_content_disposition('a "b".jpg')
