"""Diagnostik tambah kamera: riwayat kegagalan + hasil probe RTSP.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-20

Tabel baru:
- camera_add_failures: satu baris per kegagalan tambah kamera
  (atau registrasi MediaMTX-nya), berisi kode, judul, penyebab,
  dan langkah perbaikan yang sudah di-redact. stream_id NULL bila
  kamera belum sempat tersimpan.
- camera_probe_results: hasil probe RTSP terakhir per kamera
  (upsert per stream_id), main_status dan sub_status.

PostgreSQL-only, seperti migrasi 0030 (JSONB). Downgrade menghapus
kedua tabel.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "camera_add_failures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), nullable=True),
        sa.Column("camera_name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("judul", sa.String(256), nullable=False),
        sa.Column("penyebab", sa.Text(), nullable=False),
        sa.Column("langkah", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_camera_add_failures_stream_created",
        "camera_add_failures",
        ["stream_id", "created_at"],
    )
    op.create_index(
        "ix_camera_add_failures_created_at",
        "camera_add_failures",
        ["created_at"],
    )

    op.create_table(
        "camera_probe_results",
        sa.Column("stream_id", sa.Integer(), primary_key=True),
        sa.Column("camera_name", sa.String(128), nullable=False),
        sa.Column("main_status", sa.String(32), nullable=False),
        sa.Column("sub_status", sa.String(32), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("camera_probe_results")
    op.drop_index(
        "ix_camera_add_failures_created_at", table_name="camera_add_failures"
    )
    op.drop_index(
        "ix_camera_add_failures_stream_created", table_name="camera_add_failures"
    )
    op.drop_table("camera_add_failures")
