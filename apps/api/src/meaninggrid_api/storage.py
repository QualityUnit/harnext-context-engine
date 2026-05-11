"""MinIO / S3 client for blob upload (file ingestion adapter)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aioboto3

from meaninggrid_api.settings import settings

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


async def ensure_bucket() -> None:
    async with s3_client() as client:
        try:
            await client.head_bucket(Bucket=settings.minio_bucket)
        except client.exceptions.ClientError:
            await client.create_bucket(Bucket=settings.minio_bucket)


async def upload_blob(key: str, body: bytes, content_type: str) -> str:
    """Upload bytes to MinIO. Returns the s3:// URI used as mgblobref."""
    async with s3_client() as client:
        await client.put_object(
            Bucket=settings.minio_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
    return f"s3://{settings.minio_bucket}/{key}"
