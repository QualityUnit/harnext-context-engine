"""Connector protocol: pull a source's recent activity as CloudEvents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from meaninggrid_shared import CloudEvent


@dataclass
class FetchResult:
    events: list[CloudEvent]  # chronological (oldest first)
    cursor: str | None  # new incremental-sync watermark


@runtime_checkable
class Connector(Protocol):
    kind: str

    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult: ...
