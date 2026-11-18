"""Area 3 (code review 2026-11-18): indeks FK, CHECK, unik folder, enkripsi system_settings.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-18

Cakupan:
- Indeks FK yang dipakai query panas (sebelumnya seq scan):
  streams(owner_id, created_by, drive_account_id, drive_folder_id),
  users(parent_admin_id, role),
  google_drive_folders(folder_id, remote_name),
  api_access_logs(api_key_id, is_denied, created_at),
  drive_uploads(uploaded_at).
- Hapus indeks redundan ix_drive_uploads_stream_id (unique +
  komposit di atas keduanya berawalan stream_id) dan indeks mati
  ix_streams_group_name (kolom group_name tidak pernah difilter,
  hanya dibaca untuk tampilan/path).
- CHECK (NOT VALID lalu VALIDATE, pola 0027/0029):
  streams.retention_days >= 0,
  google_drive_folders.retention_days >= 0 (NULL lolos),
  api_keys.session_ttl_mnt IS NULL OR > 0,
  users.parent_admin_id IS NULL OR parent_admin_id <> id.
- Unik folder Drive: indeks unik PARSIAL folder_id WHERE
  folder_id <> '' — satu folder Drive tidak boleh ditautkan dua
  kali. Sentinel '' dikecualikan (jalur fallback admin_drive.py
  menulis folder_id="" bila pembuatan folder gagal; '' berarti
  "tidak diketahui", bukan sebuah folder). Duplikat folder_id
  nyata = gagal keras sebelum membuat indeks (pola 0029), jangan
  diam-diam menghapus data.
- Enkripsi system_settings.value: nilai mediamtx_api_password
  yang masih plaintext dienkripsi Fernet (DRIVE_TOKEN_KEY, kunci
  yang sama dengan token Drive) di migrasi ini; bila
  DRIVE_TOKEN_KEY belum diset, migrasi GAGAL dengan pesan jelas
  (bukan diam-diam melewati). Kolom value String(512) -> Text
  (token Fernet saja ~164 karakter).
- rclone_remotes.updated_at (sebelumnya tidak ada) + backfill
  google_drive_folders.updated_at yang NULL dari created_at,
  lalu kolom menjadi NOT NULL + server_default.
- Sentinel ORM: TIDAK diubah di 0030. Rencana awal (default ORM
  "" -> None + hapus server_default '' untuk
  google_drive_folders) DIBATALKAN setelah diverifikasi merusak
  15 test (NOT NULL constraint failed: local_path) — kolom NOT
  NULL dan penulis (termasuk test) menghilangkan local_path.
  Penghapusan sentinel yang benar butuh kolom nullable ATAU
  semua penulis diperbarui; keduanya di luar cakupan 0030.
  Default "" dan server_default '' dipertahankan apa adanya.
  DriveUpload.folder_name: sama — default "" dipertahankan
  (kolom NOT NULL, bagian dari unique constraint).

DIALEK: PostgreSQL saja. Migrasi ini memakai CREATE INDEX
CONCURRENTLY, partial index, dan NOT VALID/VALIDATE — semuanya
tanpa padanan SQLite. Dialek non-PostgreSQL ditolak di awal
dengan pesan jelas (alembic/env.py juga memperingatkan hal ini).
SQLite tetap hanya untuk unit test via Base.metadata.create_all.

TIDAK DIKERJAKAN di migrasi ini (sengaja, lihat laporan):
- PK log (api_access_logs, audit_logs, drive_uploads) ke
  BigInteger: butuh ALTER COLUMN TYPE + rewrite tabel dan
  penyesuaian sequence di PostgreSQL besar — migrasi berat yang
  butuh perencanaan downtime sendiri, bukan diselipkan di sini.
- FK google_drive_folders.remote_name -> rclone_remotes: butuh
  migrasi data (string -> FK) dan keputusan model; dicatat
  sebagai tindak lanjut, bukan DDL di 0030.
- server_onupdate untuk updated_at: TIDAK dipakai — diverifikasi
  PostgreSQL/SQLite tidak merendernya di DDL (no-op); penegak
  updated_at tetap onupdate ORM.
- Sentinel ORM (default "" -> None): DIBATALKAN setelah
  diverifikasi merusak 15 test (NOT NULL constraint failed:
  google_drive_folders.local_path, drive_uploads.folder_name).
  Lihat paragraf "Sentinel ORM" di atas.
- Nama CHECK di model ditulis PENDEK (mis. "role", bukan
  "ck_users_role"): naming convention Base (app/db/base.py)
  menambahkan prefix ck_<tabel>_ saat render, sehingga nama
  penuh akan dirender ganda dan drift dari nama constraint di
  DB. Nama pendek di model merender persis sama dengan nama
  yang dibuat migrasi ini (0027/0029 sudah punya drift yang
  sama untuk CHECK lama; diperbaiki di model oleh 0030).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
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


def _create_index_concurrently(conn, name: str, table: str, columns: str, extra: str = "") -> None:
    """CREATE INDEX CONCURRENTLY IF NOT EXISTS di luar transaksi (pola 0027)."""
    if _has_index(conn, table, name):
        return
    with op.get_context().autocommit_block():
        conn.execute(
            sa.text(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {table} ({columns}){extra}"
            )
        )


def _create_unique_index_concurrently(
    conn, name: str, table: str, columns: str, extra: str = ""
) -> None:
    """CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS di luar transaksi."""
    if _has_index(conn, table, name):
        return
    with op.get_context().autocommit_block():
        conn.execute(
            sa.text(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {table} ({columns}){extra}"
            )
        )


def _add_check_not_valid_then_validate(
    conn, table: str, name: str, condition: str
) -> None:
    """Tambah CHECK sebagai NOT VALID lalu VALIDATE (pola 0029).

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


def _count_violating(conn, table: str, condition: str) -> int:
    return conn.execute(
        sa.text(f"SELECT count(*) FROM {table} WHERE {condition}")
    ).scalar()


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        raise RuntimeError(
            "migrasi 0030 hanya PostgreSQL (CREATE INDEX CONCURRENTLY, "
            "partial index, NOT VALID/VALIDATE tidak ada padanannya di "
            f"dialek {conn.dialect.name}). SQLite hanya untuk unit test "
            "via Base.metadata.create_all — lihat alembic/env.py."
        )

    # -- Fail-hard: duplikat folder_id nyata ('' dikecualikan).
    dups = conn.execute(
        sa.text(
            "SELECT folder_id FROM google_drive_folders "
            "WHERE folder_id <> '' GROUP BY folder_id "
            "HAVING count(*) > 1 LIMIT 5"
        )
    ).fetchall()
    if dups:
        raise RuntimeError(
            "migrasi 0030 ditolak: google_drive_folders berisi folder_id "
            "ganda: " + ", ".join(r[0] for r in dups) + ". Hapus/gabungkan "
            "tautan ganda secara manual dulu, lalu ulangi migrasi."
        )

    # -- Fail-hard: baris yang melanggar CHECK baru (VALIDATE di
    #    bawah adalah penjaga kedua; hitungan di sini memberi pesan
    #    yang jelas sebelum DDL apa pun diubah).
    for table, condition, label in (
        ("streams", "retention_days < 0", "streams.retention_days negatif"),
        (
            "google_drive_folders",
            "retention_days IS NOT NULL AND retention_days < 0",
            "google_drive_folders.retention_days negatif",
        ),
        (
            "api_keys",
            "session_ttl_mnt IS NOT NULL AND session_ttl_mnt <= 0",
            "api_keys.session_ttl_mnt <= 0",
        ),
        (
            "users",
            "parent_admin_id IS NOT NULL AND parent_admin_id = id",
            "users.parent_admin_id menunjuk dirinya sendiri",
        ),
    ):
        n = _count_violating(conn, table, condition)
        if n:
            raise RuntimeError(
                f"migrasi 0030 ditolak: {n} baris melanggar CHECK baru "
                f"({label} di {table}). Perbaiki datanya dulu secara "
                "manual, lalu ulangi migrasi."
            )

    # -- Backfill google_drive_folders.updated_at yang NULL.
    conn.execute(
        sa.text(
            "UPDATE google_drive_folders SET updated_at = created_at "
            "WHERE updated_at IS NULL"
        )
    )
    op.alter_column(
        "google_drive_folders",
        "updated_at",
        server_default=sa.func.now(),
        nullable=False,
        existing_type=sa.DateTime(timezone=True),
    )

    # -- rclone_remotes.updated_at (baru; baris lama terisi now()).
    if not _has_column(conn, "rclone_remotes", "updated_at"):
        op.add_column(
            "rclone_remotes",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    # -- system_settings.value: String(512) -> Text (token Fernet
    #    saja ~164 karakter; tabel generik tidak boleh gagal insert
    #    untuk kredensial yang lebih panjang).
    op.alter_column(
        "system_settings",
        "value",
        type_=sa.Text(),
        existing_type=sa.String(512),
    )

    # -- Enkripsi nilai mediamtx_api_password yang masih plaintext.
    #    Gagal keras bila DRIVE_TOKEN_KEY belum diset (pesan jelas
    #    dari _get_fernet) — jangan pernah melewatinya diam-diam.
    #    Hanya key mediamtx yang dimigrasi: tabel ini generik dan
    #    key lain di masa depan belum tentu rahasia.
    from app.services.system_settings import (  # noqa: PLC0415
        MEDIAMTX_PASSWORD_KEY,
        _looks_like_fernet_token,
        encrypt_system_setting_value,
    )

    row = conn.execute(
        sa.text(
            "SELECT value FROM system_settings WHERE key = :key"
        ).bindparams(key=MEDIAMTX_PASSWORD_KEY)
    ).first()
    if row is not None and not _looks_like_fernet_token(row[0]):
        conn.execute(
            sa.text(
                "UPDATE system_settings SET value = :value "
                "WHERE key = :key"
            ).bindparams(
                value=encrypt_system_setting_value(row[0]),
                key=MEDIAMTX_PASSWORD_KEY,
            )
        )

    # -- Hapus server_default '' google_drive_folders: TIDAK
    #    dilakukan (dibatalkan — lihat docstring: default ORM ""
    #    dan server_default '' dipertahankan karena penulis
    #    menghilangkan local_path).

    # -- CHECK baru (NOT VALID + VALIDATE).
    _add_check_not_valid_then_validate(
        conn,
        "streams",
        "ck_streams_retention_days_nonnegative",
        "retention_days >= 0",
    )
    _add_check_not_valid_then_validate(
        conn,
        "google_drive_folders",
        "ck_google_drive_folders_retention_days_nonnegative",
        "retention_days IS NULL OR retention_days >= 0",
    )
    _add_check_not_valid_then_validate(
        conn,
        "api_keys",
        "ck_api_keys_session_ttl_positive",
        "session_ttl_mnt IS NULL OR session_ttl_mnt > 0",
    )
    _add_check_not_valid_then_validate(
        conn,
        "users",
        "ck_users_parent_admin_not_self",
        "parent_admin_id IS NULL OR parent_admin_id <> id",
    )

    # -- Indeks baru: CONCURRENTLY (tanpa menahan tulis).
    _create_index_concurrently(conn, "ix_streams_owner_id", "streams", "owner_id")
    _create_index_concurrently(conn, "ix_streams_created_by", "streams", "created_by")
    _create_index_concurrently(
        conn, "ix_streams_drive_account_id", "streams", "drive_account_id"
    )
    _create_index_concurrently(
        conn, "ix_streams_drive_folder_id", "streams", "drive_folder_id"
    )
    _create_index_concurrently(
        conn, "ix_users_parent_admin_id", "users", "parent_admin_id"
    )
    _create_index_concurrently(conn, "ix_users_role", "users", "role")
    _create_index_concurrently(
        conn, "ix_google_drive_folders_folder_id", "google_drive_folders", "folder_id"
    )
    _create_index_concurrently(
        conn,
        "ix_google_drive_folders_remote_name",
        "google_drive_folders",
        "remote_name",
    )
    _create_index_concurrently(
        conn,
        "ix_api_access_logs_key_denied_created",
        "api_access_logs",
        "api_key_id, is_denied, created_at",
    )
    _create_index_concurrently(
        conn, "ix_drive_uploads_uploaded_at", "drive_uploads", "uploaded_at"
    )
    # Unik parsial folder_id ('' dikecualikan — lihat docstring).
    _create_unique_index_concurrently(
        conn,
        "uq_google_drive_folders_folder_id",
        "google_drive_folders",
        "folder_id",
        " WHERE folder_id <> ''",
    )

    # -- Hapus indeks redundan / mati.
    for name, table in (
        ("ix_drive_uploads_stream_id", "drive_uploads"),
        ("ix_streams_group_name", "streams"),
    ):
        if _has_index(conn, table, name):
            op.drop_index(name, table_name=table)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        raise RuntimeError(
            "downgrade migrasi 0030 hanya PostgreSQL "
            f"(dialek {conn.dialect.name} tidak didukung)."
        )

    # Kembalikan indeks yang di-drop upgrade.
    if not _has_index(conn, "drive_uploads", "ix_drive_uploads_stream_id"):
        op.create_index(
            "ix_drive_uploads_stream_id", "drive_uploads", ["stream_id"]
        )
    if not _has_index(conn, "streams", "ix_streams_group_name"):
        op.create_index("ix_streams_group_name", "streams", ["group_name"])

    # Hapus indeks baru 0030.
    for name, table in (
        ("uq_google_drive_folders_folder_id", "google_drive_folders"),
        ("ix_drive_uploads_uploaded_at", "drive_uploads"),
        ("ix_api_access_logs_key_denied_created", "api_access_logs"),
        ("ix_google_drive_folders_remote_name", "google_drive_folders"),
        ("ix_google_drive_folders_folder_id", "google_drive_folders"),
        ("ix_users_role", "users"),
        ("ix_users_parent_admin_id", "users"),
        ("ix_streams_drive_folder_id", "streams"),
        ("ix_streams_drive_account_id", "streams"),
        ("ix_streams_created_by", "streams"),
        ("ix_streams_owner_id", "streams"),
    ):
        if _has_index(conn, table, name):
            op.drop_index(name, table_name=table)

    # Lepas CHECK baru (DROP CONSTRAINT lewat SQL mentah — lihat
    # downgrade 0027 soal prefix nama Alembic).
    for name, table in (
        ("ck_users_parent_admin_not_self", "users"),
        ("ck_api_keys_session_ttl_positive", "api_keys"),
        (
            "ck_google_drive_folders_retention_days_nonnegative",
            "google_drive_folders",
        ),
        ("ck_streams_retention_days_nonnegative", "streams"),
    ):
        if _has_constraint(conn, table, name):
            conn.execute(
                sa.text(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
            )

    # Kembalikan server_default '' google_drive_folders: TIDAK
    # dilakukan — langkah penghapusannya dibatalkan di upgrade,
    # jadi tidak ada yang perlu dikembalikan di downgrade.

    # Dekripsi kembali nilai mediamtx ke plaintext (agar downgrade
    # ke 0029 konsisten dengan perilaku lama). Gagal keras bila
    # DRIVE_TOKEN_KEY tidak tersedia — jangan menulis ciphertext
    # sebagai plaintext.
    from app.services.system_settings import (  # noqa: PLC0415
        MEDIAMTX_PASSWORD_KEY,
        _looks_like_fernet_token,
        decrypt_system_setting_value,
    )

    row = conn.execute(
        sa.text(
            "SELECT value FROM system_settings WHERE key = :key"
        ).bindparams(key=MEDIAMTX_PASSWORD_KEY)
    ).first()
    if row is not None and _looks_like_fernet_token(row[0]):
        conn.execute(
            sa.text(
                "UPDATE system_settings SET value = :value "
                "WHERE key = :key"
            ).bindparams(
                value=decrypt_system_setting_value(row[0]),
                key=MEDIAMTX_PASSWORD_KEY,
            )
        )

    # Kembalikan tipe kolom value ke String(512).
    op.alter_column(
        "system_settings",
        "value",
        type_=sa.String(512),
        existing_type=sa.Text(),
    )

    # Hapus kolom rclone_remotes.updated_at.
    if _has_column(conn, "rclone_remotes", "updated_at"):
        op.drop_column("rclone_remotes", "updated_at")

    # Kembalikan google_drive_folders.updated_at nullable tanpa
    # server_default. Backfill upgrade (NULL -> created_at) sengaja
    # TIDAK dikembalikan.
    op.alter_column(
        "google_drive_folders",
        "updated_at",
        server_default=None,
        nullable=True,
        existing_type=sa.DateTime(timezone=True),
    )
