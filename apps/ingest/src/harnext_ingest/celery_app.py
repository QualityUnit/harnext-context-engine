"""The shared Celery app for ingest background work — scheduler + crawler.

Redis is the broker + result backend. ``beat`` ticks every
``poll_beat_interval_seconds`` and fires ``dispatch_due_polls``, which claims the
sources whose last check is older than their interval and enqueues a per-source
``poll_source`` task. The website-crawl tasks (``crawl_sitemap`` / ``crawl_url``)
register here too, so one worker serves both. Task modules are listed in
``include`` so they import (and register) when the worker boots.

    celery -A harnext_ingest.celery_app worker --loglevel=info
    celery -A harnext_ingest.celery_app beat   --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from harnext_ingest.settings import IngestSettings

_s = IngestSettings()

app = Celery(
    "harnext_ingest",
    broker=_s.redis_url,
    backend=_s.redis_url,
    include=["harnext_ingest.tasks", "harnext_ingest.crawler"],
)
app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # one task at a time → fair rate-limiting
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-due-polls": {
            "task": "harnext_ingest.tasks.dispatch_due_polls",
            "schedule": float(_s.poll_beat_interval_seconds),
        },
    },
)
