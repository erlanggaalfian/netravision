"""Simpan token rclone terenkripsi di DB (kolom token_encrypted).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Token OAuth rclone (JSON) terenkripsi Fernet via DRIVE_TOKEN_KEY.
    # Sumber kebenaran token: bila .rclone.conf hilang (mis. container
    # dibuat ulang tanpa volume), API membangun ulang conf dari kolom ini
    # saat start. NULL untuk remote lama yang tokennya belum tersimpan
    # (mereka perlu dihubungkan ulang sekali).
    op.add_column(
        "rclone_remotes",
        sa.Column("token_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rclone_remotes", "token_encrypted")
