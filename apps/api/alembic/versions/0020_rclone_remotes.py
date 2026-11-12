"""Tabel rclone_remotes (remote rclone multi-akun Google Drive).

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Satu baris = satu remote rclone di .rclone.conf (mis. gdrive, gdrive-2).
    # remote_name unik dan dipakai sebagai nama section di conf.
    op.create_table(
        "rclone_remotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("remote_name", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("remote_name"),
    )


def downgrade() -> None:
    op.drop_table("rclone_remotes")
