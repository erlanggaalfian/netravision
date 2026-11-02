"""Tabel google_drive_settings (mode folder-link + rclone).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_drive_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("folder_url", sa.String(500), nullable=True, server_default=""),
        sa.Column("folder_id", sa.String(128), nullable=True, server_default=""),
        sa.Column("folder_name", sa.String(128), nullable=True, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(50), nullable=True, server_default=""),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("google_drive_settings")
