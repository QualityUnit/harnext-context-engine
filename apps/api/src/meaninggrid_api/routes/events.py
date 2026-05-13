"""Read endpoints for ingested events and per-sink processing status."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from meaninggrid_shared import IngestedEvent, SinkOutcome
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from meaninggrid_api.auth import get_tenant_id
from meaninggrid_api.db import get_session

router = APIRouter(prefix="/api/v1/events", tags=["events"])


class EventSummary(BaseModel):
    id: str
    source: str
    type: str
    subject: str
    event_time: datetime
    ingest_time: datetime
    has_blob: bool


class SinkStatus(BaseModel):
    sink: str
    status: str
    attempts: int
    last_error: str | None
    completed_at: datetime | None


class EventDetail(EventSummary):
    envelope_json: str
    sinks: list[SinkStatus]


@router.get("", response_model=list[EventSummary])
async def list_events(
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[EventSummary]:
    stmt = (
        select(IngestedEvent)
        .where(IngestedEvent.tenant_id == tenant_id)
        .order_by(desc(IngestedEvent.ingest_time))
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        EventSummary(
            id=r.event_id,
            source=r.source,
            type=r.type,
            subject=r.subject,
            event_time=r.event_time,
            ingest_time=r.ingest_time,
            has_blob=r.blob_ref is not None,
        )
        for r in rows
    ]


@router.get("/{event_id:path}", response_model=EventDetail)
async def get_event(
    event_id: str,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventDetail:
    row = await session.get(IngestedEvent, (tenant_id, event_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")

    sink_rows = (
        await session.execute(
            select(SinkOutcome).where(
                SinkOutcome.tenant_id == tenant_id,
                SinkOutcome.event_id == event_id,
            )
        )
    ).scalars().all()

    return EventDetail(
        id=row.event_id,
        source=row.source,
        type=row.type,
        subject=row.subject,
        event_time=row.event_time,
        ingest_time=row.ingest_time,
        has_blob=row.blob_ref is not None,
        envelope_json=row.envelope_json,
        sinks=[
            SinkStatus(
                sink=s.sink_name,
                status=s.status,
                attempts=s.attempts,
                last_error=s.last_error,
                completed_at=s.completed_at,
            )
            for s in sink_rows
        ],
    )
