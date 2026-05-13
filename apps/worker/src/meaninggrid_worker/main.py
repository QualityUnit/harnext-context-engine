"""Worker entrypoint — consumes events.raw.v1, runs processors then sinks.

See docs/architecture/ingestion-pipeline.md §9 for the full design.
"""

import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from meaninggrid_shared import (
    GLOBAL_DLQ_TOPIC,
    RAW_EVENTS_TOPIC,
    CloudEvent,
    IngestionContext,
    Processor,
    Sink,
    dlq_topic_for,
)

from meaninggrid_worker.dedup import already_processed
from meaninggrid_worker.embedder import start_embedder
from meaninggrid_worker.graphiti_client import get_graphiti, start_graphiti, stop_graphiti
from meaninggrid_worker.outcomes import record_outcome
from meaninggrid_worker.pipeline import build_chain, run_sinks
from meaninggrid_worker.processors import EmbedDocumentProcessor, ExtractTextProcessor
from meaninggrid_worker.settings import settings
from meaninggrid_worker.sinks import FaissSink, GraphitiSink

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("meaninggrid.worker")


async def _publish_dlq(producer: AIOKafkaProducer, topic: str, event: CloudEvent, error: str, stage: str) -> None:
    payload = {
        "original": event.model_dump(mode="json"),
        "error": error,
        "stage": stage,
    }
    await producer.send_and_wait(topic, value=json.dumps(payload, default=str).encode())


async def _handle(
    event: CloudEvent,
    processors: list[Processor],
    sinks: list[Sink],
    dlq_producer: AIOKafkaProducer,
) -> None:
    chain = build_chain(processors)
    ctx = IngestionContext(event=event)

    try:
        ctx = await chain(ctx)
    except Exception as exc:
        log.exception("processor chain failed for event %s", event.id)
        await _publish_dlq(dlq_producer, GLOBAL_DLQ_TOPIC, event, str(exc), stage="processor")
        return

    runnable_sinks = [
        s for s in sinks
        if not await already_processed(event.mgtenant, event.id, s.name)
    ]
    if not runnable_sinks:
        log.debug("event %s: nothing to do (all sinks already succeeded)", event.id)
        return

    results = await run_sinks(runnable_sinks, ctx)
    for sink, result in zip(runnable_sinks, results, strict=True):
        if result is None:
            await record_outcome(
                tenant_id=event.mgtenant,
                event_id=event.id,
                sink_name=sink.name,
                status="success",
                error=None,
                attempts=1,
            )
            log.info("sink=%s event=%s ok", sink.name, event.id)
        else:
            err = f"{type(result).__name__}: {result}"
            await record_outcome(
                tenant_id=event.mgtenant,
                event_id=event.id,
                sink_name=sink.name,
                status="failed",
                error=err,
                attempts=1,
            )
            await _publish_dlq(dlq_producer, dlq_topic_for(sink.name), event, err, stage=f"sink:{sink.name}")
            log.error("sink=%s event=%s failed: %s", sink.name, event.id, err)


async def run() -> None:
    log.info("worker booting")
    log.info("kafka=%s falkordb=%s:%d", settings.kafka_bootstrap_servers, settings.falkordb_host, settings.falkordb_port)

    await start_graphiti()
    graphiti = get_graphiti()
    start_embedder()

    processors: list[Processor] = [ExtractTextProcessor(), EmbedDocumentProcessor()]
    sinks: list[Sink] = [GraphitiSink(graphiti), FaissSink()]
    log.info("processors: %s", [p.name for p in processors])
    log.info("sinks: %s", [s.name for s in sinks])

    consumer = AIOKafkaConsumer(
        RAW_EVENTS_TOPIC,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        value_deserializer=lambda v: json.loads(v.decode()),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        # LLM extraction can take minutes per event with local models — give the
        # consumer plenty of time before the broker thinks it died.
        max_poll_interval_ms=15 * 60 * 1000,   # 15 min between poll() calls
        session_timeout_ms=60 * 1000,
        heartbeat_interval_ms=10 * 1000,
    )
    dlq_producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
    )

    await consumer.start()
    await dlq_producer.start()
    log.info("consumer started; awaiting events on %s …", RAW_EVENTS_TOPIC)

    try:
        async for msg in consumer:
            try:
                event = CloudEvent.model_validate(msg.value)
            except Exception as e:
                log.error("invalid envelope, skipping (offset=%d): %s", msg.offset, e)
                await consumer.commit()
                continue

            await _handle(event, processors, sinks, dlq_producer)
            await consumer.commit()
    finally:
        log.info("worker shutting down")
        await consumer.stop()
        await dlq_producer.stop()
        await stop_graphiti()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    main()
