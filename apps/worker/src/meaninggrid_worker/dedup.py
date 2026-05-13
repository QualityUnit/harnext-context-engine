"""Per-tenant idempotency dedup, backed by the OLTP store.

Presence in `ingested_events` (written by the API) means the event was accepted.
For dedup at the worker, we additionally check that no successful sink_outcome
exists yet — that's the "already processed" condition.

See docs/architecture/ingestion-pipeline.md §8 + §9.5.
"""

from meaninggrid_shared import SinkOutcome
from sqlalchemy import select

from meaninggrid_worker.db import SessionLocal


async def already_processed(tenant_id: str, event_id: str, sink_name: str) -> bool:
    """True if this sink already wrote this event successfully."""
    async with SessionLocal() as session:
        row = await session.scalar(
            select(SinkOutcome).where(
                SinkOutcome.tenant_id == tenant_id,
                SinkOutcome.event_id == event_id,
                SinkOutcome.sink_name == sink_name,
                SinkOutcome.status == "success",
            )
        )
        return row is not None
