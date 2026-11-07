"""can_view/can_playback/can_reshare di stream_admin_grants (paritas v2.0).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-07
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Paritas v2.0 (StreamAdminGrantModel): live, playback, dan izin
    # meneruskan kamera ke bawahan dipisah. Default True agar grant
    # yang sudah ada tetap berperilaku sama.
    for col in ("can_view", "can_playback", "can_reshare"):
        op.add_column(
            "stream_admin_grants",
            sa.Column(col, sa.Boolean(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    for col in ("can_view", "can_playback", "can_reshare"):
        op.drop_column("stream_admin_grants", col)
