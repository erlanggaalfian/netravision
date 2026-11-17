"""Tabel system_settings (kredensial internal di database).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-17

MEDIAMTX_API_PASSWORD dibuat saat deploy / install pertama dan
disimpan di database (bukan .env). Tabel ini menampungnya (key
'mediamtx_api_password'). Password dibuat oleh backend saat startup
(app/services/system_settings.py) atau oleh deploy (service migrate,
app/db/setup_mediamtx.py), BUKAN oleh migrasi ini, supaya pembuatan
password tetap idempotent dan terpusat di satu tempat.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
