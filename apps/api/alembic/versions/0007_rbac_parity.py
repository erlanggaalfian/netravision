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
    # batch_alter_table agar ForeignKey bisa dibuat di SQLite (demo)
    # maupun PostgreSQL (produksi).
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("parent_admin_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_parent_admin_id", "users",
            ["parent_admin_id"], ["id"], ondelete="SET NULL",
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
    with op.batch_alter_table("stream_admin_grants") as batch_op:
        batch_op.add_column(sa.Column("granted_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_stream_admin_grants_granted_by", "users",
            ["granted_by"], ["id"], ondelete="SET NULL",
        )
    # Siapa memasang kamera (dasar masking RTSP, paritas v2.0).
    with op.batch_alter_table("streams") as batch_op:
        batch_op.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_streams_created_by", "users",
            ["created_by"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("streams") as batch_op:
        batch_op.drop_constraint("fk_streams_created_by", type_="foreignkey")
        batch_op.drop_column("created_by")
    with op.batch_alter_table("stream_admin_grants") as batch_op:
        batch_op.drop_constraint("fk_stream_admin_grants_granted_by", type_="foreignkey")
        batch_op.drop_column("granted_by")
    op.drop_column("stream_permissions", "can_playback")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_parent_admin_id", type_="foreignkey")
        batch_op.drop_column("parent_admin_id")
