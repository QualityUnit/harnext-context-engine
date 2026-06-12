"""The shared Celery app for ingest background work — scheduler + crawler.

Redis is the broker + result backend. ``beat`` ticks every
``poll_beat_interval_seconds`` and fires ``dispatch_due_polls``, which claims the
sources whose last check is older than their interval and enqueues a per-source
``poll_source`` task. The website-crawl tasks (``crawl_sitemap`` / ``crawl_url``)
register here too, so one worker serves both. Task modules are listed in
``include`` so they import (and register) when the worker boots.

    celery -A meaninggrid_ingest.celery_app worker --loglevel=info
    celery -A meaninggrid_ingest.celery_app beat   --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from meaninggrid_ingest.settings import IngestSettings

_s = IngestSettings()

app = Celery(
    "meaninggrid_ingest",
    broker=_s.redis_url,
    backend=_s.redis_url,
    include=["meaninggrid_ingest.tasks", "meaninggrid_ingest.crawler"],
)
app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # one task at a time → fair rate-limiting
    broker_connection_retry_on_startup=True,
    # A rate-limited poll can be re-queued with a countdown up to a GitHub
    # primary-limit reset (~1h). Redis re-delivers a reserved task once its
    # visibility_timeout (default 1h) elapses, which would run a long-delayed
    # retry twice — push the window well past any reset wait to prevent that.
    broker_transport_options={"visibility_timeout": 43200},  # 12h
    beat_schedule={
        "dispatch-due-polls": {
            "task": "meaninggrid_ingest.tasks.dispatch_due_polls",
            "schedule": float(_s.poll_beat_interval_seconds),
        },
    },
)
