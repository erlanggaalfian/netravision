"""Test Area 2 sisa (audit backend+database 2026-11-17): 2.8, 2.10, 2.12, 2.19.

- 2.8: baris warisan stream_permissions (user_id terisi, role NULL)
  dihapus migrasi 0029; CHECK baru menolak bentuk mati itu dibuat lagi.
- 2.10: tabel detection_events/alerts dan kolom mati can_download,
  can_control, can_manage dihapus; DriveAccount DIPERTAHANKAN (jalur
  OAuth masih hidup).
- 2.12: GET /admin/audit-logs (super_admin, paginasi + X-Total-Count,
  filter actor_id/resource/action/rentang tanggal).
- 2.19: pool_timeout/pool_recycle + statement_timeout default di engine,
  dan dependency get_db_with_timeout per endpoint.

Tes migrasi PG (0029) dilewati bila NETRAVISION_AREA2_PG_URL tidak
diset; variabel itu harus menunjuk DATABASE SCRATCH KOSONG (bukan
demo/produksi!), pola yang sama seperti tests/test_area2_migration_pg.py.
"""

import importlib.util
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import (
    DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    _is_postgres_session,
    get_db_with_timeout,
)
from app.models.access import StreamAdminGrant, StreamPermission, UserStreamAccess
from app.models.drive import DriveAccount
from app.models.misc import AuditLog
from app.models.streams import Stream
from app.models.users import User
from tests.conftest import auth_as, make_user

API_DIR = Path(__file__).resolve().parents[1]
PG_URL = os.environ.get("NETRAVISION_AREA2_PG_URL", "")


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _audit_factory_for(db_session):
    engine = db_session.bind
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_audit_rows(db, specs):
    """specs: list (actor_id, action, resource, created_at naive)."""
    for actor_id, action, resource, created_at in specs:
        db.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                resource=resource,
                resource_id="user_id=1",
                detail={"status_code": 200, "actor": "su"},
                ip="127.0.0.1",
                created_at=created_at,
            )
        )
    await db.commit()


# ---------- 2.8: baris warisan mati + CHECK pencegah ----------

async def test_2_8_check_menolak_baris_mati(db_session):
    """2.8: (user_id terisi, role NULL) ditolak CHECK baru di metadata."""
    s = Stream(name="Cam", rtsp_url="rtsp://x", is_active=True)
    u = User(username="u8", password_hash="x", role="user", is_active=True)
    db_session.add_all([s, u])
    await db_session.commit()
    sid, uid = s.id, u.id  # snapshot: rollback meng-expire objek
    db_session.add(
        StreamPermission(stream_id=sid, role=None, user_id=uid)
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    # Bentuk per-user DENGAN role tetap lolos (dipakai tes unique 2.5).
    db_session.add(
        StreamPermission(stream_id=sid, role="guest", user_id=uid)
    )
    await db_session.commit()


async def test_2_8_baris_peran_normal_tetap_lolos(db_session):
    """2.8: baris peran (user_id NULL) yang dibaca semua jalur tetap sah."""
    s = Stream(name="Cam", rtsp_url="rtsp://x", is_active=True)
    db_session.add(s)
    await db_session.commit()
    db_session.add(StreamPermission(stream_id=s.id, role="guest"))
    await db_session.commit()
    rows = (
        await db_session.execute(select(StreamPermission))
    ).scalars().all()
    assert len(rows) == 1 and rows[0].role == "guest"


# ---------- 2.10: tabel/kolom mati hilang, DriveAccount dipertahankan ----------

def test_2_10_tabel_deteksi_hilang_dari_metadata():
    """2.10: detection_events dan alerts tidak lagi di metadata."""
    assert "detection_events" not in Base.metadata.tables
    assert "alerts" not in Base.metadata.tables


def test_2_10_kolom_mati_hilang_dari_model():
    """2.10: can_download, can_control, can_manage bukan lagi kolom."""
    assert "can_download" not in StreamPermission.__table__.columns
    assert "can_control" not in UserStreamAccess.__table__.columns
    assert "can_manage" not in StreamAdminGrant.__table__.columns
    # Kolom hidup di sebelahnya tetap ada.
    assert "can_view" in StreamPermission.__table__.columns
    assert "can_playback" in UserStreamAccess.__table__.columns
    assert "can_reshare" in StreamAdminGrant.__table__.columns


def test_2_10_drive_account_dipertahankan():
    """2.10: DriveAccount TETAP ada (jalur OAuth Drive masih hidup)."""
    assert "drive_accounts" in Base.metadata.tables
    cols = Base.metadata.tables["drive_accounts"].columns
    assert "token_encrypted" in cols and "is_default" in cols


# ---------- 2.12: GET /admin/audit-logs ----------

async def test_2_12_list_butuh_super_admin(app_client):
    """2.12: admin biasa 403, super_admin 200."""
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    await _seed_audit_rows(db, [(1, "GET /api/admin/users", "/api/admin/users", datetime(2026, 11, 10, 10, 0, 0))])
    auth_as(app, make_user(role="admin"))
    async with _client(app) as c:
        r = await c.get("/api/admin/audit-logs")
        assert r.status_code == 403, r.text
    # GET 403 di atas tetap diaudit (middleware mencatat bacaan
    # sensitif apa pun statusnya), jadi total kini 2: 1 baris seed +
    # 1 baris audit dari GET 403 itu.
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.get("/api/admin/audit-logs")
        assert r.status_code == 200, r.text
        assert r.headers["X-Total-Count"] == "2"
        assert len(r.json()) == 2
        assert any(
            row["action"] == "GET /api/admin/users" for row in r.json()
        )


async def test_2_12_paginasi_dan_total_count(app_client):
    """2.12: limit/offset + header X-Total-Count seperti admin_keys."""
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    await _seed_audit_rows(db, [
        (1, "POST /api/admin/users", "/api/admin/users", datetime(2026, 11, 10, 10, 0, 0)),
        (1, "PUT /api/admin/users/2", "/api/admin/users/{user_id}", datetime(2026, 11, 11, 10, 0, 0)),
        (2, "DELETE /api/admin/users/3", "/api/admin/users/{user_id}", datetime(2026, 11, 12, 10, 0, 0)),
    ])
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.get("/api/admin/audit-logs?limit=2&offset=0")
        assert r.status_code == 200, r.text
        assert r.headers["X-Total-Count"] == "3"
        body = r.json()
        assert len(body) == 2
        # Terbaru dulu (id desc).
        assert body[0]["action"] == "DELETE /api/admin/users/3"
        assert body[0]["actor_id"] == 2
        # GET di atas menambahkan 1 baris audit (middleware mencatat
        # bacaan sensitif), jadi total kini 4 dan baris seed tertua
        # ada di offset 3.
        r = await c.get("/api/admin/audit-logs?limit=2&offset=3")
        assert r.headers["X-Total-Count"] == "4"
        assert len(r.json()) == 1
        assert r.json()[0]["action"] == "POST /api/admin/users"


async def test_2_12_filter_actor_resource_action(app_client):
    """2.12: filter actor_id, resource (persis), action (substring)."""
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    await _seed_audit_rows(db, [
        (1, "POST /api/admin/users", "/api/admin/users", datetime(2026, 11, 10, 10, 0, 0)),
        (1, "PUT /api/admin/users/2", "/api/admin/users/{user_id}", datetime(2026, 11, 11, 10, 0, 0)),
        (2, "POST /api/admin/streams", "/api/admin/streams", datetime(2026, 11, 12, 10, 0, 0)),
    ])
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.get("/api/admin/audit-logs?actor_id=2")
        assert r.headers["X-Total-Count"] == "1"
        assert r.json()[0]["resource"] == "/api/admin/streams"
        r = await c.get("/api/admin/audit-logs?resource=/api/admin/users")
        assert r.headers["X-Total-Count"] == "1"
        assert r.json()[0]["action"] == "POST /api/admin/users"
        # action substring: semua POST (2 baris), bukan PUT.
        r = await c.get("/api/admin/audit-logs?action=POST")
        assert r.headers["X-Total-Count"] == "2"
        r = await c.get("/api/admin/audit-logs?action=PUT /api/admin/users")
        assert r.headers["X-Total-Count"] == "1"
        # Kombinasi filter.
        r = await c.get("/api/admin/audit-logs?actor_id=1&action=POST")
        assert r.headers["X-Total-Count"] == "1"


async def test_2_12_filter_rentang_tanggal(app_client):
    """2.12: date_from/date_to inklusif atas created_at."""
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    await _seed_audit_rows(db, [
        (1, "POST /api/admin/users", "/api/admin/users", datetime(2026, 11, 10, 10, 0, 0)),
        (1, "PUT /api/admin/users/2", "/api/admin/users/{user_id}", datetime(2026, 11, 11, 10, 0, 0)),
        (2, "DELETE /api/admin/users/3", "/api/admin/users/{user_id}", datetime(2026, 11, 12, 10, 0, 0)),
    ])
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        # Urutan GET penting: tiap GET menambahkan 1 baris audit
        # (created_at = sekarang, 2026-11-17) lewat middleware.
        # GET pertama tanpa GET sebelumnya: hanya baris seed 12 Nov.
        r = await c.get("/api/admin/audit-logs?date_from=2026-11-12T00:00:00")
        assert r.status_code == 200, r.text
        assert r.headers["X-Total-Count"] == "1"
        assert r.json()[0]["action"] == "DELETE /api/admin/users/3"
        # Rentang 11 Nov: baris audit dari GET sebelumnya (17 Nov)
        # di luar rentang, jadi tetap 1.
        r = await c.get(
            "/api/admin/audit-logs?date_from=2026-11-11T00:00:00&date_to=2026-11-11T23:59:59"
        )
        assert r.headers["X-Total-Count"] == "1"
        assert r.json()[0]["action"] == "PUT /api/admin/users/2"
        r = await c.get("/api/admin/audit-logs?date_to=2026-11-10T23:59:59")
        assert r.headers["X-Total-Count"] == "1"
        assert r.json()[0]["action"] == "POST /api/admin/users"


# ---------- 2.19: pool + statement_timeout ----------

def test_2_19_engine_pool_dan_statement_timeout_default(monkeypatch, tmp_path):
    """2.19: engine asyncpg membawa pool_timeout/recycle + server_settings
    statement_timeout 30 detik; URL non-asyncpg tanpa server_settings."""
    import app.db.session as sess

    # Engine di-cache di modul (global _engine); bila tes lain sudah
    # memanggil get_engine(), get_engine() mengembalikan cache tanpa
    # memanggil create_async_engine, jadi capture di bawah kosong.
    # Reset dulu supaya tes ini tidak bergantung pada urutan jalan.
    sess._engine = None
    sess._session_factory = None

    seen: dict = {}
    real_create = sess.create_async_engine

    def _capture(*args, **kwargs):
        seen.clear()
        seen.update(kwargs)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(sess, "create_async_engine", _capture)
    try:
        monkeypatch.setattr(
            sess, "get_settings",
            lambda: SimpleNamespace(
                database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/db"
            ),
        )
        engine = sess.get_engine()
        assert seen["pool_timeout"] == 30
        assert seen["pool_recycle"] == 1800
        assert seen["connect_args"] == {
            "server_settings": {"statement_timeout": "30000"}
        }
        assert engine.sync_engine.pool.timeout() == 30
        assert engine.sync_engine.pool._recycle == 1800
    finally:
        import asyncio

        asyncio.run(sess.dispose_engine())
    # URL SQLite file (tes): tanpa server_settings, pool tetap sama.
    # (URL :memory: memakai StaticPool yang menolak kwarg pool_size.)
    monkeypatch.setattr(sess, "create_async_engine", _capture)
    monkeypatch.setattr(
        sess, "get_settings",
        lambda: SimpleNamespace(
            database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db"
        ),
    )
    try:
        engine = sess.get_engine()
        assert seen["pool_timeout"] == 30
        assert seen["pool_recycle"] == 1800
        assert seen["connect_args"] == {}
    finally:
        import asyncio

        asyncio.run(sess.dispose_engine())


def test_2_19_default_statement_timeout_konstanta():
    """2.19: default 30 detik dipakai engine dan reset per-endpoint."""
    assert DEFAULT_STATEMENT_TIMEOUT_SECONDS == 30


async def test_2_19_get_db_with_timeout_noop_di_sqlite(db_session):
    """2.19: dependency per-endpoint no-op di SQLite (tanpa error)."""
    gen = get_db_with_timeout(60)(db_session)
    yielded = await gen.__anext__()
    assert yielded is db_session
    await gen.aclose()


class _FakeDialect:
    name = "postgresql"


class _FakeEngine:
    def __init__(self):
        self.dialect = _FakeDialect()


class _FakePGSession:
    """Sesi palsu berdialek PostgreSQL: catat SET yang dieksekusi."""

    def __init__(self):
        self.bind = SimpleNamespace(sync_engine=_FakeEngine())
        self.executed: list[str] = []
        self.rolled_back = 0

    async def execute(self, stmt):
        self.executed.append(str(stmt))

    async def rollback(self):
        self.rolled_back += 1


async def test_2_19_get_db_with_timeout_set_dan_reset_pg():
    """2.19: di PostgreSQL, dependency SET timeout lalu kembalikan
    ke default saat request selesai."""
    fake = _FakePGSession()
    assert _is_postgres_session(fake) is True
    gen = get_db_with_timeout(60)(fake)
    yielded = await gen.__anext__()
    assert yielded is fake
    assert fake.executed == ["SET statement_timeout = '60000'"]
    await gen.aclose()
    assert fake.rolled_back == 1
    assert fake.executed == [
        "SET statement_timeout = '60000'",
        "SET statement_timeout = '30000'",
    ]


def test_2_19_sqlite_bukan_postgres(db_session):
    """2.19: sesi SQLite dikenali bukan-PostgreSQL (no-op)."""
    assert _is_postgres_session(db_session) is False


# ---------- Migrasi 0029: rantai revisi + satu head ----------

def _load_migration_0029():
    path = API_DIR / "alembic" / "versions" / "0029_area2_sisa.py"
    spec = importlib.util.spec_from_file_location("m0029", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_0029_revisi_dan_down_revision():
    """0029 merevisi 0028 (head sebelumnya)."""
    mod = _load_migration_0029()
    assert mod.revision == "0029"
    assert mod.down_revision == "0028"


def test_alembic_satu_head_0030():
    """Rantai migrasi tetap satu head, kini 0030."""
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=API_DIR, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    heads = [
        line.split()[0] for line in r.stdout.strip().splitlines() if line.strip()
    ]
    assert heads == ["0030"], r.stdout


# ---------- Migrasi 0029 di PostgreSQL asli (gated) ----------

pytestmark_pg = pytest.mark.skipif(
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


@pytestmark_pg
async def test_pg_0029_upgrade_hapus_baris_mati_dan_tabel_mati(pg):
    """2.8 + 2.10 di PG: baris mati hilang, tabel/kolom mati hilang,
    baris hidup dan DriveAccount tetap ada."""
    r = _alembic("upgrade", "0028")
    assert r.returncode == 0, r.stdout + r.stderr
    await _exec(
        pg,
        "INSERT INTO streams (id, name, rtsp_url) VALUES (100, 'Cam', 'rtsp://x')",
    )
    await _exec(
        pg,
        "INSERT INTO users (id, username, password_hash, role) "
        "VALUES (100, 'u', 'x', 'user')",
    )
    # Baris mati persis (17 di produksi): user_id terisi, role NULL.
    await _exec(
        pg,
        "INSERT INTO stream_permissions (stream_id, role, user_id) "
        "VALUES (100, NULL, 100)",
    )
    # Baris hidup: peran (user_id NULL). Bentuk per-user DENGAN role
    # sengaja TIDAK diuji di sini: migrasi 0029 menolaknya dengan
    # gagal keras (bentuk tak dikenal audit), lihat
    # test_pg_0029_tolak_bentuk_baru_tanpa_hapus.
    await _exec(
        pg,
        "INSERT INTO stream_permissions (stream_id, role, user_id) "
        "VALUES (100, 'guest', NULL)",
    )
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(pg, "SELECT version_num FROM alembic_version") == "0029"
    # Hanya baris mati yang hilang (2 -> 1).
    assert await _scalar(pg, "SELECT count(*) FROM stream_permissions") == 1
    assert await _scalar(
        pg,
        "SELECT count(*) FROM stream_permissions WHERE user_id IS NOT NULL",
    ) == 0
    # CHECK pencegah baris mati ada.
    assert await _scalar(
        pg,
        "SELECT count(*) FROM pg_constraint WHERE conname = "
        "'ck_stream_permissions_user_row_needs_role'",
    ) == 1
    # Tabel deteksi hilang, kolom mati hilang.
    for table in ("detection_events", "alerts"):
        assert await _scalar(
            pg,
            "SELECT count(*) FROM information_schema.tables WHERE table_name = :n",
            n=table,
        ) == 0, table
    for table, column in (
        ("stream_permissions", "can_download"),
        ("user_stream_access", "can_control"),
        ("stream_admin_grants", "can_manage"),
    ):
        assert await _scalar(
            pg,
            "SELECT count(*) FROM information_schema.columns WHERE "
            "table_name = :t AND column_name = :c",
            t=table, c=column,
        ) == 0, (table, column)
    # DriveAccount DIPERTAHANKAN (jalur OAuth masih hidup).
    assert await _scalar(
        pg,
        "SELECT count(*) FROM information_schema.tables WHERE "
        "table_name = 'drive_accounts'",
    ) == 1


@pytestmark_pg
async def test_pg_0029_tolak_bentuk_baru_tanpa_hapus(pg):
    """2.8: baris user_id terisi DENGAN role (bentuk tak dikenal audit)
    membuat migrasi GAGAL sebelum menghapus apa pun."""
    r = _alembic("upgrade", "0028")
    assert r.returncode == 0, r.stdout + r.stderr
    await _exec(
        pg,
        "INSERT INTO streams (id, name, rtsp_url) VALUES (100, 'Cam', 'rtsp://x')",
    )
    await _exec(
        pg,
        "INSERT INTO users (id, username, password_hash, role) "
        "VALUES (100, 'u', 'x', 'user')",
    )
    await _exec(
        pg,
        "INSERT INTO stream_permissions (stream_id, role, user_id) "
        "VALUES (100, 'user', 100)",
    )
    r = _alembic("upgrade", "head")
    assert r.returncode != 0
    assert "ditolak" in (r.stdout + r.stderr)
    assert await _scalar(pg, "SELECT count(*) FROM stream_permissions") == 1
    # Setelah baris tak dikenal dibersihkan manual, migrasi jalan.
    await _exec(pg, "DELETE FROM stream_permissions WHERE user_id IS NOT NULL")
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(pg, "SELECT version_num FROM alembic_version") == "0029"


@pytestmark_pg
async def test_pg_0029_downgrade_upgrade_roundtrip(pg):
    """0029 turun ke 0028 (tabel/kolom kembali kosong, CHECK lepas)
    lalu naik lagi ke 0029."""
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(pg, "SELECT version_num FROM alembic_version") == "0029"
    r = _alembic("downgrade", "0028")
    assert r.returncode == 0, r.stdout + r.stderr
    for table in ("detection_events", "alerts"):
        assert await _scalar(
            pg,
            "SELECT count(*) FROM information_schema.tables WHERE table_name = :n",
            n=table,
        ) == 1, table
    for table, column in (
        ("stream_permissions", "can_download"),
        ("user_stream_access", "can_control"),
        ("stream_admin_grants", "can_manage"),
    ):
        assert await _scalar(
            pg,
            "SELECT count(*) FROM information_schema.columns WHERE "
            "table_name = :t AND column_name = :c",
            t=table, c=column,
        ) == 1, (table, column)
    assert await _scalar(
        pg,
        "SELECT count(*) FROM pg_constraint WHERE conname = "
        "'ck_stream_permissions_user_row_needs_role'",
    ) == 0
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stdout + r.stderr
    assert await _scalar(pg, "SELECT version_num FROM alembic_version") == "0029"
