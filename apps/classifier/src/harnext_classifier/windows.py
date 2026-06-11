"""Per-entity batch windowing.

Batch-lane events accumulate in a per-``(org, subject)`` session window. A window
closes on inactivity gap, on reaching ``max_events``, or on hitting ``max_age``,
emitting one ContextUnit. v1 windows are in-memory (not crash-safe) — fine for
the MVP; durable windowing is future work.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from harnext_shared import CloudEvent, ContextUnit

EmitFn = Callable[[ContextUnit], Awaitable[None]]


@dataclass
class _Window:
    org_id: str
    subject: str
    window_id: str
    events: list[CloudEvent]
    window_start: datetime
    window_end: datetime
    opened_at: float
    last_at: float


class WindowManager:
    def __init__(self, *, gap_s: float, max_events: int, max_age_s: float, emit: EmitFn) -> None:
        self.gap_s = gap_s
        self.max_events = max_events
        self.max_age_s = max_age_s
        self.emit = emit
        self._win: dict[tuple[str, str], _Window] = {}
        self._lock = asyncio.Lock()

    async def add(self, ev: CloudEvent) -> None:
        async with self._lock:
            key = (ev.mgtenant, ev.subject)
            now = time.monotonic()
            w = self._win.get(key)
            if w is None:
                w = _Window(
                    org_id=ev.mgtenant,
                    subject=ev.subject,
                    window_id=uuid.uuid4().hex,
                    events=[],
                    window_start=ev.time,
                    window_end=ev.time,
                    opened_at=now,
                    last_at=now,
                )
                self._win[key] = w
            w.events.append(ev)
            w.last_at = now
            w.window_start = min(w.window_start, ev.time)
            w.window_end = max(w.window_end, ev.time)
            if len(w.events) >= self.max_events:
                await self._close_locked(key)

    async def sweep(self) -> None:
        async with self._lock:
            now = time.monotonic()
            due = [
                k
                for k, w in self._win.items()
                if (now - w.last_at >= self.gap_s) or (now - w.opened_at >= self.max_age_s)
            ]
            for k in due:
                await self._close_locked(k)

    async def flush_all(self) -> None:
        async with self._lock:
            for k in list(self._win.keys()):
                await self._close_locked(k)

    async def _close_locked(self, key: tuple[str, str]) -> None:
        w = self._win.pop(key, None)
        if w is None or not w.events:
            return
        await self.emit(
            ContextUnit(
                org_id=w.org_id,
                subject=w.subject,
                window_id=w.window_id,
                window_start=w.window_start,
                window_end=w.window_end,
                events=w.events,
            )
        )
