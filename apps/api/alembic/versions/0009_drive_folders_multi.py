"""Drive folder-link jadi multi-tautan + drive_folder_id per kamera.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_drive_folders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("folder_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("folder_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("folder_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("local_path", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(50), nullable=True, server_default=""),
        sa.PrimaryKeyConstraint("id"),
    )
    # Pindahkan baris tunggal lama (bila ada) jadi folder pertama.
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "google_drive_settings" in insp.get_table_names():
        rows = conn.execute(
            sa.text(
                "SELECT folder_url, folder_id, folder_name, updated_at, updated_by"
                " FROM google_drive_settings WHERE folder_id IS NOT NULL"
                " AND folder_id != '' LIMIT 1"
            )
        ).fetchall()
        for r in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO google_drive_folders"
                    " (folder_url, folder_id, folder_name, local_path, updated_at, updated_by)"
                    " VALUES (:u, :f, :n, '', :t, :b)"
                ),
                {"u": r[0] or "", "f": r[1] or "", "n": r[2] or "",
                 "t": r[3], "b": r[4] or ""},
            )
        op.drop_table("google_drive_settings")
    # Folder tujuan per kamera (NULL = folder pertama).
    with op.batch_alter_table("streams") as batch_op:
        batch_op.add_column(sa.Column("drive_folder_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_streams_drive_folder_id", "google_drive_folders",
            ["drive_folder_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("streams") as batch_op:
        batch_op.drop_constraint("fk_streams_drive_folder_id", type_="foreignkey")
        batch_op.drop_column("drive_folder_id")
    op.drop_table("google_drive_folders")
