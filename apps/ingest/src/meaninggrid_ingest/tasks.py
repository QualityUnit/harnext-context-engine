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

from celery import Task
from meaninggrid_shared import CloudEvent, make_engine, make_sessionmaker

from meaninggrid_ingest.celery_app import app
from meaninggrid_ingest.connectors.base import RateLimitedError
from meaninggrid_ingest.kafka import Producer
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings

log = logging.getLogger("ingest.tasks")

# How many times a rate-limited poll re-queues itself before giving up (beat will
# still re-poll the source next interval). Honouring the API's reset time, the
# limit usually clears in one retry.
_POLL_MAX_RETRIES = 5


def _poll_backoff_seconds(retries: int, exc: RateLimitedError) -> float:
    """When to retry a rate-limited poll: honour the API's own reset time if it
    gave one (+1s slack to land past the window), else exponential backoff
    (60s, 120s, … capped at 1h). Mirrors the crawler's ``_backoff_seconds``."""
    if exc.retry_after is not None:
        return exc.retry_after + 1.0
    return float(min(3600, 60 * 2**retries))


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


@app.task(
    bind=True,
    name="meaninggrid_ingest.tasks.poll_source",
    max_retries=_POLL_MAX_RETRIES,
    acks_late=True,
)
def poll_source(self: Task, source_id: str) -> dict:
    """Poll one source. On a provider rate limit, re-queue the task at the API's
    reset time (``RateLimitedError.retry_after``) instead of failing — exponential
    backoff when the API gives no hint."""
    try:
        ingested = asyncio.run(_poll_source(source_id))
    except RateLimitedError as e:
        countdown = _poll_backoff_seconds(self.request.retries, e)
        log.warning(
            "poll_source %s rate-limited (%s); retry %d/%d in %.0fs",
            source_id,
            e,
            self.request.retries + 1,
            _POLL_MAX_RETRIES,
            countdown,
        )
        raise self.retry(exc=e, countdown=countdown) from e
    return {"source_id": source_id, "ingested": ingested}


async def _poll_source(source_id: str) -> int:
    s = IngestSettings()
    engine = make_engine(s.database_url)
    try:
        svc = SourceService(make_sessionmaker(engine), _NoProducer(), s)
        src = await svc.get_source(source_id)
        if src is not None and src.kind == "sitemap":
            # Sitemaps are crawled via the dedicated fan-out (every page, one
            # rate-limited task each) rather than the bounded inline fetch, so a
            # scheduled poll covers the whole site. Hand off and return.
            from meaninggrid_ingest.crawler import crawl_sitemap

            crawl_sitemap.delay(source_id)  # pyright: ignore[reportFunctionMemberAccess]
            return 0
    finally:
        await engine.dispose()

    engine = make_engine(s.database_url)
    producer = Producer(s.kafka_bootstrap_servers)
    await producer.start()
    try:
        svc = SourceService(make_sessionmaker(engine), producer, s)
        return await svc.sync(source_id)
    finally:
        await producer.stop()
        await engine.dispose()
