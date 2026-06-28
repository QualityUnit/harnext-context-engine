"""Async Kafka producer for the raw events topic."""

from __future__ import annotations

from aiokafka import AIOKafkaProducer
from harnext_shared import CloudEvent

from harnext_ingest.connectors.ordering import derive_ordering_key


class Producer:
    def __init__(self, bootstrap_servers: str) -> None:
        self._p = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)

    async def start(self) -> None:
        await self._p.start()

    async def stop(self) -> None:
        await self._p.stop()

    async def send_event(self, topic: str, event: CloudEvent) -> None:
        """Publish a CloudEvent, partitioned by ``{mgtenant}:{ordering_key or subject}``.

        This is the single point where the connector's declared ordering key
        (D1, #15) is stamped onto the event when unset, so every poll/webhook path
        routes the same way and downstream stages inherit the same partition
        domain via the serialized field.
        """
        if event.ordering_key is None:
            event.ordering_key = derive_ordering_key(event)
        await self._p.send_and_wait(
            topic,
            value=event.model_dump_json().encode(),
            key=event.partition_key(),
        )
