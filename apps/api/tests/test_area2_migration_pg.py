"""Test Migrasi 0027 Area 2 di PostgreSQL asli.

Dilewati bila NETRAVISION_AREA2_PG_URL tidak diset. Variabel itu harus
menunjuk DATABASE SCRATCH KOSONG (bukan demo/produksi!): tiap tes
menjatuhkan seluruh skema `public` dulu. Contoh:
  NETRAVISION_AREA2_PG_URL='postgresql+asyncpg://netravision:...@127.0.0.1:5432/netravision_area2'
  .venv/bin/pytest tests/test_area2_migration_pg.py -q

Mencakup yang tidak bisa diuji di SQLite tes:
- 2.1 FK + unique drive_uploads, dedup, orphan gagal keras.
- 2.5 unique stream_permissions NULLS NOT DISTINCT.
- 2.9 rename folder_id -> folder_name.
- 2.11 drop tabel backup 0014 + perbaikan downgrade 0009/0011.
- 2.13 normalisasi sentinel '' -> NULL.
- Naik/turun 0027 (idempotent-ish round trip).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PG_URL = os.environ.get("NETRAVISION_AREA2_PG_URL", "")
API_DIR = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="butuh NETRAVISION_AREA2_PG_URL (DB scratch Postgres)"
)


def _alembic(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL=PG_URL)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_DIR, env=env, capture_output=True, text=True, timeout=300,
    )


@pytest_asyncio.fixture
async def pg():
    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    yield engine
    await engine.dispose()


async def _q(engine, sql: str, **params):
    async with engine.connect() as conn:
        res = await conn.execute(text(sql), params)
        return res.fetchall()


async def _exec(engine, sql: str, **params):
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


async def _scalar(engine, sql: str, **params):
    rows = await _q(engine, sql, **params)
    return rows[0][0] if rows else None


async def test_upgrade_head_membuat_skema_area2(pg):
    """0027 naik: FK, unique, CHECK, indeks, kolom baru, rename."""
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    # 0030: head kini 0030 (bukan 0029 lagi). Upgrade head di test ini
    # butuh DRIVE_TOKEN_KEY di env (migrasi 0030 mengenkripsi
    # mediamtx_api_password dan gagal keras tanpa kunci itu).
    assert await _scalar(pg, "SELECT version_num FROM alembic_version") == "0030"

    assert await _scalar(
        pg,
        "SELECT count(*) FROM pg_constraint WHERE conname = "
        "'fk_drive_uploads_stream_id'",
    ) == 1
    assert await _scalar(
        pg,
        "SELECT count(*) FROM pg_constraint WHERE conname = "
        "'uq_drive_uploads_stream_folder_segment'",
    ) == 1
    assert await _scalar(
        pg,
        "SELECT count(*) FROM pg_constraint WHERE conname = "
        "'uq_stream_permissions_stream_role_user'",
    ) == 1
    # NULLS NOT DISTINCT benar-benar aktif di indeks unique-nya.
    assert await _scalar(
        pg,
        "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = 'uq_stream_permissions_stream_role_user' "
        "AND i.indnullsnotdistinct",
    ) == 1
    for ck in (
        "ck_users_role", "ck_streams_storage_mode",
        "ck_drive_accounts_status", "ck_stream_permissions_role",
    ):
        assert await _scalar(
            pg, "SELECT count(*) FROM pg_constraint WHERE conname = :n", n=ck
        ) == 1, ck
    for ix in (
        "ix_drive_uploads_stream_uploaded",
        "ix_stream_permissions_stream_role",
        "ix_user_stream_access_stream_id",
        "ix_api_key_streams_stream_id",
        "ix_group_streams_stream_id",
        "ix_stream_admin_grants_admin_id",
        "ix_api_access_logs_stream_id",
        "ix_audit_logs_actor_created",
        "ix_audit_logs_resource_created",
        "ix_streams_is_active",
        "ix_streams_storage_recording",
    ):
        assert await _scalar(
            pg, "SELECT count(*) FROM pg_indexes WHERE indexname = :n", n=ix
        ) == 1, ix
    # 2.9: folder_name ada, folder_id tidak.
    cols = [
        row[0] for row in await _q(
            pg,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'drive_uploads'",
        )
    ]
    assert "folder_name" in cols and "folder_id" not in cols
    # 2.7 + 2.20: kolom baru ada.
    assert await _scalar(
        pg,
        "SELECT count(*) FROM information_schema.columns WHERE "
        "table_name = 'api_access_logs' AND column_name = 'is_denied'",
    ) == 1
    assert await _scalar(
        pg,
        "SELECT count(*) FROM information_schema.columns WHERE "
        "table_name = 'ad_config' AND column_name = 'created_at'",
    ) == 1
    # 2.11: tabel backup 0014 sudah di-drop.
    assert await _scalar(
        pg,
        "SELECT count(*) FROM information_schema.tables WHERE "
        "table_name = '_backup_0014_super_admin_group'",
    ) == 0
    # 2.13: server_default '' sudah dihapus.
    assert await _scalar(
        pg,
        "SELECT column_default FROM information_schema.columns WHERE "
        "table_name = 'streams' AND column_name = 'record_disk'",
    ) is None


async def test_upgrade_dedup_dan_normalisasi(pg):
    """2.1 + 2.13: duplikat persis diciutkan, sentinel '' jadi NULL."""
    r = _alembic("upgrade", "0024")
    assert r.returncode == 0, r.stdout + r.stderr
    await _exec(
        pg,
        "INSERT INTO streams (id, name, rtsp_url, record_disk) VALUES "
        "(1, 'Cam', 'rtsp://x', '')",
    )
    await _exec(
        pg,
        "INSERT INTO drive_uploads (stream_id, segment_name, folder_id) VALUES "
        "(1, 'a.mp4', 'netravision'), (1, 'a.mp4', 'netravision'), "
        "(1, 'b.mp4', 'netravision')",
    )
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(pg, "SELECT count(*) FROM drive_uploads") == 2
    assert await _scalar(
        pg, "SELECT record_disk FROM streams WHERE id = 1"
    ) is None
    assert await _scalar(
        pg, "SELECT folder_name FROM drive_uploads WHERE segment_name = 'a.mp4'"
    ) == "netravision"


async def test_upgrade_yatim_gagal_keras(pg):
    """2.1: baris yatim membuat migrasi GAGAL (bukan dihapus diam-diam)."""
    r = _alembic("upgrade", "0024")
    assert r.returncode == 0, r.stdout + r.stderr
    await _exec(
        pg,
        "INSERT INTO drive_uploads (stream_id, segment_name, folder_id) VALUES "
        "(9999, 'a.mp4', 'netravision')",
    )
    r = _alembic("upgrade", "head")
    assert r.returncode != 0
    assert "yatim" in (r.stdout + r.stderr)
    assert await _scalar(pg, "SELECT count(*) FROM drive_uploads") == 1
    # Setelah yatim dibersihkan manual, migrasi jalan.
    await _exec(pg, "DELETE FROM drive_uploads WHERE stream_id = 9999")
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr


async def test_unique_nulls_not_distinct_pg(pg):
    """2.5: dua baris peran sama (user_id NULL) ditolak di PostgreSQL."""
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    await _exec(
        pg, "INSERT INTO streams (id, name, rtsp_url) VALUES (1, 'Cam', 'rtsp://x')"
    )
    await _exec(
        pg,
        "INSERT INTO stream_permissions (stream_id, role) VALUES (1, 'guest')",
    )
    with pytest.raises(Exception, match="duplicate key|UniqueViolation"):
        await _exec(
            pg,
            "INSERT INTO stream_permissions (stream_id, role) VALUES (1, 'guest')",
        )


async def test_downgrade_upgrade_roundtrip(pg):
    """Naik/turun 0027 lalu naik lagi berhasil; downgrade mengembalikan
    nama kolom dan membuat lagi tabel backup 0014 (kosong)."""
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    r = _alembic("downgrade", "0026")
    assert r.returncode == 0, r.stdout + r.stderr
    cols = [
        row[0] for row in await _q(
            pg,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'drive_uploads'",
        )
    ]
    assert "folder_id" in cols and "folder_name" not in cols
    assert await _scalar(
        pg,
        "SELECT count(*) FROM information_schema.columns WHERE "
        "table_name = 'api_access_logs' AND column_name = 'is_denied'",
    ) == 0
    assert await _scalar(
        pg,
        "SELECT count(*) FROM information_schema.tables WHERE "
        "table_name = '_backup_0014_super_admin_group'",
    ) == 1
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    # 0030: head kini 0030 (lihat komentar yang sama di
    # test_upgrade_head_membuat_skema_area2).
    assert await _scalar(pg, "SELECT version_num FROM alembic_version") == "0030"


async def test_downgrade_0011_tidak_hapus_guest_asli(pg):
    """2.11: downgrade 0011 hanya menghapus guest seed ('!'), bukan
    guest asli ber-hash bcrypt (kasus produksi)."""
    r = _alembic("upgrade", "0011")
    assert r.returncode == 0, r.stdout + r.stderr
    # Guest seed -> ganti hash jadi bcrypt seperti produksi.
    await _exec(
        pg,
        "UPDATE users SET password_hash = '$2b$12$abcdefghijklmnopqrstuu' "
        "WHERE username = 'guest'",
    )
    r = _alembic("downgrade", "0010")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(
        pg, "SELECT count(*) FROM users WHERE username = 'guest'"
    ) == 1
    # Guest seed asli ('!') tetap terhapus oleh downgrade: hapus dulu
    # guest bcrypt di atas, lalu upgrade 0011 membuat seed baru.
    await _exec(pg, "DELETE FROM users WHERE username = 'guest'")
    r = _alembic("upgrade", "0011")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(
        pg,
        "SELECT password_hash FROM users WHERE username = 'guest'",
    ) == "!"
    r = _alembic("downgrade", "0010")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(
        pg, "SELECT count(*) FROM users WHERE username = 'guest'"
    ) == 0


async def test_downgrade_0009_kembalikan_semua_folder(pg):
    """2.11: downgrade 0009 mengembalikan SEMUA folder, bukan 1 baris."""
    r = _alembic("upgrade", "0009")
    assert r.returncode == 0, r.stdout + r.stderr
    await _exec(
        pg,
        "INSERT INTO google_drive_folders (folder_url, folder_id, folder_name) "
        "VALUES ('u1', 'id1', 'satu'), ('u2', 'id2', 'dua')",
    )
    r = _alembic("downgrade", "0008")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(pg, "SELECT count(*) FROM google_drive_settings") == 2
