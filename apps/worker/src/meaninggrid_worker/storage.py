"""MinIO blob fetch for the worker (file-event extraction)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import aioboto3

from meaninggrid_worker.settings import settings

_session = aioboto3.Session()


@asynccontextmanager
async def s3_client() -> AsyncIterator:
    async with _session.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name="us-east-1",
    ) as client:
        yield client


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """s3://bucket/key/path → (bucket, key/path)"""
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"not an s3:// URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


async def fetch_blob(uri: str) -> bytes:
    bucket, key = parse_s3_uri(uri)
    async with s3_client() as client:
        resp = await client.get_object(Bucket=bucket, Key=key)
        async with resp["Body"] as stream:
            return await stream.read()
