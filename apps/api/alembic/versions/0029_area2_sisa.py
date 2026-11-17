"""Area 2 sisa (audit backend+database 2026-11-17): baris mati,
tabel/kolom mati.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-17

Cakupan:
- 2.8: hapus baris warisan stream_permissions dengan user_id terisi
  dan role NULL (17 baris di produksi per 2026-11-17). Verifikasi
  kode: tidak satu pun jalur membaca baris itu (_check_camera_access
  di app/core/rbac.py, get_role_access di admin_streams.py, dan
  filter di streams.py/recordings.py semuanya mensyaratkan
  user_id IS NULL; satu-satunya writer set_role_access selalu
  membuat user_id=None). Baris itu tidak memberi akses nyata, jadi
  penghapusan aman. CHECK baru mencegah bentuk mati itu dibuat lagi.
- 2.10: hapus tabel detection_events dan alerts (0 baris di produksi,
  tanpa writer/reader di luar model; modul detektor Fase 6 belum
  pernah dibangun) dan kolom mati stream_permissions.can_download,
  user_stream_access.can_control, stream_admin_grants.can_manage
  (tidak pernah dibaca di luar definisi model; can_manage masih
  ditulis True dan dikembalikan mentah di API, referensinya dihapus
  koordinator bersamaan).
- 2.10 (drive_accounts): TIDAK dihapus. Verifikasi kode: jalur OAuth
  Drive masih hidup (app/services/drive_accounts.py:
  resolve_drive_account, get_drive_client, active_uploaders dipakai
  _drive_loop di main.py dan uploader_for_stream di recordings.py;
  admin_drive.py punya CRUD + callback OAuth penuh). Tabel 0 baris
  dan streams.drive_account_id NULL di 68/68 kamera hanya berarti
  belum ada akun terhubung, bukan jalurnya mati.
- 2.12 dan 2.19: tanpa DDL (endpoint di routers/admin_audit.py;
  statement_timeout di app/db/session.py).

KEAMANAN PRODUKSI:
- Baris stream_permissions yang dihapus HANYA bentuk mati persis
  (user_id IS NOT NULL AND role IS NULL). Bila ada baris user_id
  terisi DENGAN role (bentuk yang tidak ada di produksi saat audit),
  migrasi GAGAL KERAS sebelum menghapus apa pun, supaya bentuk baru
  yang mungkin dipakai fitur lain tidak hilang diam-diam.
- detection_events/alerts hanya di-drop bila 0 baris; ada baris =
  gagal keras.
- Downgrade membuat lagi kedua tabel (kosong) dan ketiga kolom, dan
  melepas CHECK. Baris stream_permissions yang dihapus TIDAK bisa
  dikembalikan oleh downgrade (sengaja: baris itu terbukti mati).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(conn, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def _has_constraint(conn, table: str, name: str) -> bool:
    return any(
        c["name"] == name
        for c in inspect(conn).get_unique_constraints(table)
        + inspect(conn).get_check_constraints(table)
        + inspect(conn).get_foreign_keys(table)
    )


def _add_check_not_valid_then_validate(
    conn, table: str, name: str, condition: str
) -> None:
    """Tambah CHECK sebagai NOT VALID lalu VALIDATE (aman produksi).

    VALIDATE gagal keras bila ada baris yang melanggar, tanpa
    menghapus data apa pun.
    """
    if _has_constraint(conn, table, name):
        return
    conn.execute(
        sa.text(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"CHECK ({condition}) NOT VALID"
        )
    )
    conn.execute(sa.text(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}"))


def upgrade() -> None:
    conn = op.get_bind()

    # -- 2.8: hapus baris warisan mati (user_id terisi, role NULL).
    #    Bentuk lain (user_id terisi DENGAN role) tidak dikenal audit:
    #    tolak migrasi supaya tidak terhapus diam-diam.
    unknown_shape = conn.execute(
        sa.text(
            "SELECT count(*) FROM stream_permissions "
            "WHERE user_id IS NOT NULL AND role IS NOT NULL"
        )
    ).scalar()
    if unknown_shape:
        raise RuntimeError(
            "migrasi 0029 ditolak: stream_permissions berisi "
            f"{unknown_shape} baris user_id terisi DENGAN role "
            "(bentuk baru, bukan warisan mati). Periksa dulu apakah "
            "ada fitur yang memakai baris per-user, lalu ulangi migrasi."
        )
    conn.execute(
        sa.text(
            "DELETE FROM stream_permissions "
            "WHERE user_id IS NOT NULL AND role IS NULL"
        )
    )
    # Cegah baris mati dibuat lagi (writer saat ini selalu
    # user_id=None, jadi CHECK ini tidak mengubah perilaku berjalan).
    _add_check_not_valid_then_validate(
        conn,
        "stream_permissions",
        "ck_stream_permissions_user_row_needs_role",
        "user_id IS NULL OR role IS NOT NULL",
    )

    # -- 2.10: hapus tabel deteksi/alert (0 baris; ada baris = tolak).
    for table in ("detection_events", "alerts"):
        if table in inspect(conn).get_table_names():
            n = conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
            if n:
                raise RuntimeError(
                    f"migrasi 0029 ditolak: {table} berisi {n} baris "
                    "(audit mencatat 0 baris). Arsipkan dulu bila "
                    "datanya dibutuhkan, lalu ulangi migrasi."
                )
    # alerts dulu: FK event_id menunjuk detection_events.
    if "alerts" in inspect(conn).get_table_names():
        op.drop_table("alerts")
    if "detection_events" in inspect(conn).get_table_names():
        op.drop_table("detection_events")

    # -- 2.10: hapus kolom mati.
    if _has_column(conn, "stream_permissions", "can_download"):
        op.drop_column("stream_permissions", "can_download")
    if _has_column(conn, "user_stream_access", "can_control"):
        op.drop_column("user_stream_access", "can_control")
    if _has_column(conn, "stream_admin_grants", "can_manage"):
        op.drop_column("stream_admin_grants", "can_manage")


def downgrade() -> None:
    conn = op.get_bind()

    # Kembalikan ketiga kolom mati (nilai default sama seperti 0001).
    if not _has_column(conn, "stream_permissions", "can_download"):
        op.add_column(
            "stream_permissions",
            sa.Column(
                "can_download", sa.Boolean(), nullable=False,
                server_default=sa.false(),
            ),
        )
    if not _has_column(conn, "user_stream_access", "can_control"):
        op.add_column(
            "user_stream_access",
            sa.Column(
                "can_control", sa.Boolean(), nullable=False,
                server_default=sa.false(),
            ),
        )
    if not _has_column(conn, "stream_admin_grants", "can_manage"):
        op.add_column(
            "stream_admin_grants",
            sa.Column(
                "can_manage", sa.Boolean(), nullable=False,
                server_default=sa.true(),
            ),
        )

    # Kembalikan kedua tabel (kosong, DDL sama seperti 0001).
    # Baris stream_permissions yang dihapus upgrade TIDAK kembali.
    if "detection_events" not in inspect(conn).get_table_names():
        op.create_table(
            "detection_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("stream_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column(
                "detected_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("snapshot_path", sa.String(512), nullable=True),
            sa.Column(
                "meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True
            ),
            sa.ForeignKeyConstraint(
                ["stream_id"], ["streams.id"], ondelete="CASCADE",
                name="fk_detection_events_stream_id_streams",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_detection_events"),
        )
        op.create_index(
            "ix_detection_events_detected_at", "detection_events", ["detected_at"]
        )
    if "alerts" not in inspect(conn).get_table_names():
        op.create_table(
            "alerts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("stream_id", sa.Integer(), nullable=True),
            sa.Column("event_id", sa.Integer(), nullable=True),
            sa.Column("message", sa.String(512), nullable=False),
            sa.Column(
                "is_read", sa.Boolean(), nullable=False,
                server_default=sa.false(),
            ),
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
                ["user_id"], ["users.id"], ondelete="CASCADE",
                name="fk_alerts_user_id_users",
            ),
            sa.ForeignKeyConstraint(
                ["stream_id"], ["streams.id"], ondelete="SET NULL",
                name="fk_alerts_stream_id_streams",
            ),
            sa.ForeignKeyConstraint(
                ["event_id"], ["detection_events.id"], ondelete="SET NULL",
                name="fk_alerts_event_id_detection_events",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        )

    # Lepas CHECK pencegah baris mati. DROP CONSTRAINT lewat SQL
    # mentah: op.drop_constraint(type_="check") memberi prefix nama
    # tabel pada nama constraint (lihat downgrade 0027), sehingga
    # gagal dengan "constraint ck_<tabel>_<nama> does not exist".
    if _has_constraint(conn, "stream_permissions", "ck_stream_permissions_user_row_needs_role"):
        conn.execute(
            sa.text(
                "ALTER TABLE stream_permissions DROP CONSTRAINT "
                "ck_stream_permissions_user_row_needs_role"
            )
        )
