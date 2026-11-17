"""Simpan jti refresh token aktif di users (deteksi pemakaian ulang).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 4.2 (Area 4): jti refresh token yang sedang aktif. Bersama
    # refresh_token_hash yang sudah ada, backend bisa membedakan token
    # aktif, token yang baru dirotasi (grace window), dan token lama
    # yang dipakai ulang (reuse -> cabut seluruh keluarga token).
    # NULL untuk semua baris lama: token yang diterbitkan sebelum
    # migrasi ini tidak punya jti tersimpan dan tetap lolos lewat
    # pencocokan hash seperti biasa sampai dirotasi sekali.
    op.add_column(
        "users",
        sa.Column("refresh_token_jti", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "refresh_token_jti")
