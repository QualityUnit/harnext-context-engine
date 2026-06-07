"""context_get_urls — resolve conversation-log URLs to their stored content.

A URL is ``cms://conversation/<id>`` (or a bare id). Scoped to the server's org.
"""

from __future__ import annotations

import json
from typing import Any

from meaninggrid_shared import ConversationLog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_CLIP = 8000


def conversation_url(conversation_id: str) -> str:
    return f"cms://conversation/{conversation_id}"


def _parse_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def _transcript_text(transcript_json: str) -> str:
    try:
        turns = json.loads(transcript_json).get("turns", [])
    except (ValueError, AttributeError):
        return ""
    lines = []
    for t in turns:
        role = t.get("role", "")
        content = (t.get("content") or "").strip()
        if role in ("assistant", "result", "tool_use") and content:
            tag = t.get("tool_name") or role
            lines.append(f"[{tag}] {content}")
    text = "\n".join(lines)
    return text if len(text) <= _CLIP else text[:_CLIP] + "…"


async def get_conversation_payload(
    sm: async_sessionmaker[AsyncSession], org_id: str, url: str
) -> dict[str, Any]:
    cid = _parse_id(url)
    async with sm() as s:
        row = await s.get(ConversationLog, cid)
    if row is None or row.org_id != org_id:
        return {"url": url, "found": False}
    return {
        "url": url,
        "found": True,
        "build_id": row.build_id,
        "lane": row.lane,
        "harness": row.harness,
        "stop_reason": row.stop_reason,
        "snapshot_id": row.snapshot_id,
        "instruction": row.instruction,
        "files_changed": json.loads(row.files_changed_json),
        "transcript": _transcript_text(row.transcript_json),
        "created_at": row.created_at.isoformat(),
    }
