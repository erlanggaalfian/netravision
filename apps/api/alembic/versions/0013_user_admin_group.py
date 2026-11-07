"""admin_group di users — kelompok wilayah akun (paritas v2.0).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-07
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Kelompok wilayah akun (paritas v2.0). Akun dengan nama grup yang
    # sama saling mengelola; lintas grup tertutup. Kosong = belum
    # berkelompok, hanya Super Admin yang menjangkaunya. Tidak ada
    # hubungannya dengan group_name kamera.
    op.add_column("users", sa.Column("admin_group", sa.String(60), nullable=True))
    op.create_index("ix_users_admin_group", "users", ["admin_group"])


def downgrade() -> None:
    op.drop_index("ix_users_admin_group", table_name="users")
    op.drop_column("users", "admin_group")
