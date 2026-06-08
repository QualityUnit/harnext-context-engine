"""The shared Celery application for ingest background work.

This is the single ``Celery`` instance every ingest task registers on — the
distributed-crawl tasks in :mod:`meaninggrid_ingest.crawler` and the source
polling scheduler. Run a worker with::

    celery -A meaninggrid_ingest.celery_app worker --loglevel=info

Task modules are listed in ``include`` so they import (and register) when the
worker boots. Broker/back-end come from :class:`IngestSettings` (Redis default).
"""

from __future__ import annotations

from celery import Celery

from meaninggrid_ingest.settings import IngestSettings

_settings = IngestSettings()

app = Celery(
    "meaninggrid_ingest",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["meaninggrid_ingest.crawler"],
)

app.conf.update(
    task_acks_late=True,  # re-deliver a crawl if a worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # one task at a time → fair rate-limiting
    task_track_started=True,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
)
