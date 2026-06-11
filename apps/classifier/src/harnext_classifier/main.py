"""Classifier — consume raw events, route fast/batch, manage batch windows."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiokafka import AIOKafkaConsumer
from harnext_shared import (
    BATCH_EVENTS_TOPIC,
    CLASSIFIER_GROUP,
    FAST_EVENTS_TOPIC,
    RAW_EVENTS_TOPIC,
    CloudEvent,
    init_db,
    make_engine,
    make_sessionmaker,
)

from harnext_classifier.anomaly import AnomalyScorer
from harnext_classifier.kafka import Producer
from harnext_classifier.router import Router
from harnext_classifier.settings import ClassifierSettings
from harnext_classifier.windows import WindowManager

log = logging.getLogger("classifier")


async def _sweep_loop(wm: WindowManager, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        await wm.sweep()


async def run_async() -> None:
    settings = ClassifierSettings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)

    producer = Producer(settings.kafka_bootstrap_servers)
    await producer.start()
    router = Router(AnomalyScorer(sm, settings), settings)
    wm = WindowManager(
        gap_s=settings.window_gap_s,
        max_events=settings.window_max_events,
        max_age_s=settings.window_max_age_s,
        emit=lambda cu: producer.send_unit(BATCH_EVENTS_TOPIC, cu),
    )

    consumer = AIOKafkaConsumer(
        RAW_EVENTS_TOPIC,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=CLASSIFIER_GROUP,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        max_poll_interval_ms=300_000,
    )
    await consumer.start()
    sweeper = asyncio.create_task(_sweep_loop(wm, settings.window_sweep_s))
    log.info("classifier up: %s → {fast,batch}", RAW_EVENTS_TOPIC)

    try:
        async for msg in consumer:
            if msg.value is None:
                await consumer.commit()
                continue
            try:
                ev = CloudEvent.model_validate_json(msg.value)
            except Exception as e:  # noqa: BLE001 — skip undecodable envelopes
                log.warning("bad event @offset %d: %s", msg.offset, e)
                await consumer.commit()
                continue

            decision = await router.decide(ev)
            if decision.lane == "fast":
                await producer.send_event(FAST_EVENTS_TOPIC, ev)
                log.info("FAST  %s (%s, score=%.2f)", ev.subject, decision.reason, decision.score)
            else:
                await wm.add(ev)
            await consumer.commit()
    finally:
        sweeper.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper
        await wm.flush_all()
        await producer.stop()
        await consumer.stop()
        await engine.dispose()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
