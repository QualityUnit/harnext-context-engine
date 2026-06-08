"""Alembic migration environment for the CMS metadata DB.

Migrations run over a *synchronous* driver even though the apps use async — the
URL's async driver (``+aiosqlite`` / ``+asyncpg``) is stripped here. The URL is
resolved, in priority order, from:

  1. ``config.attributes["sqlalchemy_url"]`` — set by ``init_db`` when migrations
     are applied programmatically on app startup.
  2. the ``DATABASE_URL`` environment variable — for the ``alembic`` CLI.
  3. the same default the app settings use.

``target_metadata`` is the shared ``Base.metadata`` so ``--autogenerate`` diffs
against the live ORM models. Batch mode is on so SQLite ``ALTER`` migrations work.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from meaninggrid_shared.db import Base
from sqlalchemy import create_engine, pool

config = context.config

# Only configure logging from the .ini when run via the CLI (which passes one).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

DEFAULT_URL = "sqlite+aiosqlite:///./data/meaninggrid.sqlite"


def _sync_url(url: str) -> str:
    """Map an async SQLAlchemy URL to its synchronous driver for migrations."""
    return url.replace("+aiosqlite", "").replace("+asyncpg", "")


def _resolve_url() -> str:
    return config.attributes.get("sqlalchemy_url") or os.environ.get("DATABASE_URL") or DEFAULT_URL


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(_resolve_url()),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _sync_url(_resolve_url())
    # A generous busy timeout lets concurrent app startups serialize on the
    # single SQLite file instead of erroring with "database is locked".
    connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
    connectable = create_engine(url, poolclass=pool.NullPool, connect_args=connect_args)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
