"""Source registry + sync service: registers sources and pulls their activity
into the raw Kafka topic, recording a slim IngestedEvent per event."""

from __future__ import annotations

import json
import uuid

from meaninggrid_shared import (
    RAW_EVENTS_TOPIC,
    BuildLedger,
    IngestedEvent,
    Org,
    Source,
    utcnow,
)
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meaninggrid_ingest.connectors import get_connector
from meaninggrid_ingest.kafka import Producer
from meaninggrid_ingest.settings import IngestSettings


class SourceService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: Producer,
        settings: IngestSettings,
    ) -> None:
        self.sm = sessionmaker
        self.producer = producer
        self.s = settings

    async def ensure_org(self, org_id: str, name: str | None = None) -> Org:
        async with self.sm() as s:
            org = await s.get(Org, org_id)
            if org is None:
                org = Org(id=org_id, name=name or org_id)
                s.add(org)
                await s.commit()
                await s.refresh(org)
            return org

    async def list_orgs(self) -> list[Org]:
        async with self.sm() as s:
            return list((await s.execute(select(Org).order_by(Org.created_at))).scalars())

    async def create_source(
        self, org_id: str, kind: str, config: dict, secret: str | None
    ) -> Source:
        await self.ensure_org(org_id)
        src = Source(
            id=uuid.uuid4().hex,
            org_id=org_id,
            kind=kind,
            config_json=json.dumps(config),
            secret=secret,
            status="active",
        )
        async with self.sm() as s:
            s.add(src)
            await s.commit()
            await s.refresh(src)
        return src

    async def list_sources(self, org_id: str | None) -> list[Source]:
        async with self.sm() as s:
            q = select(Source).order_by(Source.created_at)
            if org_id:
                q = q.where(Source.org_id == org_id)
            return list((await s.execute(q)).scalars())

    async def get_source(self, source_id: str) -> Source | None:
        async with self.sm() as s:
            return await s.get(Source, source_id)

    async def delete_source(self, source_id: str) -> bool:
        async with self.sm() as s:
            src = await s.get(Source, source_id)
            if src is None:
                return False
            await s.delete(src)
            await s.commit()
            return True

    async def sync(self, source_id: str) -> int:
        """Pull new activity, produce to the raw topic, advance the cursor.
        Returns the number of events ingested. Records last_error on failure."""
        src = await self.get_source(source_id)
        if src is None:
            raise KeyError(source_id)

        connector = get_connector(src.kind, github_per_page=self.s.github_per_page)
        try:
            result = await connector.fetch(
                org_id=src.org_id,
                config=json.loads(src.config_json),
                secret=src.secret,
                since=src.cursor,
            )
            for ev in result.events:
                await self.producer.send_event(RAW_EVENTS_TOPIC, ev)
                await self._record_ingested(src, ev)
            await self._mark_synced(source_id, result.cursor)
            return len(result.events)
        except Exception as e:
            await self._mark_error(source_id, str(e))
            raise

    async def _record_ingested(self, src: Source, ev) -> None:
        async with self.sm() as s:
            await s.merge(
                IngestedEvent(
                    org_id=src.org_id,
                    event_id=ev.id,
                    source_id=src.id,
                    source=ev.source,
                    type=ev.type,
                    subject=ev.subject,
                    event_time=ev.time,
                    ingest_time=utcnow(),
                )
            )
            await s.commit()

    async def _mark_synced(self, source_id: str, cursor: str | None) -> None:
        async with self.sm() as s:
            src = await s.get(Source, source_id)
            if src:
                src.cursor = cursor
                src.last_sync_at = utcnow()
                src.status = "active"
                src.last_error = None
                await s.commit()

    async def _mark_error(self, source_id: str, error: str) -> None:
        async with self.sm() as s:
            src = await s.get(Source, source_id)
            if src:
                src.status = "error"
                src.last_error = error[:2000]
                await s.commit()

    async def list_events(self, org_id: str, limit: int = 50) -> list[IngestedEvent]:
        async with self.sm() as s:
            q = (
                select(IngestedEvent)
                .where(IngestedEvent.org_id == org_id)
                .order_by(desc(IngestedEvent.ingest_time))
                .limit(limit)
            )
            return list((await s.execute(q)).scalars())

    async def list_builds(self, org_id: str, limit: int = 50) -> list[BuildLedger]:
        async with self.sm() as s:
            q = (
                select(BuildLedger)
                .where(BuildLedger.org_id == org_id)
                .order_by(desc(BuildLedger.updated_at))
                .limit(limit)
            )
            return list((await s.execute(q)).scalars())
