"""Worker pipeline protocols: IngestionContext, Processor, Sink.

The contract lives here (in shared) so apps/worker can implement it and apps/api
can reference the types when surfacing per-sink completion status.

See docs/architecture/ingestion-pipeline.md §9 for the full architecture.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from meaninggrid_shared.envelope import CloudEvent


@dataclass
class IngestionContext:
    """The data carrier passed through both phases (processors → sinks).

    `event` is immutable; processors that need to "rewrite" the event add an
    artifact instead. `artifacts` is additive — processors add keys, never
    overwrite, never remove.

    Conventional artifact keys:
        artifacts["text"]          — extracted full text (str)
        artifacts["chunks"]        — list[str] of text chunks
        artifacts["embedding"]     — np.ndarray for the whole document
        artifacts["chunk_embeds"]  — list[np.ndarray] per chunk
        artifacts["summary"]       — short LLM summary
    """

    event: CloudEvent
    artifacts: dict[str, Any] = field(default_factory=dict)


# Middleware signature: (ctx, next) -> ctx. See §9.3.
Next = Callable[[], Awaitable[IngestionContext]]


@runtime_checkable
class Processor(Protocol):
    """Phase A — middleware. Sequential, ordered by topological sort on requires/produces."""

    name: str
    requires: list[str]
    produces: list[str]

    async def __call__(self, ctx: IngestionContext, next_: Next) -> IngestionContext: ...


@runtime_checkable
class Sink(Protocol):
    """Phase B — terminal handler. Parallel, independent, idempotent on event.id."""

    name: str
    requires: list[str]

    async def write(self, ctx: IngestionContext) -> None: ...
