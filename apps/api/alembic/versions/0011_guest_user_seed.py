"""Akun guest persisten — tampil di menu Pengguna agar show_ads bisa diatur.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-06
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guest login v2.0 bersifat ephemeral (tanpa baris DB), sehingga tidak
    # muncul di menu Pengguna dan show_ads-nya hardcoded True. Seed satu
    # baris guest agar superadmin bisa mengatur iklan untuk guest di sana.
    # password_hash tidak bisa dipakai login (guest login pakai token
    # ephemeral + GUEST_PASSWORD), diisi hash acak yang tidak valid.
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM users WHERE username = 'guest'")
    ).first()
    if not exists:
        conn.execute(
            sa.text(
                "INSERT INTO users (username, password_hash, role, is_active, "
                "show_ads, created_at, updated_at) VALUES "
                "('guest', '!', 'guest', TRUE, TRUE, now(), now())"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM users WHERE username = 'guest'"))
