"""Async Kafka producer for the fast (CloudEvent) and batch (ContextUnit) lanes."""

from __future__ import annotations

from aiokafka import AIOKafkaProducer
from harnext_shared import CloudEvent, ContextUnit


class Producer:
    def __init__(self, bootstrap_servers: str) -> None:
        self._p = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)

    async def start(self) -> None:
        await self._p.start()

    async def stop(self) -> None:
        await self._p.stop()

    async def send_event(self, topic: str, event: CloudEvent) -> None:
        await self._p.send_and_wait(
            topic, value=event.model_dump_json().encode(), key=event.partition_key()
        )

    async def send_unit(self, topic: str, unit: ContextUnit) -> None:
        await self._p.send_and_wait(
            topic,
            value=unit.model_dump_json(by_alias=True).encode(),
            key=unit.partition_key(),
        )
