"""Grup kamera + owner stream.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stream_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stream_groups"),
        sa.UniqueConstraint("name", name="uq_stream_groups_name"),
    )
    op.create_table(
        "group_streams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["stream_groups.id"],
            name="fk_group_streams_group_id_stream_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id"],
            ["streams.id"],
            name="fk_group_streams_stream_id_streams",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_group_streams"),
        sa.UniqueConstraint(
            "group_id", "stream_id", name="uq_group_streams_group_id_stream_id"
        ),
    )
    # SQLite tidak mendukung ALTER constraint (create/drop FK) pada tabel
    # yang sudah ada; batch mode membuat ulang tabel bila perlu (G-R6).
    with op.batch_alter_table("streams") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_streams_owner_id_users",
            "users",
            ["owner_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("streams") as batch_op:
        batch_op.drop_constraint("fk_streams_owner_id_users", type_="foreignkey")
        batch_op.drop_column("owner_id")
    op.drop_table("group_streams")
    op.drop_table("stream_groups")
