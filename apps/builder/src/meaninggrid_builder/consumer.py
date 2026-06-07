"""Lane consumers — decode fast events / batch units into WorkItems and submit.

Both lanes feed the same Dispatcher. Manual commit after the build is durably
recorded (at-least-once; the ledger makes redelivery idempotent).
``max_poll_interval_ms`` is large because a build runs a coding agent.
"""

from __future__ import annotations

import logging

from aiokafka import AIOKafkaConsumer
from meaninggrid_shared import CloudEvent, ContextUnit

from meaninggrid_builder.dispatcher import Dispatcher
from meaninggrid_builder.work_item import WorkItem

log = logging.getLogger("builder.consumer")

_MAX_POLL_INTERVAL_MS = 1_800_000  # 30 min — a build runs a coding agent


def decode(lane: str, value: bytes) -> WorkItem | None:
    try:
        if lane == "fast":
            return WorkItem.from_fast_event(CloudEvent.model_validate_json(value))
        return WorkItem.from_context_unit(ContextUnit.model_validate_json(value))
    except Exception as e:  # noqa: BLE001 — skip undecodable messages
        log.warning("undecodable %s message: %s", lane, e)
        return None


class LaneConsumer:
    def __init__(
        self, *, topic: str, group: str, lane: str, bootstrap_servers: str, dispatcher: Dispatcher
    ) -> None:
        self.topic = topic
        self.group = group
        self.lane = lane
        self.bootstrap = bootstrap_servers
        self.dispatcher = dispatcher

    async def run(self) -> None:
        consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap,
            group_id=self.group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_interval_ms=_MAX_POLL_INTERVAL_MS,
        )
        await consumer.start()
        log.info("consuming %s (group %s)", self.topic, self.group)
        try:
            async for msg in consumer:
                if msg.value is not None:
                    wi = decode(self.lane, msg.value)
                    if wi is not None:
                        await self.dispatcher.submit(wi)
                await consumer.commit()
        finally:
            await consumer.stop()
