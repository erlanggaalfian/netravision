"""Superadmin tidak bisa masuk grup - bersihkan admin_group lama.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-07
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Simpan dulu nilai admin_group lama super_admin ke tabel backup
    # sementara, supaya downgrade bisa mengembalikannya (G-S4: downgrade
    # lama hanya `pass` dan nilai hilang permanen).
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "_backup_0014_super_admin_group" not in insp.get_table_names():
        op.create_table(
            "_backup_0014_super_admin_group",
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("admin_group", sa.String(128), nullable=True),
            sa.PrimaryKeyConstraint("user_id"),
        )
    conn.execute(
        sa.text(
            "INSERT INTO _backup_0014_super_admin_group (user_id, admin_group)"
            " SELECT id, admin_group FROM users"
            " WHERE role = 'super_admin' AND admin_group IS NOT NULL"
        )
    )
    # Superadmin berdiri sendiri dan punya semua hak: tidak bisa
    # dimasukkan ke grup. Bersihkan nilai lama bila ada.
    op.execute("UPDATE users SET admin_group = NULL WHERE role = 'super_admin'")


def downgrade() -> None:
    # Kembalikan nilai admin_group lama dari tabel backup, lalu hapus
    # tabel backupnya. Bila tabel backup tidak ada (mis. upgrade lama
    # sebelum perbaikan ini), tolak dengan pesan jelas daripada
    # menghilangkan data diam-diam.
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "_backup_0014_super_admin_group" not in insp.get_table_names():
        raise RuntimeError(
            "downgrade 0014 ditolak: tabel backup _backup_0014_super_admin_group "
            "tidak ada (upgrade dijalankan sebelum perbaikan G-S4), sehingga "
            "admin_group super_admin lama tidak bisa dikembalikan dengan aman. "
            "Isi manual admin_group super_admin bila perlu, lalu buat ulang "
            "tabel backup kosong dan ulangi downgrade."
        )
    conn.execute(
        sa.text(
            "UPDATE users SET admin_group = "
            "(SELECT admin_group FROM _backup_0014_super_admin_group"
            " WHERE _backup_0014_super_admin_group.user_id = users.id)"
            " WHERE role = 'super_admin' AND id IN"
            " (SELECT user_id FROM _backup_0014_super_admin_group)"
        )
    )
    op.drop_table("_backup_0014_super_admin_group")
