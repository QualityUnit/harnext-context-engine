"""Celery tasks that crawl a sitemap's pages — the *full-coverage* crawl path.

A large sitemap (thousands of URLs) shouldn't be crawled in one blocking sync.
So the work is split across two tasks, and the whole site is covered — politeness
comes from rate-limiting each request, not from dropping pages:

* :func:`crawl_sitemap` (``source_id``) — the entry point the polling scheduler
  enqueues. It reads + parses the sitemap (recursing the index), selects *every*
  page new since the source's cursor, advances the cursor, and fans out one
  :func:`crawl_url` per page (initial submission staggered by ``countdown``).
* :func:`crawl_url` — fetches a single page and writes its event. It carries a
  Celery ``rate_limit`` (per worker), so however many pages were enqueued, the
  origin sees a bounded request rate; HTTP 429/503 triggers a backoff retry
  rather than a hammer.

Together these are the politeness guarantee: a hard per-worker request ceiling
(rate_limit) + a staggered start (countdown) + backoff on push-back — applied to
the complete page set, not a truncated one.

Both tasks reuse :class:`SitemapConnector` so the discovery/crawl/event logic is
identical to the inline ``fetch`` — only the *execution* differs (and ``fetch``
caps a single call, while this path is uncapped). The async producer + DB are
reached through a small per-worker runtime (one event loop + one started Kafka
producer, reused across tasks).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading

import httpx
from celery import Task
from meaninggrid_shared import init_db, make_engine, make_sessionmaker

from meaninggrid_ingest.celery_app import app
from meaninggrid_ingest.connectors.sitemap import (
    SitemapConnector,
    SitemapEntry,
    TransientCrawlError,
)
from meaninggrid_ingest.kafka import Producer
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings

log = logging.getLogger("ingest.crawler")

_S = IngestSettings()  # import-time: only used for the task rate_limit literal
_STAGGER_CAP = 1000  # cap the per-task countdown growth; rate_limit governs the tail


# -- per-worker async runtime ----------------------------------------------
class _Runtime:
    """A worker-process-local bridge from Celery's synchronous tasks to the
    async producer/DB. One event loop runs on a daemon thread; ``run`` submits a
    coroutine to it and blocks for the result. Built once and reused, so the
    Kafka producer connects a single time per worker — not per task."""

    def __init__(self, service: SourceService, settings: IngestSettings) -> None:
        self.service = service
        self.settings = settings
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="crawler-loop", daemon=True
        )
        self._thread.start()

    def run(self, coro):  # noqa: ANN001, ANN201 — generic coroutine passthrough
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()


_RT: _Runtime | None = None


def _default_runtime() -> _Runtime:
    settings = IngestSettings()
    engine = make_engine(settings.database_url)
    producer = Producer(settings.kafka_bootstrap_servers)
    service = SourceService(make_sessionmaker(engine), producer, settings)
    rt = _Runtime(service, settings)
    rt.run(init_db(engine))  # idempotent — safe if the API already created tables
    rt.run(producer.start())
    return rt


def _runtime() -> _Runtime:
    """The lazily-initialized, cached worker runtime (overridable in tests)."""
    global _RT
    if _RT is None:
        _RT = _default_runtime()
    return _RT


def _backoff_seconds(retries: int, transient: TransientCrawlError | None) -> float:
    """Honour a server's ``Retry-After`` when given, else exponential backoff."""
    if transient is not None and transient.retry_after is not None:
        return transient.retry_after
    return float(min(60, 2 ** (retries + 1)))


# -- crawl one page ---------------------------------------------------------
async def _crawl_one(
    rt: _Runtime, source_id: str, url: str, lastmod: str | None, site: str, org_id: str
) -> bool:
    """Crawl a single URL and persist its event. Returns whether an event was
    written (False = skipped: non-OK status, non-HTML, dead link, or the source
    was deleted mid-crawl). Raises :class:`TransientCrawlError` for 429/503 so the
    task can retry with backoff."""
    connector = SitemapConnector.from_settings(rt.settings)
    entry = SitemapEntry(loc=url, lastmod=lastmod)
    async with httpx.AsyncClient(
        timeout=connector.timeout,
        follow_redirects=True,
        headers={"User-Agent": connector.user_agent},
    ) as client:
        ev = await connector.crawl_page(client, entry, org_id=org_id, site=site)
    if ev is None:
        return False
    return await rt.service.record_event(source_id, ev)


@app.task(
    bind=True,
    name="meaninggrid_ingest.crawler.crawl_url",
    rate_limit=_S.crawl_rate_limit,
    max_retries=3,
    acks_late=True,
)
def crawl_url(
    self: Task, source_id: str, url: str, lastmod: str | None, site: str, org_id: str
) -> dict:
    """Crawl one sitemap page (rate-limited per worker) and emit its event."""
    rt = _runtime()
    try:
        persisted = rt.run(_crawl_one(rt, source_id, url, lastmod, site, org_id))
    except TransientCrawlError as e:
        raise self.retry(exc=e, countdown=_backoff_seconds(self.request.retries, e)) from e
    return {"url": url, "persisted": persisted}


# -- discover + fan out -----------------------------------------------------
@app.task(bind=True, name="meaninggrid_ingest.crawler.crawl_sitemap", acks_late=True)
def crawl_sitemap(self: Task, source_id: str) -> dict:
    """Read the sitemap, advance the cursor, and fan out one rate-limited
    ``crawl_url`` per new/changed page. The scheduler enqueues this per sitemap
    source on its polling interval."""
    rt = _runtime()
    src = rt.run(rt.service.get_source(source_id))
    if src is None or src.kind != "sitemap":
        return {"enqueued": 0, "reason": "source missing or not a sitemap"}

    config = json.loads(src.config_json)
    connector = SitemapConnector.from_settings(rt.settings)
    site = SitemapConnector.site_of(config)
    try:
        # max_pages=None → enqueue *every* new/changed page. The origin is kept
        # safe by crawl_url's per-worker rate limit, not by truncating the list.
        entries, cursor = rt.run(
            connector.discover(config=config, since=src.cursor, max_pages=None)
        )
    except Exception as e:  # noqa: BLE001 — surface the failure on the source row
        rt.run(rt.service._mark_error(source_id, str(e)))
        raise

    delay = rt.settings.crawl_delay_seconds
    for i, entry in enumerate(entries):
        crawl_url.apply_async(  # pyright: ignore[reportFunctionMemberAccess] — celery Task
            (source_id, entry.loc, entry.lastmod, site, src.org_id),
            # Stagger the initial submission (capped); crawl_url's rate_limit is
            # what governs the sustained pace across the whole fan-out.
            countdown=min(i, _STAGGER_CAP) * delay,
        )
    # Advance the watermark up front so a concurrent poll won't re-discover these.
    rt.run(rt.service.set_cursor(source_id, cursor))
    log.info("crawl_sitemap %s: enqueued %d pages (cursor=%s)", source_id, len(entries), cursor)
    return {"enqueued": len(entries), "cursor": cursor}
