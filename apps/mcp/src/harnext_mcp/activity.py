"""Records every MCP tool call (request + response) to the shared metadata DB.

The dashboard reads these rows to chart MCP request volume over time and show the
raw request/response pairs. Recording is strictly best-effort: a logging failure
must never break the tool call it is observing, and payloads are size-capped so a
large research answer or transcript can't bloat the metadata DB.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from harnext_shared import McpRequest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger("mcp.activity")

_PARAMS_CAP = 8_000
_RESPONSE_CAP = 20_000


def _dump(value: Any, cap: int) -> str:
    try:
        s = json.dumps(value, default=str)
    except Exception:  # noqa: BLE001 — never let serialization break logging
        s = str(value)
    return s if len(s) <= cap else s[:cap] + "…"


async def record_request(
    sm: async_sessionmaker[AsyncSession],
    *,
    org_id: str,
    tool: str,
    params: dict[str, Any],
    status: str,
    response: Any,
    error: str | None,
    duration_ms: int,
) -> None:
    """Persist one MCP tool call. Swallows its own errors by design."""
    try:
        async with sm() as s:
            s.add(
                McpRequest(
                    id=uuid.uuid4().hex,
                    org_id=org_id,
                    tool=tool,
                    params_json=_dump(params, _PARAMS_CAP),
                    status=status,
                    response_json=None if response is None else _dump(response, _RESPONSE_CAP),
                    error=error[:2000] if error else None,
                    duration_ms=duration_ms,
                )
            )
            await s.commit()
    except Exception:  # noqa: BLE001 — logging must not break the tool call
        log.exception("failed to record MCP request (org=%s tool=%s)", org_id, tool)
