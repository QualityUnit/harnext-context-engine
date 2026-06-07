"""Async engine / session helpers shared by every CMS app.

All apps point at the same ``DATABASE_URL`` (one SQLite file in v1) and reuse
this factory so WAL pragmas and the session config stay consistent.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from meaninggrid_shared.db import Base, configure_sqlite_pragmas


def make_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, future=True)
    configure_sqlite_pragmas(engine)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables if missing. Safe to call on every app startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
