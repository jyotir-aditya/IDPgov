"""Cloudflare R2 service — PDF upload to Year/Month "folders" (key prefixes).

R2 is S3-compatible, so this uses boto3's S3 client pointed at the R2
endpoint. The bucket must have public read access enabled (R2 dashboard ->
bucket -> Settings -> Public access) so R2_PUBLIC_BASE_URL serves objects
directly with no auth — the register sheet needs a permanent link per row,
and R2 has no per-object "share with this folder" concept like Drive.
"""
from __future__ import annotations

from datetime import datetime

from app.config import settings


def _client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def upload_pdf(local_path: str, filename: str) -> tuple[str, str]:
    """Upload a PDF under a Year/Month key prefix. Returns (object_key, public_url)."""
    now = datetime.now()
    key = f"{now.year}/{now.strftime('%B')}/{filename}"

    client = _client()
    client.upload_file(
        local_path, settings.R2_BUCKET_NAME, key,
        ExtraArgs={"ContentType": "application/pdf"},
    )

    url = f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    return key, url
