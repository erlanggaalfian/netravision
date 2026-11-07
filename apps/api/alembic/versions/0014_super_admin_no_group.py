"""Superadmin tidak bisa masuk grup — bersihkan admin_group lama.

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
    # Superadmin berdiri sendiri dan punya semua hak: tidak bisa
    # dimasukkan ke grup. Bersihkan nilai lama bila ada.
    op.execute("UPDATE users SET admin_group = NULL WHERE role = 'super_admin'")


def downgrade() -> None:
    # Nilai lama tidak bisa dikembalikan.
    pass
