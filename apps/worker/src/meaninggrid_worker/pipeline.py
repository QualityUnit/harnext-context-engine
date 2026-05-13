"""Worker pipeline: build the processor chain (Phase A) and run sinks (Phase B).

See docs/architecture/ingestion-pipeline.md §9.5 for the worker loop and §9.3-9.4
for the Processor / Sink contracts.
"""

import asyncio
from collections.abc import Awaitable, Callable

from meaninggrid_shared import IngestionContext, Processor, Sink


def build_chain(
    processors: list[Processor],
) -> Callable[[IngestionContext], Awaitable[IngestionContext]]:
    """Compose processors into a middleware chain. Standard onion model."""

    async def run(ctx: IngestionContext) -> IngestionContext:
        async def step(i: int) -> IngestionContext:
            if i == len(processors):
                return ctx
            return await processors[i](ctx, lambda: step(i + 1))

        return await step(0)

    return run


async def run_sinks(
    sinks: list[Sink],
    ctx: IngestionContext,
) -> list[BaseException | None]:
    """Run sinks in parallel. Returns one entry per sink: None on success, the
    exception on failure. Caller routes failures to per-sink DLQ topics.
    """
    results = await asyncio.gather(
        *(sink.write(ctx) for sink in sinks),
        return_exceptions=True,
    )
    return [r if isinstance(r, BaseException) else None for r in results]
