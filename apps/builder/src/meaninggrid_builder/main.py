"""Builder — consume both lanes, run the harness over each org's AgentFS."""

from __future__ import annotations

import asyncio
import logging

from meaninggrid_shared import (
    BATCH_EVENTS_TOPIC,
    BUILDER_BATCH_GROUP,
    BUILDER_FAST_GROUP,
    FAST_EVENTS_TOPIC,
    init_db,
    make_engine,
    make_sessionmaker,
)

from meaninggrid_builder.agentfs.backend import get_backend
from meaninggrid_builder.agentfs.store import OrgFsStore
from meaninggrid_builder.build_runner import BuildRunner
from meaninggrid_builder.consumer import LaneConsumer
from meaninggrid_builder.dispatcher import Dispatcher
from meaninggrid_builder.dlq import Dlq
from meaninggrid_builder.persistence import Persistence
from meaninggrid_builder.reconcile import reconcile
from meaninggrid_builder.settings import BuilderSettings

log = logging.getLogger("builder")


async def run_async() -> None:
    settings = BuilderSettings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)

    store = OrgFsStore(get_backend(settings), sm)
    await reconcile(store, sm)
    build_runner = BuildRunner(store, Persistence(sm), settings)
    dlq = Dlq(settings.kafka_bootstrap_servers)
    await dlq.start()
    dispatcher = Dispatcher(build_runner, dlq, settings.max_concurrent_builds)

    fast = LaneConsumer(
        topic=FAST_EVENTS_TOPIC,
        group=BUILDER_FAST_GROUP,
        lane="fast",
        bootstrap_servers=settings.kafka_bootstrap_servers,
        dispatcher=dispatcher,
    )
    batch = LaneConsumer(
        topic=BATCH_EVENTS_TOPIC,
        group=BUILDER_BATCH_GROUP,
        lane="batch",
        bootstrap_servers=settings.kafka_bootstrap_servers,
        dispatcher=dispatcher,
    )

    log.info("builder up: harness=%s backend=%s", settings.harness, settings.agentfs_backend)
    try:
        await asyncio.gather(fast.run(), batch.run())
    finally:
        await dlq.stop()
        await engine.dispose()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
