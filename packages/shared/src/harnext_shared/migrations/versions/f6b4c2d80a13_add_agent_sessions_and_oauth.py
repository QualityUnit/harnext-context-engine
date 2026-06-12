"""add agent harness OAuth (device flow) + pushed conversation logs

Revision ID: f6b4c2d80a13
Revises: e5a3b7c91f02
Create Date: 2026-06-12 12:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6b4c2d80a13"
down_revision: str | None = "e5a3b7c91f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # OAuth 2.0 Device Authorization Grant (RFC 8628) requests. State lives in the
    # DB (not process memory) so polling + approval can land on different workers.
    op.create_table(
        "device_auth_requests",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("device_code", sa.String(length=64), nullable=False),
        sa.Column("user_code", sa.String(length=16), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("device_auth_requests", schema=None) as batch_op:
        batch_op.create_index(
            "ix_device_auth_device_code", ["device_code"], unique=True
        )
        batch_op.create_index("ix_device_auth_user_code", ["user_code"], unique=True)

    # Rotated, hashed refresh tokens (only the SHA-256 hash is stored).
    op.create_table(
        "agent_refresh_tokens",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_refresh_tokens", schema=None) as batch_op:
        batch_op.create_index(
            "ix_agent_refresh_token_hash", ["token_hash"], unique=True
        )
        batch_op.create_index("ix_agent_refresh_org", ["org_id"], unique=False)

    # Pushed conversations: one header row per session.
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("client_session_id", sa.String(length=128), nullable=False),
        sa.Column("harness", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("usage_json", sa.Text(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_sessions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_agent_sessions_org_time", ["org_id", "started_at"], unique=False
        )
        batch_op.create_index(
            "ix_agent_sessions_client_session",
            ["org_id", "client_session_id"],
            unique=True,
        )

    # Append-only turns within a session (one raw stream-json envelope each).
    op.create_table(
        "agent_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_agent_events_session_seq", ["session_id", "seq"], unique=True
        )


def downgrade() -> None:
    op.drop_table("agent_events")
    op.drop_table("agent_sessions")
    op.drop_table("agent_refresh_tokens")
    op.drop_table("device_auth_requests")
