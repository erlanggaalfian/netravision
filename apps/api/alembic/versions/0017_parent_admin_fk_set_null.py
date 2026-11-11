"""Korektif G-S8: FK users.parent_admin_id jadi ondelete SET NULL.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-11

Migrasi 0007 membuat FK parent_admin_id tanpa ondelete (default NO ACTION),
berbeda dengan FK granted_by dan created_by di file yang sama yang memakai
SET NULL - menghapus admin pembuat gagal (FK violation) selama masih ada
akun buatannya. Karena 0007 sudah ter-apply di server, perbaikan file 0007
saja tidak cukup: migrasi korektif ini mengubah FK di DB yang sudah upgrade.
Deploy baru tetap aman: 0007 yang sudah diperbaiki membuat FK SET NULL,
lalu migrasi ini men-drop dan membuatnya ulang dengan definisi yang sama.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_parent_admin_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_users_parent_admin_id", "users",
            ["parent_admin_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_parent_admin_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_users_parent_admin_id", "users",
            ["parent_admin_id"], ["id"],
        )
