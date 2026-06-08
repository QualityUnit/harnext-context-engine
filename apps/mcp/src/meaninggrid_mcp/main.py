"""The MCP context server — the only external surface.

Multi-tenant: one always-on process serves every project. Each request carries a
per-project bearer token (``Authorization: Bearer <token>``, minted by the
dashboard); the token's ``org`` claim is the tenant for that call. Three tools
over an org's AgentFS + conversation log:
  - context_research(question)        → synthesized, cited answer (read agent)
  - context_get_urls(urls)            → raw-conversation-log content by URL
  - context_update(instruction, ...)  → write agent applies it to the store
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from meaninggrid_shared import decode_mcp_token

from meaninggrid_mcp.context import get_resources
from meaninggrid_mcp.conversation import conversation_url, get_conversation_payload
from meaninggrid_mcp.research import research
from meaninggrid_mcp.settings import MCPSettings

log = logging.getLogger("mcp")

settings = MCPSettings()


class MeaningGridTokenVerifier(TokenVerifier):
    """Verify a per-project MCP bearer token and expose its org as the client id."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret

    async def verify_token(self, token: str) -> AccessToken | None:
        org = decode_mcp_token(token, self._secret)
        if org is None:
            return None
        return AccessToken(token=token, client_id=org, scopes=["mcp"])


mcp: FastMCP = FastMCP(
    "MeaningGrid Context", auth=MeaningGridTokenVerifier(settings.jwt_secret)
)


def _org() -> str:
    """The tenant for the current request, from its verified bearer token."""
    token = get_access_token()
    if token is None or not token.client_id:
        raise ToolError("missing or invalid MeaningGrid token")
    return token.client_id


@mcp.tool
async def context_research(question: str) -> dict[str, Any]:
    """Search the organization's context and return a synthesized, cited answer.

    The answer is drawn only from the org's stored context (its events, files,
    and prior agent work). Use this to pull the right context before acting."""
    res = await get_resources()
    return await research(res.store, res.builder_settings, _org(), question)


@mcp.tool
async def context_get_urls(urls: list[str]) -> list[dict[str, Any]]:
    """Fetch the content behind one or more context URLs (e.g. the
    cms://conversation/<id> URLs returned by context_update)."""
    res = await get_resources()
    org = _org()
    return [await get_conversation_payload(res.sm, org, u) for u in urls]


@mcp.tool
async def context_update(instruction: str, context: str | None = None) -> dict[str, Any]:
    """Apply an instruction to the organization's context store. Spawns an
    internal write agent that incorporates the instruction (and optional context)
    into the store, returning a URL for the resulting conversation."""
    res = await get_resources()
    full = instruction if not context else f"{instruction}\n\nCaller-provided context:\n{context}"
    outcome = await res.build_runner.run_update(_org(), full, uuid.uuid4().hex)
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
    log.info(
        "MeaningGrid MCP server (multi-tenant) on %s:%d", settings.mcp_host, settings.mcp_port
    )
    mcp.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    run()
