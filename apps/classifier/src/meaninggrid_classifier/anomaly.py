"""Per-entity streaming anomaly score (RQ2 MVP).

Keyed by ``(org, subject, source_kind)``. Tracks the inter-arrival gap with
Welford mean/variance and scores a *burst* — a gap much shorter than the
entity's baseline — as anomalous. Robust-z (median/MAD) + HBOS are the planned
upgrades; this is the simplest per-entity, label-free detector that routes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from meaninggrid_shared import CloudEvent, EntityBaseline
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meaninggrid_classifier.settings import ClassifierSettings


def _epoch(dt: datetime) -> float:
    """Seconds since epoch, treating naive datetimes (SQLite round-trips drop
    tzinfo) as UTC so aware/naive subtraction never raises."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


class AnomalyScorer:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], settings: ClassifierSettings
    ) -> None:
        self.sm = sessionmaker
        self.min_samples = settings.anomaly_min_samples

    async def score(self, event: CloudEvent) -> float:
        kind = event.source.split(":", 1)[0]
        async with self.sm() as s:
            row = await s.get(EntityBaseline, (event.mgtenant, event.subject, kind))
            if row is None:
                s.add(
                    EntityBaseline(
                        org_id=event.mgtenant,
                        subject=event.subject,
                        source_kind=kind,
                        n=0,
                        mean_gap=0.0,
                        m2_gap=0.0,
                        last_event_time=event.time,
                    )
                )
                await s.commit()
                return 0.0

            score = 0.0
            if row.last_event_time is not None:
                gap = max(0.0, _epoch(event.time) - _epoch(row.last_event_time))
                # score against the established baseline BEFORE updating it
                if row.n >= self.min_samples:
                    std = (row.m2_gap / row.n) ** 0.5
                    if std > 1e-9:
                        z = (gap - row.mean_gap) / std
                        if z < 0:  # burst: gap shorter than usual for this entity
                            score = -z
                # Welford update
                row.n += 1
                delta = gap - row.mean_gap
                row.mean_gap += delta / row.n
                row.m2_gap += delta * (gap - row.mean_gap)
            row.last_event_time = event.time
            await s.commit()
            return score
