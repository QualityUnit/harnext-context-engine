"""The batch-lane message: a Context Unit.

The fast lane carries a single ``CloudEvent``. The batch lane carries a
``ContextUnit`` — the accumulated events for one entity window, emitted at
window close. In v1 the unit is the raw windowed events (the builder agent does
the synthesis); RQ3's richer aggregation (dedupe, sketches, map-reduce
summaries) is future work.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from harnext_shared.envelope import CloudEvent


class ContextUnit(BaseModel):
    """One window's worth of events for a single entity (subject)."""

    schema_: str = Field(default="cms/context-unit/v1", alias="schema")
    org_id: str
    subject: str  # the entity key these events share
    window_id: str  # stable per window → the batch dedupe_key
    window_start: datetime
    window_end: datetime
    events: list[CloudEvent]

    model_config = {"populate_by_name": True}

    def partition_key(self) -> bytes:
        return f"{self.org_id}:{self.subject}".encode()
