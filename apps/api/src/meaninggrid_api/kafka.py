"""Kafka producer lifecycle and helpers."""

import json
from typing import Any

from aiokafka import AIOKafkaProducer

from meaninggrid_api.settings import settings
from meaninggrid_shared import CloudEvent, RAW_EVENTS_TOPIC

_producer: AIOKafkaProducer | None = None


async def start_producer() -> None:
    global _producer
    _producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v, default=str).encode(),
        compression_type="gzip",
    )
    await _producer.start()


async def stop_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


def get_producer() -> AIOKafkaProducer:
    if _producer is None:
        raise RuntimeError("Kafka producer not started")
    return _producer


async def publish_event(event: CloudEvent) -> None:
    """Publish a CloudEvent to events.raw.v1 with the tenant-scoped, entity-keyed partition key."""
    payload: dict[str, Any] = event.model_dump(mode="json")
    await get_producer().send_and_wait(
        RAW_EVENTS_TOPIC,
        value=payload,
        key=event.partition_key(),
    )
