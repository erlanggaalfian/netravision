"""can_playback di user_stream_access — share stream saja vs stream+playback.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-06
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Default TRUE agar share yang sudah ada tetap berperilaku sama
    # (stream + playback), sampai superadmin mengubahnya per user.
    op.add_column(
        "user_stream_access",
        sa.Column("can_playback", sa.Boolean(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("user_stream_access", "can_playback")
