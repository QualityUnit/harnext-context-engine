"""Lazily-built shared resources for the MCP tools.

Built on first use so the async engine binds to FastMCP's event loop. Reuses the
builder's OrgFsStore + BuildRunner so the MCP server reads/writes the same store
the builder maintains. These resources are org-agnostic — the per-request tenant
is resolved from the bearer token and passed into each call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from harnext_builder.agentfs.backend import get_backend
from harnext_builder.agentfs.store import OrgFsStore
from harnext_builder.build_runner import BuildRunner
from harnext_builder.persistence import Persistence
from harnext_builder.settings import BuilderSettings
from harnext_shared import init_db, make_engine, make_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class Resources:
    builder_settings: BuilderSettings
    sm: async_sessionmaker[AsyncSession]
    store: OrgFsStore
    build_runner: BuildRunner


_res: Resources | None = None
_lock = asyncio.Lock()


async def get_resources() -> Resources:
    global _res
    if _res is not None:
        return _res
    async with _lock:
        if _res is None:
            builder_settings = BuilderSettings()
            engine = make_engine(builder_settings.database_url)
            await init_db(engine)
            sm = make_sessionmaker(engine)
            store = OrgFsStore(get_backend(builder_settings), sm)
            _res = Resources(
                builder_settings=builder_settings,
                sm=sm,
                store=store,
                build_runner=BuildRunner(store, Persistence(sm), builder_settings),
            )
    return _res
