"""Paritas RBAC v2.0: parent_admin_id, can_playback, granted_by, created_by.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Admin pembuat akun (cakupan kelola admin, paritas v2.0).
    op.add_column(
        "users",
        sa.Column(
            "parent_admin_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    # Izin playback terpisah dari izin tonton (paritas v2.0).
    # Default True agar grant lama tidak berubah perilaku.
    op.add_column(
        "stream_permissions",
        sa.Column(
            "can_playback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # Pencatat pemberi grant admin (paritas v2.0).
    op.add_column(
        "stream_admin_grants",
        sa.Column(
            "granted_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Siapa memasang kamera (dasar masking RTSP, paritas v2.0).
    # Model menyusul via _rbac_patch_notes.md; kode toleran bila belum ada.
    op.add_column(
        "streams",
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("streams", "created_by")
    op.drop_column("stream_admin_grants", "granted_by")
    op.drop_column("stream_permissions", "can_playback")
    op.drop_column("users", "parent_admin_id")
