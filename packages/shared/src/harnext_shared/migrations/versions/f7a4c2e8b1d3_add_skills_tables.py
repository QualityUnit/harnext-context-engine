"""add skills + skill_files tables (project-scoped agent skills)

Revision ID: f7a4c2e8b1d3
Revises: e5a3b7c91f02
Create Date: 2026-06-12 12:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a4c2e8b1d3"
down_revision: str | None = "e5a3b7c91f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "name", name="uq_skills_org_name"),
    )
    with op.batch_alter_table("skills", schema=None) as batch_op:
        batch_op.create_index("ix_skills_org_id", ["org_id"], unique=False)

    op.create_table(
        "skill_files",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("hash", sa.String(length=128), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "path", name="uq_skill_files_skill_path"),
    )
    with op.batch_alter_table("skill_files", schema=None) as batch_op:
        batch_op.create_index("ix_skill_files_skill_id", ["skill_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("skill_files", schema=None) as batch_op:
        batch_op.drop_index("ix_skill_files_skill_id")

    op.drop_table("skill_files")
    with op.batch_alter_table("skills", schema=None) as batch_op:
        batch_op.drop_index("ix_skills_org_id")

    op.drop_table("skills")
