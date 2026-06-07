"""WorkItem — unifies a fast event and a batch Context Unit for the builder.

Fast and batch flow through the *same* build path; only the trigger and the
rendered instruction differ. ``dedupe_key`` is the CloudEvent ``(source, id)``
for a fast event, or the window id for a batch unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from meaninggrid_shared import CloudEvent, ContextUnit


@dataclass
class WorkItem:
    org_id: str
    lane: str  # fast | batch
    dedupe_key: str
    subjects: list[str]
    events: list[CloudEvent]
    window_meta: dict[str, Any] | None = field(default=None)

    @classmethod
    def from_fast_event(cls, ev: CloudEvent) -> WorkItem:
        return cls(
            org_id=ev.mgtenant,
            lane="fast",
            dedupe_key=f"{ev.source}::{ev.id}",
            subjects=[ev.subject],
            events=[ev],
        )

    @classmethod
    def from_context_unit(cls, cu: ContextUnit) -> WorkItem:
        return cls(
            org_id=cu.org_id,
            lane="batch",
            dedupe_key=cu.window_id,
            subjects=[cu.subject],
            events=cu.events,
            window_meta={
                "window_id": cu.window_id,
                "window_start": cu.window_start.isoformat(),
                "window_end": cu.window_end.isoformat(),
            },
        )
