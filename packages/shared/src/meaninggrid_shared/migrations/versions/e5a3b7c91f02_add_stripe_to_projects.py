"""add stripe integration columns to projects

Revision ID: e5a3b7c91f02
Revises: d4e2f6a7b8c9
Create Date: 2026-06-09 12:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a3b7c91f02"
down_revision: str | None = "d4e2f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Stripe is connected with a read-only Restricted API key (no OAuth), so the
    # key lives on the project (the per-source secret at create time). The resolved
    # account display name is stored alongside it to show in the UI.
    op.add_column("projects", sa.Column("stripe_account_name", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("stripe_api_key", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_column("stripe_api_key")
        batch_op.drop_column("stripe_account_name")
