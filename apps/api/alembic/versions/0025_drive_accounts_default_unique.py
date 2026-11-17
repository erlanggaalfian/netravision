"""Satu akun Drive default: indeks unik parsial is_default.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A-1.19: tanpa ini, dua POST /admin/drive-accounts bersamaan
    # sama-sama membaca "belum ada akun" dan sama-sama is_default=True.
    # Bila sudah ada >1 default (race lama), sisakan yang tertua.
    op.execute(
        """
        UPDATE drive_accounts SET is_default = false
        WHERE is_default AND id NOT IN (
            SELECT id FROM drive_accounts
            WHERE is_default ORDER BY created_at ASC, id ASC LIMIT 1
        )
        """
    )
    op.create_index(
        "uq_drive_accounts_is_default",
        "drive_accounts",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_drive_accounts_is_default",
        table_name="drive_accounts",
        postgresql_where=sa.text("is_default"),
    )
