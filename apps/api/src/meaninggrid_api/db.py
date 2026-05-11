"""Async SQLAlchemy engine + session factory.

Used by both the API (ingest writes, read endpoints) and the bootstrap script.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from meaninggrid_api.settings import settings
from meaninggrid_shared import Base, configure_sqlite_pragmas

engine = create_async_engine(settings.database_url, echo=False, future=True)
configure_sqlite_pragmas(engine)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """Create all tables. v0 uses create_all; introduce Alembic when schema starts changing."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionLocal() as session:
        yield session
