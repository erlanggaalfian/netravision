"""Kolom record_disk di streams (rekaman multi-disk).

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Mount point disk tujuan rekaman per kamera (mis. "/mnt/disk2").
    # Kosong = pakai recordings_dir default (perilaku lama dipertahankan).
    op.add_column(
        "streams",
        sa.Column("record_disk", sa.String(100), nullable=True, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("streams", "record_disk")
