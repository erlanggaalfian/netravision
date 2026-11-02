"""Akun Google Drive multi-akun + drive_account_id per stream.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drive_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("root_folder_id", sa.String(128), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "streams",
        sa.Column("drive_account_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_streams_drive_account_id",
        "streams",
        "drive_accounts",
        ["drive_account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_streams_drive_account_id", "streams", type_="foreignkey")
    op.drop_column("streams", "drive_account_id")
    op.drop_table("drive_accounts")
