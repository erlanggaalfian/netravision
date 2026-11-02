"""Jejak upload Drive (drive_uploads) — cegah upload ganda.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drive_uploads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("segment_name", sa.String(64), nullable=False),
        sa.Column("folder_id", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_drive_uploads_stream_id", "drive_uploads", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_drive_uploads_stream_id", table_name="drive_uploads")
    op.drop_table("drive_uploads")
