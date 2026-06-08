"""add liveagent integration columns to projects

Revision ID: d4e2f6a7b8c9
Revises: c3f1a2b4d5e6
Create Date: 2026-06-08 20:50:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e2f6a7b8c9"
down_revision: str | None = "c3f1a2b4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LiveAgent is self-hosted with a per-install base URL + v3 API key (no OAuth),
    # so both live on the project (the key is the per-source secret at create time).
    op.add_column("projects", sa.Column("liveagent_base_url", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("liveagent_api_key", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_column("liveagent_api_key")
        batch_op.drop_column("liveagent_base_url")
