"""Thin wrapper around the S3 API for R2. The only module that talks to object storage."""

from functools import cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings

PRESIGNED_PUT_EXPIRY = 15 * 60  # seconds


@cache
def _client():
    """One client per process (boto3 clients are thread-safe and costly to build)."""
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name=settings.R2_REGION,
        config=Config(signature_version="s3v4"),
    )


def presigned_put_url(key: str, content_type: str) -> str:
    """URL for a single PUT of `key`; the Content-Type header is part of the signature."""
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=PRESIGNED_PUT_EXPIRY,
        HttpMethod="PUT",
    )


def head_object(key: str) -> dict | None:
    """Object metadata, or None if it does not exist."""
    try:
        return _client().head_object(Bucket=settings.R2_BUCKET, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise


def get_object_bytes(key: str) -> bytes:
    return _client().get_object(Bucket=settings.R2_BUCKET, Key=key)["Body"].read()


def delete_object(key: str) -> None:
    """Delete `key`; deleting a missing object is not an error."""
    _client().delete_object(Bucket=settings.R2_BUCKET, Key=key)


def public_url(key: str) -> str | None:
    base = settings.R2_PUBLIC_URL.rstrip("/")
    return f"{base}/{key}" if base else None
