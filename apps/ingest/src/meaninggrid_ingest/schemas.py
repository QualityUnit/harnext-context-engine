"""API request/response models (secrets/tokens never leave the server)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str


class UserOut(BaseModel):
    id: str
    username: str
    created_at: datetime


class ProjectCreate(BaseModel):
    owner_id: str
    name: str


class ProjectOut(BaseModel):
    id: str
    name: str
    owner_id: str
    created_at: datetime
    github_login: str | None
    github_connected: bool
    slack_team_name: str | None
    slack_connected: bool


class SourceCreate(BaseModel):
    project_id: str
    kind: str  # github | slack
    config: dict[str, Any]
    secret: str | None = None  # optional manual token; else the project's OAuth token


class SourceOut(BaseModel):
    id: str
    org_id: str  # == project id
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


class RepoOut(BaseModel):
    full_name: str


class ChannelOut(BaseModel):
    id: str
    name: str
