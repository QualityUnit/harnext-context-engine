"""SQLAlchemy 2.0 ORM models for the OLTP store.

See docs/architecture/ingestion-pipeline.md §8a for the table list and rationale.
v0 driver is SQLite via aiosqlite; schema is dialect-agnostic so Postgres swap
is a connection-string change.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def configure_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Enable WAL + sane defaults for SQLite. No-op for any other dialect.

    WAL is what makes concurrent readers + a single writer tolerable. Without
    it, every reader blocks the writer and vice versa.
    """
    if not str(engine.url).startswith("sqlite"):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestedEvent(Base):
    """Source-of-truth record that an event was accepted by the Ingest API.

    Created by the Ingest API on /ingest. The worker checks this table for
    dedup (presence = seen). Holds the full envelope for replay/debug.

    Index on (tenant_id, ingest_time DESC) lets the dashboard's /events list
    query short-circuit at LIMIT N instead of sorting the whole table — the
    difference between ~7 ms and ~3.7 s at 93k rows.
    """

    __tablename__ = "ingested_events"
    __table_args__ = (
        Index(
            "ix_ingested_events_tenant_time",
            "tenant_id",
            "ingest_time",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id"), primary_key=True
    )
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    source: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(128))
    subject: Mapped[str] = mapped_column(String(255))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingest_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    blob_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    envelope_json: Mapped[str] = mapped_column(Text)


class SinkOutcome(Base):
    """Per-(event, sink) status. Populated by the worker.

    See docs/architecture/ingestion-pipeline.md §9.6 for failure semantics.
    """

    __tablename__ = "sink_outcomes"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    sink_name: Mapped[str] = mapped_column(String(64), primary_key=True)

    status: Mapped[str] = mapped_column(String(32))  # pending | success | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VectorDocument(Base):
    """Sidecar metadata for the per-tenant on-disk FAISS index.

    Populated by FaissSink (apps/worker/sinks/faiss.py); read by
    /api/v1/documents/vectors. Vectors themselves live in the binary FAISS
    file at `{faiss_dir}/{tenant_id}.index`; `faiss_id` is the row index
    inside that file. See docs/architecture/ingestion-pipeline.md §9.9.
    """

    __tablename__ = "vector_documents"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    faiss_id: Mapped[int] = mapped_column(Integer)
    dim: Mapped[int] = mapped_column(Integer)

    source: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(128))
    subject: Mapped[str] = mapped_column(String(255))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingest_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    text_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
