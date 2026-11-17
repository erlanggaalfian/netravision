"""Area 2 (audit backend+database 2026-11-17): FK/unique/indeks/check/retensi.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-17

Cakupan temuan Area 2 yang diperbaiki di sini:
- 2.1: FK drive_uploads.stream_id -> streams.id ON DELETE CASCADE +
  unique (stream_id, folder_name, segment_name).
- 2.2: retensi jejak upload (lihat prune_drive_upload_traces di
  app/services/drive_uploader.py, dipanggil harian dari
  _retention_loop); migrasi ini hanya menyiapkan skema.
- 2.4: indeks komposit drive_uploads (stream_id, uploaded_at).
- 2.5: indeks + unique stream_permissions (NULLS NOT DISTINCT).
- 2.6: indeks kolom kedua FK (user_stream_access, api_key_streams,
  group_streams, stream_admin_grants).
- 2.7: kolom api_access_logs.is_denied + indeks stream_id (indeks
  (api_key_id, created_at) sudah dibuat migrasi 0024 Area 6).
- 2.9: drive_uploads.folder_id diganti nama menjadi folder_name
  (isinya memang NAMA folder, bukan ID Drive).
- 2.11: DROP tabel backup _backup_0014_super_admin_group (0 baris di
  produksi per 2026-11-17; downgrade 0027 membuatnya lagi kosong).
- 2.12: indeks audit_logs (actor_id, created_at) dan
  (resource, created_at).
- 2.13: normalisasi sentinel '' -> NULL (streams.record_disk,
  api_keys.custom_camera_name, google_drive_folders.updated_by)
  + hapus server_default '' ketiganya.
- 2.14: api_access_logs.created_at memakai server_default now();
  GoogleDriveFolder.updated_at onupdate (level ORM, tanpa DDL).
- 2.15: CHECK users.role, streams.storage_mode,
  drive_accounts.status, stream_permissions.role.
- 2.18: indeks streams (is_active) dan (storage_mode,
  recording_enabled).
- 2.20: kolom ad_config.created_at.

KEAMANAN PRODUKSI (cek read-only 2026-11-17, sebelum migrasi):
- drive_uploads 11.098 baris: 0 grup duplikat (stream_id, folder_id,
  segment_name), 0 baris yatim (stream_id tanpa streams.id), nilai
  folder_id hanya 'netravision'. Dedup di bawah ini idempotent dan
  hanya menghapus duplikat persis bila ada (saat ini tidak ada).
- stream_permissions 17 baris, semua user_id terisi + role NULL,
  0 grup duplikat (cek ini sudah memakai semantik GROUP BY yang
  menyamakan NULL, sama seperti NULLS NOT DISTINCT).
- users.role di produksi: admin, guest, super_admin; storage_mode:
  drive, local; drive_accounts: 0 baris; _backup_0014: 0 baris;
  super_admin dengan admin_group: 0. Semua lolos CHECK di bawah.
- Guest produksi BUKAN seed migrasi (hash bcrypt, dibuat 2026-07-01),
  jadi downgrade 0011 yang diperbaiki tidak akan menghapusnya.

CARA AMAN DI PRODUKSI:
- Indeks biasa dibuat CONCURRENTLY (tanpa menahan tulis); unique
  constraint dibuat langsung karena tabel kecil (11 ribu baris,
  kunci sesaat) dan unique tidak mendukung NOT VALID.
- FK dan CHECK dibuat NOT VALID lalu VALIDATE, supaya pembuatan
  tidak memindai tabel sambil menahan tulis; VALIDATE gagal keras
  bila ada baris yatim/nilai di luar CHECK (tidak ada data yang
  dihapus diam-diam).
- Bila migrasi ini gagal di VALIDATE, perbaiki datanya dulu secara
  manual, lalu jalankan lagi (langkah dedup/normalisasi idempotent).

CATATAN RANTAI REVISI: rantai saat ini 0024 (Area 6, indeks
api_access_logs) -> 0025 (Area 1, default akun Drive) -> 0026
(refresh_token_jti) -> 0027 (migrasi ini). Nomor 0027 dipilih karena
0025 sudah dipakai migrasi Area 1 sehingga 0025 ganda bila dipakai
juga di sini; bila ada migrasi baru dari area lain, rebase 0027 ke
head terbaru.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(conn, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def _has_index(conn, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in inspect(conn).get_indexes(table))


def _has_constraint(conn, table: str, name: str) -> bool:
    return any(
        c["name"] == name
        for c in inspect(conn).get_unique_constraints(table)
        + inspect(conn).get_check_constraints(table)
        + inspect(conn).get_foreign_keys(table)
    )


def _add_constraint_not_valid_then_validate(
    conn, table: str, name: str, ddl: str
) -> None:
    """Tambah FK/CHECK sebagai NOT VALID lalu VALIDATE (aman produksi).

    `ddl` adalah pernyataan ALTER TABLE ... ADD CONSTRAINT ... NOT VALID
    lengkap. VALIDATE gagal keras bila ada baris yang melanggar, tanpa
    menghapus data apa pun.
    """
    if _has_constraint(conn, table, name):
        return
    conn.execute(sa.text(ddl))
    conn.execute(sa.text(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}"))


def _create_index_concurrently(conn, name: str, table: str, columns: str, extra: str = "") -> None:
    """CREATE INDEX CONCURRENTLY IF NOT EXISTS di luar transaksi.

    Harus dipanggil di dalam autocommit_block; bila dipanggil dalam
    transaksi biasa PostgreSQL menolaknya.
    """
    with op.get_context().autocommit_block():
        conn.execute(
            sa.text(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {table} ({columns}){extra}"
            )
        )


def upgrade() -> None:
    conn = op.get_bind()

    # -- 2.1: dedup jejak persis (idempotent; saat ini 0 di produksi).
    #    Hanya baris kembar persis yang dihapus, simpan id terkecil.
    conn.execute(
        sa.text(
            "DELETE FROM drive_uploads u USING drive_uploads d "
            "WHERE u.stream_id = d.stream_id "
            "AND u.folder_id = d.folder_id "
            "AND u.segment_name = d.segment_name AND u.id > d.id"
        )
    )

    # -- 2.13: normalisasi sentinel '' -> NULL (idempotent).
    conn.execute(sa.text("UPDATE streams SET record_disk = NULL WHERE record_disk = ''"))
    conn.execute(
        sa.text(
            "UPDATE api_keys SET custom_camera_name = NULL "
            "WHERE custom_camera_name = ''"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE google_drive_folders SET updated_by = NULL WHERE updated_by = ''"
        )
    )
    # Hapus server_default '' supaya insert mentah berikutnya dapat NULL.
    for table, column in (
        ("streams", "record_disk"),
        ("api_keys", "custom_camera_name"),
        ("google_drive_folders", "updated_by"),
    ):
        op.alter_column(table, column, server_default=None)

    # -- 2.11: hapus tabel backup 0014 (0 baris; ada baris = tolak).
    if "_backup_0014_super_admin_group" in inspect(conn).get_table_names():
        n = conn.execute(
            sa.text("SELECT count(*) FROM _backup_0014_super_admin_group")
        ).scalar()
        if n:
            raise RuntimeError(
                "migrasi 0027 ditolak: _backup_0014_super_admin_group berisi "
                f"{n} baris (admin_group super_admin lama masih butuh "
                "restore). Pulihkan manual dulu, lalu ulangi migrasi."
            )
        op.drop_table("_backup_0014_super_admin_group")

    # -- 2.7: kolom is_denied + backfill dari action lama.
    if not _has_column(conn, "api_access_logs", "is_denied"):
        op.add_column(
            "api_access_logs",
            sa.Column("is_denied", sa.Boolean(), nullable=False, server_default="false"),
        )
    conn.execute(
        sa.text(
            "UPDATE api_access_logs SET is_denied = TRUE "
            "WHERE action LIKE '%.denied%'"
        )
    )

    # -- 2.20: AdConfig.created_at.
    if not _has_column(conn, "ad_config", "created_at"):
        op.add_column(
            "ad_config",
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    # -- 2.14: created_at log akses memakai default server.
    op.alter_column(
        "api_access_logs", "created_at", server_default=sa.func.now()
    )

    # -- 2.9: folder_id -> folder_name (isinya memang nama folder).
    if _has_column(conn, "drive_uploads", "folder_id"):
        with op.batch_alter_table("drive_uploads") as batch_op:
            batch_op.alter_column("folder_id", new_column_name="folder_name")

    # -- 2.1: FK stream_id -> streams.id ON DELETE CASCADE.
    #    Yatim dicek dulu supaya pesan gagalnya jelas; VALIDATE di
    #    bawah tetap menjadi penjaga kedua (tidak ada data dihapus).
    orphans = conn.execute(
        sa.text(
            "SELECT count(*) FROM drive_uploads u "
            "LEFT JOIN streams s ON s.id = u.stream_id WHERE s.id IS NULL"
        )
    ).scalar()
    if orphans:
        raise RuntimeError(
            "migrasi 0027 ditolak: drive_uploads punya "
            f"{orphans} baris yatim (stream_id tanpa streams.id). "
            "Hapus atau perbaiki baris itu secara manual dulu."
        )
    _add_constraint_not_valid_then_validate(
        conn,
        "drive_uploads",
        "fk_drive_uploads_stream_id",
        "ALTER TABLE drive_uploads ADD CONSTRAINT fk_drive_uploads_stream_id "
        "FOREIGN KEY (stream_id) REFERENCES streams (id) ON DELETE CASCADE NOT VALID",
    )

    # -- 2.1: unique (stream_id, folder_name, segment_name).
    if not _has_constraint(conn, "drive_uploads", "uq_drive_uploads_stream_folder_segment"):
        op.create_unique_constraint(
            "uq_drive_uploads_stream_folder_segment",
            "drive_uploads",
            ["stream_id", "folder_name", "segment_name"],
        )

    # -- 2.5: unique stream_permissions (NULLS NOT DISTINCT).
    if not _has_constraint(
        conn, "stream_permissions", "uq_stream_permissions_stream_role_user"
    ):
        op.create_unique_constraint(
            "uq_stream_permissions_stream_role_user",
            "stream_permissions",
            ["stream_id", "role", "user_id"],
            postgresql_nulls_not_distinct=True,
        )

    # -- 2.15: CHECK constraints (NOT VALID + VALIDATE).
    _add_constraint_not_valid_then_validate(
        conn,
        "users",
        "ck_users_role",
        "ALTER TABLE users ADD CONSTRAINT ck_users_role "
        "CHECK (role IN ('super_admin', 'admin', 'user', 'guest')) NOT VALID",
    )
    _add_constraint_not_valid_then_validate(
        conn,
        "streams",
        "ck_streams_storage_mode",
        "ALTER TABLE streams ADD CONSTRAINT ck_streams_storage_mode "
        "CHECK (storage_mode IN ('local', 'drive', 'both')) NOT VALID",
    )
    _add_constraint_not_valid_then_validate(
        conn,
        "drive_accounts",
        "ck_drive_accounts_status",
        "ALTER TABLE drive_accounts ADD CONSTRAINT ck_drive_accounts_status "
        "CHECK (status IN ('pending', 'connected', 'error')) NOT VALID",
    )
    _add_constraint_not_valid_then_validate(
        conn,
        "stream_permissions",
        "ck_stream_permissions_role",
        "ALTER TABLE stream_permissions ADD CONSTRAINT ck_stream_permissions_role "
        "CHECK (role IN ('admin', 'user', 'guest')) NOT VALID",
    )

    # -- Indeks biasa: CONCURRENTLY (tanpa menahan tulis).
    #    2.4: (stream_id, uploaded_at) untuk MAX(uploaded_at).
    _create_index_concurrently(
        conn, "ix_drive_uploads_stream_uploaded", "drive_uploads",
        "stream_id, uploaded_at",
    )
    #    2.5: cek akses panas (stream_id, role) khusus baris peran.
    _create_index_concurrently(
        conn, "ix_stream_permissions_stream_role", "stream_permissions",
        "stream_id, role", " WHERE user_id IS NULL",
    )
    #    2.6: indeks kolom kedua FK.
    _create_index_concurrently(
        conn, "ix_user_stream_access_stream_id", "user_stream_access", "stream_id"
    )
    _create_index_concurrently(
        conn, "ix_api_key_streams_stream_id", "api_key_streams", "stream_id"
    )
    _create_index_concurrently(
        conn, "ix_group_streams_stream_id", "group_streams", "stream_id"
    )
    _create_index_concurrently(
        conn, "ix_stream_admin_grants_admin_id", "stream_admin_grants", "admin_id"
    )
    #    2.7: filter log per stream_id.
    _create_index_concurrently(
        conn, "ix_api_access_logs_stream_id", "api_access_logs", "stream_id"
    )
    #    2.12: filter audit_logs.
    _create_index_concurrently(
        conn, "ix_audit_logs_actor_created", "audit_logs", "actor_id, created_at"
    )
    _create_index_concurrently(
        conn, "ix_audit_logs_resource_created", "audit_logs", "resource, created_at"
    )
    #    2.18: filter streams yang sering dipakai.
    _create_index_concurrently(
        conn, "ix_streams_is_active", "streams", "is_active"
    )
    _create_index_concurrently(
        conn, "ix_streams_storage_recording", "streams",
        "storage_mode, recording_enabled",
    )


def downgrade() -> None:
    conn = op.get_bind()

    for name, table in (
        ("ix_streams_storage_recording", "streams"),
        ("ix_streams_is_active", "streams"),
        ("ix_audit_logs_resource_created", "audit_logs"),
        ("ix_audit_logs_actor_created", "audit_logs"),
        ("ix_api_access_logs_stream_id", "api_access_logs"),
        ("ix_stream_admin_grants_admin_id", "stream_admin_grants"),
        ("ix_group_streams_stream_id", "group_streams"),
        ("ix_api_key_streams_stream_id", "api_key_streams"),
        ("ix_user_stream_access_stream_id", "user_stream_access"),
        ("ix_stream_permissions_stream_role", "stream_permissions"),
        ("ix_drive_uploads_stream_uploaded", "drive_uploads"),
    ):
        if _has_index(conn, table, name):
            op.drop_index(name, table_name=table)

    # DROP CONSTRAINT lewat SQL mentah: op.drop_constraint(type_="check")
    # memberi prefix nama tabel pada nama constraint (Alembic mengira
    # nama itu dibuat dari naming convention), sehingga gagal dengan
    # "constraint ck_<tabel>_<nama> does not exist".
    for name, table in (
        ("ck_stream_permissions_role", "stream_permissions"),
        ("ck_drive_accounts_status", "drive_accounts"),
        ("ck_streams_storage_mode", "streams"),
        ("ck_users_role", "users"),
        ("uq_stream_permissions_stream_role_user", "stream_permissions"),
        ("uq_drive_uploads_stream_folder_segment", "drive_uploads"),
        ("fk_drive_uploads_stream_id", "drive_uploads"),
    ):
        if _has_constraint(conn, table, name):
            conn.execute(
                sa.text(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
            )

    # Kembalikan nama kolom 2.9 (data tetap nama folder).
    if _has_column(conn, "drive_uploads", "folder_name"):
        with op.batch_alter_table("drive_uploads") as batch_op:
            batch_op.alter_column("folder_name", new_column_name="folder_id")

    op.alter_column("api_access_logs", "created_at", server_default=None)
    if _has_column(conn, "ad_config", "created_at"):
        op.drop_column("ad_config", "created_at")
    if _has_column(conn, "api_access_logs", "is_denied"):
        op.drop_column("api_access_logs", "is_denied")

    # Buat lagi tabel backup 0014 (kosong) supaya downgrade 0014 yang
    # membutuhkannya tetap bisa jalan.
    if "_backup_0014_super_admin_group" not in inspect(conn).get_table_names():
        op.create_table(
            "_backup_0014_super_admin_group",
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("admin_group", sa.String(128), nullable=True),
            sa.PrimaryKeyConstraint("user_id"),
        )

    # Kembalikan server_default '' (nilai data yang sudah jadi NULL
    # sengaja tidak dikembalikan ke '').
    for table, column in (
        ("streams", "record_disk"),
        ("api_keys", "custom_camera_name"),
        ("google_drive_folders", "updated_by"),
    ):
        op.alter_column(table, column, server_default="")
