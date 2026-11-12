"""Kaitkan folder tujuan ke akun rclone (kolom remote_name).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nama remote rclone pemilik folder ini (mis. gdrive, gdrive-2).
    # Terisi untuk folder "netravision" yang dibuat otomatis saat akun
    # terhubung; kosong untuk tautan folder manual (kompatibel lama).
    op.add_column(
        "google_drive_folders",
        sa.Column("remote_name", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("google_drive_folders", "remote_name")
