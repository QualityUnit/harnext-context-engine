"""Celery tasks for source polling.

``dispatch_due_polls`` (beat, every minute) claims the due sources and fans out a
``poll_source`` task per source. ``poll_source`` runs the same async path as the
manual ``POST /sources/{id}/sync`` (``connector.fetch`` → Kafka → cursor). Both
bridge the async service into Celery's sync worker with ``asyncio.run`` — each
task gets its own engine (and, for polling, its own Kafka producer) and tears it
down when done.
"""

from __future__ import annotations

import asyncio
import logging

from meaninggrid_shared import CloudEvent, make_engine, make_sessionmaker

from meaninggrid_ingest.celery_app import app
from meaninggrid_ingest.kafka import Producer
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings

log = logging.getLogger("ingest.tasks")


class _NoProducer:
    """Dispatch only reads/claims rows — it never produces to Kafka."""

    async def send_event(self, topic: str, event: CloudEvent) -> None:  # pragma: no cover
        raise RuntimeError("dispatch must not produce events")


@app.task(name="meaninggrid_ingest.tasks.dispatch_due_polls")
def dispatch_due_polls() -> dict:
    return asyncio.run(_dispatch_due_polls())


async def _dispatch_due_polls() -> dict:
    s = IngestSettings()
    engine = make_engine(s.database_url)
    try:
        svc = SourceService(make_sessionmaker(engine), _NoProducer(), s)
        due = await svc.claim_due_polls()
    finally:
        await engine.dispose()
    for source_id in due:
        poll_source.delay(source_id)
    if due:
        log.info("dispatched %d due source poll(s)", len(due))
    return {"dispatched": len(due)}


@app.task(name="meaninggrid_ingest.tasks.poll_source")
def poll_source(source_id: str) -> dict:
    return {"source_id": source_id, "ingested": asyncio.run(_poll_source(source_id))}


async def _poll_source(source_id: str) -> int:
    s = IngestSettings()
    engine = make_engine(s.database_url)
    producer = Producer(s.kafka_bootstrap_servers)
    await producer.start()
    try:
        svc = SourceService(make_sessionmaker(engine), producer, s)
        return await svc.sync(source_id)
    finally:
        await producer.stop()
        await engine.dispose()
