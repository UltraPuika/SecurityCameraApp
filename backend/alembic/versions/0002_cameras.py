"""cameras and provider accounts

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("secrets_enc", sa.Text(), nullable=False),
        sa.Column("state_enc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_accounts_provider", "provider_accounts", ["provider"])
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column("group_name", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("provider_accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("favourite", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("secrets_enc", sa.Text(), nullable=False),
        sa.Column("discovered", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("status_code", sa.String(64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cameras_location", "cameras", ["location"])
    op.create_index("ix_cameras_provider", "cameras", ["provider"])


def downgrade() -> None:
    op.drop_table("cameras")
    op.drop_table("provider_accounts")
