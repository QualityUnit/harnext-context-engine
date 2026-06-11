"""Async engine / session helpers shared by every CMS app.

All apps point at the same ``DATABASE_URL`` (one SQLite file in v1) and reuse
this factory so WAL pragmas and the session config stay consistent. Schema is
owned by Alembic: ``init_db`` brings the DB up to the latest revision on startup.
"""

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from harnext_shared.db import configure_sqlite_pragmas

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def make_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, future=True)
    configure_sqlite_pragmas(engine)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _upgrade_to_head(database_url: str) -> None:
    """Apply all pending Alembic migrations (synchronous). Run off-thread by
    ``init_db`` so it never blocks the event loop or nests an event loop."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.attributes["sqlalchemy_url"] = database_url
    command.upgrade(cfg, "head")


async def init_db(engine: AsyncEngine) -> None:
    """Bring the schema to the latest Alembic revision. Safe to call on every
    app startup (idempotent: a no-op once the DB is already at head)."""
    url = engine.url.render_as_string(hide_password=False)
    await asyncio.to_thread(_upgrade_to_head, url)
