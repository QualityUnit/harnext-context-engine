"""Lazily-built shared resources for the MCP tools.

Built on first use so the async engine binds to FastMCP's event loop. Reuses the
builder's OrgFsStore + BuildRunner so the MCP server reads/writes the same store
the builder maintains.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from meaninggrid_builder.agentfs.backend import get_backend
from meaninggrid_builder.agentfs.store import OrgFsStore
from meaninggrid_builder.build_runner import BuildRunner
from meaninggrid_builder.persistence import Persistence
from meaninggrid_builder.settings import BuilderSettings
from meaninggrid_shared import init_db, make_engine, make_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meaninggrid_mcp.settings import MCPSettings


@dataclass
class Context:
    org_id: str
    builder_settings: BuilderSettings
    sm: async_sessionmaker[AsyncSession]
    store: OrgFsStore
    build_runner: BuildRunner


_ctx: Context | None = None
_lock = asyncio.Lock()


async def get_ctx() -> Context:
    global _ctx
    if _ctx is not None:
        return _ctx
    async with _lock:
        if _ctx is None:
            mcp_settings = MCPSettings()
            builder_settings = BuilderSettings()
            engine = make_engine(builder_settings.database_url)
            await init_db(engine)
            sm = make_sessionmaker(engine)
            store = OrgFsStore(get_backend(builder_settings), sm)
            _ctx = Context(
                org_id=mcp_settings.org_id,
                builder_settings=builder_settings,
                sm=sm,
                store=store,
                build_runner=BuildRunner(store, Persistence(sm), builder_settings),
            )
    return _ctx
