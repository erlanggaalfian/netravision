"""Retensi per folder Google Drive (kolom retention_days).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # None = tidak ada hapus otomatis per folder; terisi = hapus file .mp4
    # di folder Drive itu yang lebih tua dari nilai ini (hari).
    op.add_column(
        "google_drive_folders",
        sa.Column("retention_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("google_drive_folders", "retention_days")
