"""The MCP context server — the only external surface.

Three tools over one org's AgentFS + conversation log:
  - context_research(question)        → synthesized, cited answer (read agent)
  - context_get_urls(urls)            → raw-conversation-log content by URL
  - context_update(instruction, ...)  → write agent applies it to the store
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastmcp import FastMCP

from meaninggrid_mcp.context import get_ctx
from meaninggrid_mcp.conversation import conversation_url, get_conversation_payload
from meaninggrid_mcp.research import research
from meaninggrid_mcp.settings import MCPSettings

log = logging.getLogger("mcp")

mcp: FastMCP = FastMCP("MeaningGrid Context")


@mcp.tool
async def context_research(question: str) -> dict[str, Any]:
    """Search the organization's context and return a synthesized, cited answer.

    The answer is drawn only from the org's stored context (its events, files,
    and prior agent work). Use this to pull the right context before acting."""
    ctx = await get_ctx()
    return await research(ctx.store, ctx.builder_settings, ctx.org_id, question)


@mcp.tool
async def context_get_urls(urls: list[str]) -> list[dict[str, Any]]:
    """Fetch the content behind one or more context URLs (e.g. the
    cms://conversation/<id> URLs returned by context_update)."""
    ctx = await get_ctx()
    return [await get_conversation_payload(ctx.sm, ctx.org_id, u) for u in urls]


@mcp.tool
async def context_update(instruction: str, context: str | None = None) -> dict[str, Any]:
    """Apply an instruction to the organization's context store. Spawns an
    internal write agent that incorporates the instruction (and optional context)
    into the store, returning a URL for the resulting conversation."""
    ctx = await get_ctx()
    full = instruction if not context else f"{instruction}\n\nCaller-provided context:\n{context}"
    outcome = await ctx.build_runner.run_update(ctx.org_id, full, uuid.uuid4().hex)
    return {
        "status": outcome.status.value,
        "build_id": outcome.build_id,
        "snapshot_id": outcome.snapshot_id,
        "conversation_url": (
            conversation_url(outcome.conversation_id) if outcome.conversation_id else None
        ),
        "error": outcome.error,
    }


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    s = MCPSettings()
    log.info("MCP context server for org=%s on %s:%d", s.org_id, s.mcp_host, s.mcp_port)
    mcp.run(transport="http", host=s.mcp_host, port=s.mcp_port)


if __name__ == "__main__":
    run()
