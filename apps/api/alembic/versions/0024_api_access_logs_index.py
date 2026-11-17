"""Indeks log akses embed (api_key_id, created_at).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-17

Area 6 temuan 6.8: list_logs memfilter api_key_id dan mengurutkan
created_at, dan menghitung total per halaman; tanpa indeks gabungan
ini tiap halaman memindai seluruh tabel api_access_logs yang tumbuh
tanpa batas (hanya ada ix_api_access_logs_created_at).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_api_access_logs_key_created",
        "api_access_logs",
        ["api_key_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_access_logs_key_created", table_name="api_access_logs")
