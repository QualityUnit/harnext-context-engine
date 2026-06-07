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


# Columns added to `users` after v1; ALTER-ed in for existing DBs (create_all
# does not alter existing tables). Keep in sync with the User model.
_USER_AUTH_COLUMNS = {
    "email": "VARCHAR(320)",
    "name": "VARCHAR(255)",
    "password_hash": "TEXT",
    "google_sub": "VARCHAR(255)",
    "avatar_url": "TEXT",
}


async def migrate_schema(engine: AsyncEngine) -> None:
    """Idempotent, non-destructive migrations (SQLite). Preserves existing rows.

    Adds the auth columns/indexes to an existing ``users`` table. A no-op on a
    freshly-created DB (create_all already made them) and on non-SQLite."""
    if not str(engine.url).startswith("sqlite"):
        return
    async with engine.begin() as conn:
        info = await conn.exec_driver_sql("PRAGMA table_info(users)")
        cols = {row[1] for row in info.fetchall()}
        if not cols:
            return  # table will be created by init_db with all columns
        for col, decl in _USER_AUTH_COLUMNS.items():
            if col not in cols:
                await conn.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users(email)"
        )
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub ON users(google_sub)"
        )
