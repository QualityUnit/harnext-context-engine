"""SQLAlchemy 2.0 ORM models for the CMS control-plane / metadata store.

One SQLite file (WAL) is shared by all apps as the OLTP/metadata store:
    - source registry        (Org, Source)        — written by apps/ingest
    - ingest record          (IngestedEvent)      — written by apps/ingest
    - classifier baselines   (EntityBaseline)     — written by apps/classifier
    - build idempotency      (BuildLedger)        — written by apps/builder
    - raw-conversation log   (ConversationLog)    — written by apps/builder, read by apps/mcp
    - FS snapshot index      (FsSnapshot)         — written by apps/builder, read by apps/mcp
    - MCP request/response   (McpRequest)         — written by apps/mcp, read by apps/ingest
    - harness OAuth + logs   (DeviceAuthRequest, AgentRefreshToken, AgentSession,
                              AgentEvent)          — written/read by apps/ingest

The per-org *context* itself does NOT live here — it lives in each org's
AgentFS store (see apps/builder/agentfs). This DB only holds metadata and the
URL-addressable conversation log.

Schema is dialect-agnostic so a Postgres swap is a connection-string change.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def configure_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Enable WAL + sane defaults for SQLite. No-op for any other dialect.

    WAL is what makes concurrent readers + a single writer tolerable across the
    several CMS processes that share this file.
    """
    if not str(engine.url).startswith("sqlite"):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Accounts + projects (control plane for the dashboard)
# --------------------------------------------------------------------------


class User(Base):
    """A dashboard account. Email/password or Google sign-in.

    ``username`` is a legacy column (kept so existing rows survive); new users
    set it to their email. ``password_hash`` is null for Google-only accounts;
    ``google_sub`` is Google's stable user id (null for password-only accounts).
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_google_sub", "google_sub", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)  # legacy
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    """A project owned by a user. ``project.id`` == the CloudEvent ``mgtenant``
    extension == the boundary for one AgentFS store. No cross-project access.

    OAuth integration state (the access token obtained when the user connects
    GitHub/Slack) lives here; sources created in the project reuse it."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex == org_id
    name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    github_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    slack_team_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slack_team_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slack_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Discord uses an app-level bot token (env); only the connected guild is per-project.
    discord_guild_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discord_guild_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # LiveAgent is self-hosted with a per-install base URL + v3 API key (no OAuth).
    # The key is the secret; the base URL is not, so it can be shown back in the UI.
    liveagent_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    liveagent_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stripe uses a read-only Restricted API key (no OAuth). The key is the secret;
    # the resolved account display name is not, so it's shown back in the UI.
    stripe_account_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)


class Source(Base):
    """A connected data source (a GitHub repo, a Slack channel, …).

    ``config_json`` carries kind-specific config, e.g.
        github:    {"repo": "owner/name"}
        slack:     {"channel_id": "C123", "channel_name": "general"}
        liveagent: {"base_url": "https://x.ladesk.com", "department_id": "abc",
                    "department_name": "Support", "tag_id": "t1", "tag_name": "vip"}
    ``secret`` holds the access token / API key (plaintext in v1; an encrypted
    vault is future work). ``cursor`` is the incremental-sync watermark.
    """

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"))  # project id
    kind: Mapped[str] = mapped_column(String(32))  # github | slack | discord | liveagent
    config_json: Mapped[str] = mapped_column(Text)
    secret: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="active")  # active|paused|error
    cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IngestedEvent(Base):
    """A slim record that an event was normalized + produced to the raw topic.

    Lets the UI list recent activity and join to BuildLedger for build status.
    The full payload lives in Kafka / the event itself, not here.
    """

    __tablename__ = "ingested_events"
    __table_args__ = (Index("ix_ingested_events_org_time", "org_id", "ingest_time"),)

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(255))  # CloudEvent.source
    type: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingest_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# Classifier state (per-entity streaming baselines)
# --------------------------------------------------------------------------


class EntityBaseline(Base):
    """Per ``(org, subject, source_kind)`` rolling stats for anomaly scoring.

    MVP uses Welford mean/variance on the inter-arrival gap (robust-z via
    median/MAD is the planned upgrade, per RQ2). State is plain rows here, not
    Flink keyed state, for the single-node MVP.
    """

    __tablename__ = "entity_baselines"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(32), primary_key=True)

    n: Mapped[int] = mapped_column(Integer, default=0)
    mean_gap: Mapped[float] = mapped_column(Float, default=0.0)
    m2_gap: Mapped[float] = mapped_column(Float, default=0.0)  # Welford sum of squares
    last_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------
# Builder state (idempotency, conversation log, snapshot index)
# --------------------------------------------------------------------------


class BuildLedger(Base):
    """Idempotency + status for one incorporation build.

    ``dedupe_key`` is the CloudEvent ``(source, id)`` for a fast event, or the
    window id for a batch Context Unit (proposal §Idempotency: at-least-once +
    consumer dedupe). A build with status=success short-circuits redelivery.
    """

    __tablename__ = "build_ledger"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(512), primary_key=True)

    build_id: Mapped[str] = mapped_column(String(64))  # uuid4 hex
    lane: Mapped[str] = mapped_column(String(16))  # fast | batch
    status: Mapped[str] = mapped_column(String(16))  # running | success | failed
    snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConversationLog(Base):
    """URL-addressable raw-conversation log: one row per build's transcript.

    The MCP ``context_get_urls`` tool resolves a URL to one of these rows. The
    transcript / files-changed / usage are stored as JSON text.
    """

    __tablename__ = "conversation_log"
    __table_args__ = (Index("ix_conversation_org_time", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex == URL id
    org_id: Mapped[str] = mapped_column(String(64))
    build_id: Mapped[str] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(512))
    lane: Mapped[str] = mapped_column(String(16))

    harness: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    instruction: Mapped[str] = mapped_column(Text)
    transcript_json: Mapped[str] = mapped_column(Text)
    files_changed_json: Mapped[str] = mapped_column(Text)
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str] = mapped_column(String(32))
    snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FsSnapshot(Base):
    """Snapshot index for an org's AgentFS. Only successful builds add a row, so
    ``latest`` for an org == the most recent row — the consistent view the MCP
    read path mounts (monotonic reads; never the live in-progress build)."""

    __tablename__ = "fs_snapshots"
    __table_args__ = (Index("ix_fs_snapshots_org_time", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex == snapshot_id
    org_id: Mapped[str] = mapped_column(String(64))
    build_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # genesis | build
    ref: Mapped[str] = mapped_column(Text)  # backend handle (snapshot path / git sha / branch)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# MCP server activity (request/response log for the dashboard)
# --------------------------------------------------------------------------


class McpRequest(Base):
    """One row per MCP tool call: the request (tool + params) and its response.

    Written by apps/mcp on every invocation — success or error — and read by the
    dashboard's MCP activity view to chart request volume over time and show the
    raw request/response pairs. Tenant-scoped by ``org_id`` like every other
    table; ``params_json`` / ``response_json`` are size-capped at write time.
    """

    __tablename__ = "mcp_requests"
    __table_args__ = (Index("ix_mcp_requests_org_time", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    org_id: Mapped[str] = mapped_column(String(64))
    tool: Mapped[str] = mapped_column(String(64))  # context_research | context_get_urls | …
    params_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # ok | error
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# Agent harness OAuth (device flow) + pushed conversation logs
# --------------------------------------------------------------------------


class DeviceAuthRequest(Base):
    """One OAuth 2.0 Device Authorization Grant (RFC 8628) in flight.

    A CLI harness asks for a ``device_code`` + short ``user_code``; the user
    approves it in the dashboard (binding it to one Project == ``org_id``); the
    CLI polls ``/oauth/token`` until ``status`` flips to ``approved`` and then
    exchanges the ``device_code`` for an access + refresh token.

    Codes are stored in plaintext: they are short-lived (``expires_at``), single
    -use, and the security boundary is the human approval step — consistent with
    the v1 plaintext-secret posture elsewhere. State lives in the DB (not in
    process memory) so polling and approval can land on different workers.
    """

    __tablename__ = "device_auth_requests"
    __table_args__ = (
        Index("ix_device_auth_device_code", "device_code", unique=True),
        Index("ix_device_auth_user_code", "user_code", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    device_code: Mapped[str] = mapped_column(String(64))  # opaque poll key
    user_code: Mapped[str] = mapped_column(String(16))  # short human code (XXXX-XXXX)
    client_id: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(64), default="agent")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|denied
    org_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # set on approval
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # the approver
    interval: Mapped[int] = mapped_column(Integer, default=5)  # min poll gap (seconds)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRefreshToken(Base):
    """A long-lived, rotated refresh token issued to a harness client.

    Only the SHA-256 hash of the opaque token is stored (the token is high
    entropy, so a fast hash with exact-match lookup is correct). Rotation marks
    the old row ``revoked_at`` + ``replaced_by``; presenting an already-revoked
    token is treated as theft and revokes the whole chain (reuse detection)."""

    __tablename__ = "agent_refresh_tokens"
    __table_args__ = (
        Index("ix_agent_refresh_token_hash", "token_hash", unique=True),
        Index("ix_agent_refresh_org", "org_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    token_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex
    org_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(64))  # the approver (audit / display)
    client_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # rotation chain


class AgentSession(Base):
    """One conversation a harness pushed to the engine — the header row.

    Mirrors :class:`ConversationLog`'s spirit (harness/model/usage/stop_reason)
    but is built up incrementally: the client opens it, appends event batches as
    turns complete (see :class:`AgentEvent`), then finalizes it. ``open`` is
    idempotent on ``(org_id, client_session_id)`` so a retried open returns the
    same row rather than duplicating the conversation."""

    __tablename__ = "agent_sessions"
    __table_args__ = (
        Index("ix_agent_sessions_org_time", "org_id", "started_at"),
        Index("ix_agent_sessions_client_session", "org_id", "client_session_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # server uuid4 hex
    org_id: Mapped[str] = mapped_column(String(64))
    client_session_id: Mapped[str] = mapped_column(String(128))  # client-supplied idempotency key
    harness: Mapped[str] = mapped_column(String(32))  # harnext | …
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cwd: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)  # clipped first prompt
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentEvent(Base):
    """One append-only turn in an :class:`AgentSession` — a raw stream-json
    envelope (system/init, assistant, user/tool_result, result) as harnext emits.

    ``seq`` is a client-assigned monotonic ordinal; the unique ``(session_id,
    seq)`` index gives both ordering and idempotency (re-sending a batch is a
    no-op). ``org_id`` is denormalized so the row is tenant-scoped for cleanup
    and direct queries. ``payload_json`` is size-capped at write time."""

    __tablename__ = "agent_events"
    __table_args__ = (Index("ix_agent_events_session_seq", "session_id", "seq", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    session_id: Mapped[str] = mapped_column(String(64))  # → agent_sessions.id
    org_id: Mapped[str] = mapped_column(String(64))  # denormalized for tenant cleanup
    seq: Mapped[int] = mapped_column(Integer)  # client monotonic ordinal
    type: Mapped[str] = mapped_column(String(32))  # system | assistant | user | result
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# Polling scheduler state (Celery beat)
# --------------------------------------------------------------------------


class SourcePollState(Base):
    """Per-source polling watermark for the Celery-beat scheduler.

    A source is *due* when ``now - last_checked_at >= interval_seconds`` (default
    1h). Kept separate from ``Source.last_sync_at`` (which only advances on a
    *successful* sync) so the scheduler tracks each claim/attempt and the cadence
    can be tuned per source. Beat ticks every minute, claims the due sources
    (stamping ``last_checked_at``) and enqueues a poll for each. ``org_id`` mirrors
    the owning source's project so it's cleaned up with the rest of a tenant.
    """

    __tablename__ = "source_poll_state"

    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("sources.id"), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64))  # == project id (tenant cleanup)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
