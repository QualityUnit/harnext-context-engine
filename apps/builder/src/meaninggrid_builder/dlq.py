"""Dead-letter queue: builds that fail after the build path go here per lane."""

from __future__ import annotations

import json

from aiokafka import AIOKafkaProducer
from meaninggrid_shared import BUILDER_BATCH_GROUP, BUILDER_FAST_GROUP, dlq_topic_for

from meaninggrid_builder.work_item import WorkItem


class Dlq:
    def __init__(self, bootstrap_servers: str) -> None:
        self._p = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)

    async def start(self) -> None:
        await self._p.start()

    async def stop(self) -> None:
        await self._p.stop()

    async def send(self, wi: WorkItem, error: str) -> None:
        group = BUILDER_FAST_GROUP if wi.lane == "fast" else BUILDER_BATCH_GROUP
        payload = {
            "lane": wi.lane,
            "org_id": wi.org_id,
            "dedupe_key": wi.dedupe_key,
            "error": error[:2000],
            "events": [e.model_dump(mode="json") for e in wi.events],
        }
        await self._p.send_and_wait(
            dlq_topic_for(group),
            value=json.dumps(payload, default=str).encode(),
            key=f"{wi.org_id}:{wi.dedupe_key}".encode(),
        )
