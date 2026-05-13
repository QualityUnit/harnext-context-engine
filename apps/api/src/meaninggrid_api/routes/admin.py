"""Admin operations — destructive ops gated behind explicit confirmation.

Today: one endpoint, `POST /admin/reset`, which wipes every byte of state the
platform owns (FalkorDB graphs, OLTP rows, MinIO blobs, on-disk FAISS index
files, Kafka topics) and reseeds the default tenant.

Why we touch Kafka too: the worker dedupes on `(tenant_id, event_id)` and the
sinks are idempotent on `event.id`, so a reset that left the existing event
backlog in `events.raw.v1` would just refill everything we just cleared. The
only honest reset is to drop the topic; aiokafka's producer + Redpanda's
`auto.create.topics=true` (the v0 broker default) re-create it on next
publish.

The worker may need a manual restart after this call: an in-flight consumer
loop will throw when its topic disappears under it. The frontend tells the
user.
"""

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import redis.asyncio as aioredis
from aiokafka.admin import AIOKafkaAdminClient
from fastapi import APIRouter, Depends, HTTPException, status
from meaninggrid_shared import Base, Tenant
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from meaninggrid_api.db import SessionLocal, engine, get_session
from meaninggrid_api.settings import settings
from meaninggrid_api.storage import ensure_bucket, s3_client

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
log = logging.getLogger("meaninggrid.api.admin")

_DEFAULT_TENANT_ID = "default"
_DEFAULT_TENANT_NAME = "Default Tenant"

# The literal a caller must send as `confirm`. Belt-and-braces against accidental
# fetches; the frontend types this same string into an input field.
_CONFIRM_PHRASE = "RESET"


class ResetRequest(BaseModel):
    confirm: str = Field(
        description=f"Must equal '{_CONFIRM_PHRASE}' to proceed. Belt-and-braces guard against accidental calls."
    )


class ResetSummary(BaseModel):
    falkordb_graphs: list[str]
    sqlite_rows_before: dict[str, int]
    minio_objects: int
    faiss_files: int
    kafka_topics: list[str]
    tenants_reseeded: list[str]
    notes: list[str]


@router.post("/reset", response_model=ResetSummary)
async def reset_all_data(
    req: ResetRequest,
    _session: Annotated[AsyncSession, Depends(get_session)],
) -> ResetSummary:
    """Wipe every piece of platform state. Requires `{'confirm': 'RESET'}`."""
    if req.confirm != _CONFIRM_PHRASE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"confirm field must equal '{_CONFIRM_PHRASE}'",
        )

    notes: list[str] = []

    # Capture row counts BEFORE we wipe so the response is informative.
    sqlite_rows_before = await _count_sqlite_rows()

    # Run independent wipes in parallel — each one is I/O-bound and they don't
    # share resources. Topic deletion lasts longest; let it overlap.
    falkor_graphs, minio_objects, faiss_files, kafka_topics = await asyncio.gather(
        _drop_all_falkordb_graphs(notes),
        _empty_minio_bucket(notes),
        asyncio.to_thread(_delete_faiss_files),
        _delete_kafka_topics(notes),
    )

    # SQLite reset has to be serialized after the schema-using callers above
    # so we don't drop tables while another coroutine reads them.
    await _wipe_sqlite_schema()

    # Reseed the default tenant so the dashboard works after reset.
    seeded = await _reseed_default_tenant()

    # Make sure the MinIO bucket still exists post-wipe (we only deleted
    # objects, but be defensive against a future code path).
    await ensure_bucket()

    log.warning(
        "ADMIN RESET completed: falkor=%s minio=%d faiss=%d kafka=%s",
        falkor_graphs,
        minio_objects,
        faiss_files,
        kafka_topics,
    )
    notes.append(
        "Restart the worker (`make worker`) — its Kafka consumer loop is in "
        "an undefined state now that `events.raw.v1` was dropped."
    )

    return ResetSummary(
        falkordb_graphs=falkor_graphs,
        sqlite_rows_before=sqlite_rows_before,
        minio_objects=minio_objects,
        faiss_files=faiss_files,
        kafka_topics=kafka_topics,
        tenants_reseeded=seeded,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# FalkorDB — list every graph the instance knows about, delete each.
# ---------------------------------------------------------------------------


async def _drop_all_falkordb_graphs(notes: list[str]) -> list[str]:
    client = aioredis.Redis(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        username=settings.falkordb_username or None,
        password=settings.falkordb_password or None,
        decode_responses=True,
    )
    try:
        graphs: list[str] = await client.execute_command("GRAPH.LIST")
        for name in graphs:
            try:
                await client.execute_command("GRAPH.DELETE", name)
            except Exception as e:
                notes.append(f"FalkorDB: failed to delete graph {name!r}: {e}")
                log.exception("falkor graph delete failed: %s", name)
        return list(graphs)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# SQLite — drop and recreate every table on Base. Counts captured first.
# ---------------------------------------------------------------------------


async def _count_sqlite_rows() -> dict[str, int]:
    counts: dict[str, int] = {}
    async with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            try:
                r = await conn.execute(text(f"SELECT COUNT(*) FROM {table.name}"))
                counts[table.name] = int(r.scalar() or 0)
            except Exception:
                counts[table.name] = 0
    return counts


async def _wipe_sqlite_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def _reseed_default_tenant() -> list[str]:
    async with SessionLocal() as session:
        session.add(Tenant(id=_DEFAULT_TENANT_ID, name=_DEFAULT_TENANT_NAME))
        await session.commit()
    return [_DEFAULT_TENANT_ID]


# ---------------------------------------------------------------------------
# MinIO — list every object in the bucket, delete in batches of 1000.
# ---------------------------------------------------------------------------


async def _empty_minio_bucket(notes: list[str]) -> int:
    deleted = 0
    try:
        async with s3_client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=settings.minio_bucket):
                objs = page.get("Contents") or []
                if not objs:
                    continue
                # delete_objects accepts up to 1000 keys per call; paginator
                # pages are at most 1000 by default so we don't need to chunk.
                resp = await s3.delete_objects(
                    Bucket=settings.minio_bucket,
                    Delete={"Objects": [{"Key": o["Key"]} for o in objs]},
                )
                deleted += len(resp.get("Deleted") or [])
                if resp.get("Errors"):
                    notes.append(
                        f"MinIO: {len(resp['Errors'])} delete errors — first: {resp['Errors'][0]}"
                    )
    except Exception as e:
        notes.append(f"MinIO: bucket empty failed: {e}")
        log.exception("minio empty failed")
    return deleted


# ---------------------------------------------------------------------------
# FAISS — wipe every per-tenant .index file (+ any leftover .index.tmp).
# ---------------------------------------------------------------------------


def _delete_faiss_files() -> int:
    p = Path(settings.faiss_dir)
    if not p.exists():
        return 0
    n = 0
    for f in p.glob("*.index"):
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    for f in p.glob("*.index.tmp"):
        try:
            f.unlink()
        except OSError:
            pass
    return n


# ---------------------------------------------------------------------------
# Kafka — drop every topic matching `events.*`. Redpanda auto-creates on next
# publish, so the producer in the API process doesn't need to be restarted.
# ---------------------------------------------------------------------------


async def _delete_kafka_topics(notes: list[str]) -> list[str]:
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    await admin.start()
    try:
        topic_meta = await admin.list_topics()
        # AIOKafkaAdminClient.list_topics() returns list[str]
        topics: list[str] = [t for t in topic_meta if t.startswith("events.")]
        if not topics:
            return []
        try:
            await admin.delete_topics(topics, timeout_ms=15000)
        except Exception as e:
            notes.append(f"Kafka: delete_topics partial failure: {e}")
            log.exception("kafka delete_topics failed")
        return topics
    finally:
        await admin.close()
