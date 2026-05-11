"""Async SQLAlchemy engine for the worker. Same DB as the API (shared SQLite file)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from meaninggrid_shared import configure_sqlite_pragmas
from meaninggrid_worker.settings import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)
configure_sqlite_pragmas(engine)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
