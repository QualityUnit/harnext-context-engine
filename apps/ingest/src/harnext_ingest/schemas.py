"""API request/response models (secrets/tokens never leave the server)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class BetaSignupIn(BaseModel):
    email: str
    name: str | None = None


class BetaSignupOut(BaseModel):
    ok: bool
    status: str  # Mailchimp member status, e.g. "subscribed" / "pending"


class UserOut(BaseModel):
    id: str
    email: str | None
    name: str | None
    avatar_url: str | None
    created_at: datetime


class AuthOut(BaseModel):
    token: str
    user: UserOut


class ProjectCreate(BaseModel):
    name: str


class ProjectRename(BaseModel):
    name: str


class McpInfoOut(BaseModel):
    endpoint: str
    token: str


class AnalyticsOut(BaseModel):
    events_per_day: list[int]
    total_events: int
    total_builds: int
    context_bytes: int
    sources_live: int
    days: int


class ProjectOut(BaseModel):
    id: str
    name: str
    owner_id: str
    created_at: datetime
    github_login: str | None
    github_connected: bool
    slack_team_name: str | None
    slack_connected: bool
    discord_guild_name: str | None
    discord_connected: bool
    liveagent_base_url: str | None
    liveagent_connected: bool
    stripe_account_name: str | None
    stripe_connected: bool


class SourceCreate(BaseModel):
    project_id: str
    kind: str  # github | slack | discord | liveagent | stripe | youtube
    config: dict[str, Any]
    secret: str | None = None  # optional manual token; else the project's OAuth token


class LiveAgentConnectIn(BaseModel):
    base_url: str
    api_key: str


class StripeConnectIn(BaseModel):
    api_key: str


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
    event_count: int = 0


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


class McpRequestOut(BaseModel):
    id: str
    tool: str
    params: Any
    status: str
    response: Any | None
    error: str | None
    duration_ms: int
    created_at: datetime


class McpStatsOut(BaseModel):
    requests_per_day: list[int]
    total_requests: int
    total_errors: int
    avg_duration_ms: int
    by_tool: dict[str, int]
    days: int


class FsListOut(BaseModel):
    """A flat listing of the org context filesystem (the agent's working files)."""

    files: list[str]
    snapshot_id: str | None  # the latest committed snapshot this listing reflects


class FsFileOut(BaseModel):
    path: str
    content: str
    size: int  # bytes of the (UTF-8) content


class FsWriteIn(BaseModel):
    path: str
    content: str


class FsWriteOut(BaseModel):
    path: str
    size: int
    snapshot_id: str  # the edit snapshot created by this write


# -- Agent harness OAuth (device flow) ------------------------------------


class DeviceCodeOut(BaseModel):
    """RFC 8628 device-authorization response."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class TokenOut(BaseModel):
    """RFC 6749 access-token response (device + refresh grants)."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str
    scope: str = "agent"


class DeviceLookupOut(BaseModel):
    """What the dashboard approve page shows before the user picks a project."""

    user_code: str
    client_id: str
    status: str
    expires_at: datetime


class DeviceApproveIn(BaseModel):
    user_code: str
    project_id: str


class DeviceDenyIn(BaseModel):
    user_code: str


# -- Pushed agent conversations -------------------------------------------


class AgentSessionOpenIn(BaseModel):
    client_session_id: str
    harness: str
    model: str | None = None
    cwd: str | None = None
    title: str | None = None


class AgentEventIn(BaseModel):
    seq: int
    type: str
    payload: Any


class AgentEventBatchIn(BaseModel):
    events: list[AgentEventIn]


class AgentEventBatchOut(BaseModel):
    session_id: str
    accepted: int
    duplicates: int
    max_seq: int | None


class AgentSessionFinalizeIn(BaseModel):
    stop_reason: str | None = None
    usage: dict[str, Any] | None = None


class AgentSessionOut(BaseModel):
    id: str
    org_id: str
    client_session_id: str
    harness: str
    model: str | None
    cwd: str | None
    title: str | None
    status: str
    stop_reason: str | None
    usage: Any | None
    event_count: int
    started_at: datetime
    ended_at: datetime | None


class AgentEventOut(BaseModel):
    seq: int
    type: str
    payload: Any
    created_at: datetime


class AgentSessionDetailOut(BaseModel):
    session: AgentSessionOut
    events: list[AgentEventOut]


class RepoOut(BaseModel):
    full_name: str


class ChannelOut(BaseModel):
    id: str
    name: str


class DepartmentOut(BaseModel):
    id: str
    name: str


class TagOut(BaseModel):
    id: str
    name: str
