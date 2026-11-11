"""Guest default nonaktif: baris guest dibuat otomatis dan is_active FALSE.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-07

CATATAN (G-T3): versi lama file ini menjalankan
`UPDATE users SET is_active = FALSE WHERE username = 'guest'` pada baris
guest yang SUDAH ADA, sehingga server yang upgrade dari 0015 ke 0016
dengan guest yang sengaja diaktifkan operator menjadi terkunci tanpa
pemberitahuan. Versi ini HANYA menonaktifkan baris guest yang BARU dibuat
(cabang INSERT); baris yang sudah ada tidak disentuh. Server yang sudah
menjalankan 0016 lama dan guest-nya mati karenanya harus mengaktifkan
guest MANUAL lewat web (menu Pengguna, switch Login Guest di baris guest)
bila memang menginginkannya - tidak ada migrasi korektif yang
mengaktifkan ulang otomatis, karena tidak bisa dibedakan apakah
nonaktif itu pilihan operator atau akibat migrasi lama.
"""
from collections.abc import Sequence
from datetime import datetime, timezone

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
        # Hanya baris guest BARU yang dibuat nonaktif. Baris guest yang
        # sudah ada TIDAK disentuh: operator mungkin sudah sengaja
        # mengaktifkannya, dan migrasi tidak boleh mematikannya paksa
        # (G-T3: versi lama migrasi ini menonaktifkan guest yang aktif).
        conn.execute(
            sa.text(
                "INSERT INTO users (username, password_hash, role, is_active, "
                "show_ads, created_at, updated_at) VALUES "
                "('guest', '!', 'guest', FALSE, TRUE, :now, :now)"
            ),
            {"now": datetime.now(timezone.utc)},
        )
    # else: biarkan apa adanya (aktif tetap aktif, nonaktif tetap nonaktif).


def downgrade() -> None:
    # Kembalikan ke seed migrasi 0011 (guest aktif).
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE users SET is_active = TRUE WHERE username = 'guest'")
    )
