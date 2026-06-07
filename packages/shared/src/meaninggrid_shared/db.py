"""SQLAlchemy 2.0 ORM models for the CMS control-plane / metadata store.

One SQLite file (WAL) is shared by all apps as the OLTP/metadata store:
    - source registry        (Org, Source)        — written by apps/ingest
    - ingest record          (IngestedEvent)      — written by apps/ingest
    - classifier baselines   (EntityBaseline)     — written by apps/classifier
    - build idempotency      (BuildLedger)        — written by apps/builder
    - raw-conversation log   (ConversationLog)    — written by apps/builder, read by apps/mcp
    - FS snapshot index      (FsSnapshot)         — written by apps/builder, read by apps/mcp

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
# Source registry (control plane for the web UI + connectors)
# --------------------------------------------------------------------------


class Org(Base):
    """A tenant. ``org.id`` == the CloudEvent ``mgtenant`` extension == the
    boundary for one AgentFS store. No cross-org access, anywhere."""

    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Source(Base):
    """A connected data source (a GitHub repo, a Slack channel, …).

    ``config_json`` carries kind-specific config, e.g.
        github: {"repo": "owner/name"}
        slack:  {"channel_id": "C123", "channel_name": "general"}
    ``secret`` holds the access token (plaintext in v1; an encrypted vault is
    future work). ``cursor`` is the incremental-sync watermark.
    """

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("orgs.id"))
    kind: Mapped[str] = mapped_column(String(32))  # github | slack
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
