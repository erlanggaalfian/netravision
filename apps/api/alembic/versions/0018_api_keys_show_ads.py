"""Kolom show_ads di api_keys (opsi iklan per API key).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Default True supaya kunci yang sudah ada tetap menampilkan iklan
    # (perilaku lama dipertahankan); hanya kunci yang dimatikan eksplisit
    # yang embed-nya tanpa iklan.
    op.add_column(
        "api_keys",
        sa.Column("show_ads", sa.Boolean(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "show_ads")
