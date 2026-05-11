"""Ingest endpoints — POST /ingest (JSON) and POST /ingest/file (multipart).

See docs/architecture/ingestion-pipeline.md §5 and §6.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from meaninggrid_api.auth import get_tenant_id
from meaninggrid_api.db import get_session
from meaninggrid_api.kafka import publish_event
from meaninggrid_api.storage import upload_blob
from meaninggrid_shared import CloudEvent, IngestedEvent

router = APIRouter(prefix="/api/v1", tags=["ingest"])


class IngestRequest(BaseModel):
    source: str
    type: str
    subject: str
    time: datetime | None = None
    id: str | None = None
    data: dict[str, Any] | None = None


class IngestResponse(BaseModel):
    id: str
    accepted_at: datetime


def _derive_id(req: IngestRequest, tenant_id: str) -> str:
    """Per §8: prefer caller-supplied id; fall back to a deterministic-ish derivation."""
    if req.id:
        return f"{req.source}:{req.id}"
    return f"{req.source}:{req.subject}:{datetime.now(UTC).isoformat()}"


async def _record_and_publish(
    session: AsyncSession, event: CloudEvent
) -> None:
    session.add(
        IngestedEvent(
            tenant_id=event.mgtenant,
            event_id=event.id,
            source=event.source,
            type=event.type,
            subject=event.subject,
            event_time=event.time,
            ingest_time=event.mgingesttime or datetime.now(UTC),
            blob_ref=event.mgblobref,
            envelope_json=event.model_dump_json(),
        )
    )
    await session.commit()
    await publish_event(event)


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED, response_model=IngestResponse)
async def ingest(
    req: IngestRequest,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestResponse:
    accepted_at = datetime.now(UTC)
    event = CloudEvent(
        id=_derive_id(req, tenant_id),
        source=req.source,
        type=req.type,
        subject=req.subject,
        time=req.time or accepted_at,
        data=req.data,
        mgtenant=tenant_id,
        mgingesttime=accepted_at,
    )
    await _record_and_publish(session, event)
    return IngestResponse(id=event.id, accepted_at=accepted_at)


@router.post("/ingest/file", status_code=status.HTTP_202_ACCEPTED, response_model=IngestResponse)
async def ingest_file(
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
    file: UploadFile = File(...),
    source: str = Form("file"),
    subject: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
) -> IngestResponse:
    """Multipart upload. Streams the file to MinIO; payload becomes a metadata-only envelope
    with mgblobref pointing at the blob. Text extraction happens in the worker (§5.2).
    """
    if file.filename is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "filename required")

    body = await file.read()
    file_id = uuid.uuid4().hex
    key = f"{tenant_id}/{datetime.now(UTC):%Y/%m/%d}/{file_id}-{file.filename}"
    blob_ref = await upload_blob(key, body, file.content_type or "application/octet-stream")

    extra_meta: dict[str, Any] = {}
    if metadata:
        try:
            extra_meta = json.loads(metadata)
        except json.JSONDecodeError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"metadata not valid JSON: {e}") from e

    accepted_at = datetime.now(UTC)
    event = CloudEvent(
        id=f"file:{file_id}",
        source=source,
        type="file.uploaded",
        subject=subject or f"doc:{file_id}",
        time=accepted_at,
        data={
            "filename": file.filename,
            "mime": file.content_type,
            "size_bytes": len(body),
            **extra_meta,
        },
        mgtenant=tenant_id,
        mgingesttime=accepted_at,
        mgblobref=blob_ref,
    )
    await _record_and_publish(session, event)
    return IngestResponse(id=event.id, accepted_at=accepted_at)
