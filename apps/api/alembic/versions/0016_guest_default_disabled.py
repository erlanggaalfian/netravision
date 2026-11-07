"""Guest default nonaktif: baris guest dibuat otomatis dan is_active FALSE.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-07
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guest dibuat otomatis oleh sistem dan defaultnya nonaktif.
    # Bila database dihapus lalu migrasi jalan lagi, guest dibuat
    # dalam posisi nonaktif; superadmin mengaktifkannya lewat web
    # (menu Pengguna, switch Login Guest di baris guest).
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id FROM users WHERE username = 'guest'")
    ).first()
    if row is None:
        conn.execute(
            sa.text(
                "INSERT INTO users (username, password_hash, role, is_active, "
                "show_ads, created_at, updated_at) VALUES "
                "('guest', '!', 'guest', FALSE, TRUE, now(), now())"
            )
        )
    else:
        conn.execute(
            sa.text("UPDATE users SET is_active = FALSE WHERE username = 'guest'")
        )


def downgrade() -> None:
    # Kembalikan ke seed migrasi 0011 (guest aktif).
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE users SET is_active = TRUE WHERE username = 'guest'")
    )
