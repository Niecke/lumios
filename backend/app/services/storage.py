"""
S3-compatible object storage service.
Uses boto3 — works with MinIO locally and any S3-compatible backend in production.
"""

import hashlib
import logging
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from config import (
    S3_ENDPOINT_URL,
    S3_PUBLIC_ENDPOINT_URL,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
    S3_BUCKET,
)


def _make_client(endpoint_url: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=os.getenv("S3_REGION", "auto"),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


_client = _make_client(S3_ENDPOINT_URL)
_public_client = _make_client(S3_PUBLIC_ENDPOINT_URL)


_bucket_verified = False


def ensure_bucket() -> None:
    global _bucket_verified
    if _bucket_verified:
        return
    logger = logging.getLogger(__name__)
    try:
        _client.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        logger.warning("Bucket %s not found, creating it", S3_BUCKET)
        _client.create_bucket(Bucket=S3_BUCKET)
    _bucket_verified = True


def upload_fileobj(file_obj, key: str, content_type: str) -> None:
    _client.upload_fileobj(
        file_obj,
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    from services.redis_client import cache_get, cache_set

    cache_key = f"presigned:{hashlib.sha256(key.encode()).hexdigest()[:16]}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    url = _public_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )
    cache_set(cache_key, url, ttl=min(expires_in // 2, 1800))
    return url


def get_presigned_download_url(key: str, filename: str, expires_in: int = 3600) -> str:
    """Presigned URL that sets Content-Disposition: attachment so the browser
    saves the file directly instead of opening it in a new tab."""
    from services.redis_client import cache_get, cache_set

    raw = f"{key}:{filename}"
    cache_key = f"presigned_dl:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    url = _public_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=expires_in,
    )
    cache_set(cache_key, url, ttl=min(expires_in // 2, 1800))
    return url


def delete_object(key: str) -> None:
    _client.delete_object(Bucket=S3_BUCKET, Key=key)


def get_object_bytes(key: str) -> bytes:
    """Download an object from GCS and return its raw bytes."""
    response = _client.get_object(Bucket=S3_BUCKET, Key=key)
    return response["Body"].read()
