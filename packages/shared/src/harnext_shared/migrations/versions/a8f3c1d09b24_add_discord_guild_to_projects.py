"""add discord guild columns to projects

Revision ID: a8f3c1d09b24
Revises: 6ec9cb8af050
Create Date: 2026-06-08 19:40:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8f3c1d09b24"
down_revision: str | None = "6ec9cb8af050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Discord is poll-only with an app-level bot token; only the invited guild is
    # per-project (mirrors slack_team_id/slack_team_name).
    op.add_column("projects", sa.Column("discord_guild_id", sa.String(length=64), nullable=True))
    op.add_column(
        "projects", sa.Column("discord_guild_name", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_column("discord_guild_name")
        batch_op.drop_column("discord_guild_id")
