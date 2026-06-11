"""Dispatcher — per-org serialization + bounded cross-org concurrency.

Single-writer-per-org is the load-bearing invariant: one build per org at a
time, across *both* lanes (a per-org lock). Different orgs build concurrently up
to a global semaphore. ``submit`` blocks until the build is durably recorded so
the calling consumer only commits the offset afterwards (at-least-once). FAILED
builds (and unexpected errors) go to the DLQ.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from harnext_builder.build_runner import BuildOutcome, BuildStatus
from harnext_builder.work_item import WorkItem

log = logging.getLogger("builder.dispatcher")


class _Runner(Protocol):
    async def run(self, wi: WorkItem) -> BuildOutcome: ...


class _Dlq(Protocol):
    async def send(self, wi: WorkItem, error: str) -> None: ...


class Dispatcher:
    def __init__(self, runner: _Runner, dlq: _Dlq, max_concurrent: int) -> None:
        self.runner = runner
        self.dlq = dlq
        self._sem = asyncio.Semaphore(max_concurrent)
        self._org_locks: dict[str, asyncio.Lock] = {}

    def _lock(self, org_id: str) -> asyncio.Lock:
        return self._org_locks.setdefault(org_id, asyncio.Lock())

    async def submit(self, wi: WorkItem) -> BuildOutcome | None:
        # org lock first (same-org waiters hold no concurrency slot), then the
        # global semaphore (bounds active builds across distinct orgs).
        async with self._lock(wi.org_id):
            async with self._sem:
                try:
                    outcome = await self.runner.run(wi)
                except Exception as e:  # noqa: BLE001 — never let one build kill the loop
                    log.exception("build crashed: org=%s key=%s", wi.org_id, wi.dedupe_key)
                    await self.dlq.send(wi, f"{type(e).__name__}: {e}")
                    return None

        if outcome.status is BuildStatus.FAILED:
            await self.dlq.send(wi, outcome.error or "build failed")
        else:
            log.info(
                "%s org=%s key=%s build=%s",
                outcome.status.value,
                wi.org_id,
                wi.dedupe_key,
                outcome.build_id,
            )
        return outcome
