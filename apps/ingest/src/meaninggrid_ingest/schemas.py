"""API request/response models (secrets never leave the server)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class OrgCreate(BaseModel):
    id: str
    name: str | None = None


class OrgOut(BaseModel):
    id: str
    name: str
    created_at: datetime


class SourceCreate(BaseModel):
    org_id: str
    org_name: str | None = None
    kind: str  # github | slack
    config: dict[str, Any]
    secret: str | None = None


class SourceOut(BaseModel):
    id: str
    org_id: str
    kind: str
    config: dict[str, Any]
    status: str
    cursor: str | None
    last_sync_at: datetime | None
    last_error: str | None
    created_at: datetime
    has_secret: bool


class SyncOut(BaseModel):
    source_id: str
    ingested: int


class EventOut(BaseModel):
    event_id: str
    source: str
    type: str
    subject: str
    event_time: datetime
    ingest_time: datetime


class BuildOut(BaseModel):
    org_id: str
    dedupe_key: str
    lane: str
    status: str
    snapshot_id: str | None
    attempts: int
    last_error: str | None
    updated_at: datetime
