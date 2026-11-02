"""Opsi API key ala v2.0: nama kamera kustom, include_playback, urutan kamera.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("custom_camera_name", sa.String(128), nullable=True, server_default=""),
    )
    op.add_column(
        "api_keys",
        sa.Column("include_playback", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "api_key_streams",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("api_key_streams", "position")
    op.drop_column("api_keys", "include_playback")
    op.drop_column("api_keys", "custom_camera_name")
