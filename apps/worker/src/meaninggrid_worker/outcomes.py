"""Per-sink outcome tracking — written to the OLTP store after each sink runs.

Drives /api/v1/events/{id} sink status display in the dashboard.
"""

from datetime import UTC, datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from meaninggrid_worker.db import SessionLocal
from meaninggrid_shared import SinkOutcome


async def record_outcome(
    *,
    tenant_id: str,
    event_id: str,
    sink_name: str,
    status: str,
    error: str | None,
    attempts: int,
) -> None:
    """Upsert a (tenant, event, sink) outcome row."""
    async with SessionLocal() as session:
        stmt = sqlite_insert(SinkOutcome).values(
            tenant_id=tenant_id,
            event_id=event_id,
            sink_name=sink_name,
            status=status,
            attempts=attempts,
            last_error=error,
            completed_at=datetime.now(UTC) if status in {"success", "failed"} else None,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "event_id", "sink_name"],
            set_={
                "status": stmt.excluded.status,
                "attempts": stmt.excluded.attempts,
                "last_error": stmt.excluded.last_error,
                "completed_at": stmt.excluded.completed_at,
            },
        )
        await session.execute(stmt)
        await session.commit()
