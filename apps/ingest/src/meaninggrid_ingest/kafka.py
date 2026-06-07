"""Async Kafka producer for the raw events topic."""

from __future__ import annotations

from aiokafka import AIOKafkaProducer
from meaninggrid_shared import CloudEvent


class Producer:
    def __init__(self, bootstrap_servers: str) -> None:
        self._p = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)

    async def start(self) -> None:
        await self._p.start()

    async def stop(self) -> None:
        await self._p.stop()

    async def send_event(self, topic: str, event: CloudEvent) -> None:
        """Publish a CloudEvent, partitioned by ``{mgtenant}:{subject}``."""
        await self._p.send_and_wait(
            topic,
            value=event.model_dump_json().encode(),
            key=event.partition_key(),
        )
