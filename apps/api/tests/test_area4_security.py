"""Test Area 4 (Auth/Keamanan/RBAC) audit 2026-11-17.

Mencakup perbaikan 4.1-4.20 yang tidak tercakup file tes lain:
refresh rotation + deteksi reuse (4.1/4.2), kebijakan password (4.12),
pencabutan refresh saat ganti password/nonaktif (4.1), kedaluwarsa
API key (4.3), token sesi file playback (4.4), redaksi password hasil
scan + brankas vault (4.6), rate limit endpoint (4.7), proxy tepercaya
(4.8), lockout per (identitas, IP) (4.9), revalidasi + idle WS (4.10),
auth control API MediaMTX (4.11), guest sintetis (4.14), audit auth
(4.15), header keamanan + docs mati (4.16/4.18), guard probe (4.17),
max_length + validasi URL iklan (4.19/4.20).
"""

import hashlib
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token, hash_password, hash_token
from app.main import create_app
from app.models.users import User


# ---------- helper FakeSession (pola tests/test_auth.py) ----------

class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def first(self):
        return self._items[0] if self._items else None


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalars(self._items)


class FakeSession:
    def __init__(self, user=None):
        self._user = user
        self.committed = False

    async def execute(self, stmt):
        return _FakeResult([self._user] if self._user is not None else [])

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass

    def add(self, obj):
        pass


def _make_fake_user(**kw):
    base = dict(
        id=1,
        username="admin",
        password_hash=hash_password("rahasia123"),
        role="admin",
        is_active=True,
        refresh_token_hash=None,
        refresh_token_jti=None,
    )
    base.update(kw)
    return User(**base)


def _fake_client(app, user=None):
    from app.core.rbac import get_current_user
    from app.db.session import get_db

    fake = FakeSession(user)

    async def _get_db():
        yield fake

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), fake


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------- 4.12: kebijakan password ----------

def test_validate_password_policy():
    from app.core.security import validate_password

    # Admin/super_admin minimal 12 karakter.
    assert validate_password("pendek", "admin") is not None
    assert validate_password("rahasia123", "admin") is not None  # 10 karakter
    assert validate_password("rahasia123456", "admin") is None
    assert validate_password("pendek", "super_admin") is not None
    # User/guest minimal 8 karakter.
    assert validate_password("pendek", "user") is not None  # 6 karakter
    assert validate_password("rahasia123", "user") is None
    assert validate_password("rahasia123", "guest") is None
    # Password umum ditolak walau panjang.
    assert validate_password("password123", "admin") is not None
    assert validate_password("netravision123", "user") is not None
    # Spasi di ujung ditolak.
    assert validate_password(" rahasia123456", "admin") is not None
    assert validate_password("rahasia123456 ", "admin") is not None
    assert validate_password("rahasia 123456", "admin") is None


# ---------- 4.2: grace window + deteksi pemakaian ulang refresh ----------

async def test_refresh_grace_window_allows_one_retry():
    """Token lama yang baru dirotasi masih lolos SEKALI dalam grace (10 dtk)."""
    from app.routers import auth as auth_router

    auth_router.reset_refresh_state()
    settings = get_settings()
    app = create_app()
    user = _make_fake_user()
    token_a, jti_a = create_refresh_token(user.id, settings)
    user.refresh_token_hash = hash_token(token_a)
    user.refresh_token_jti = jti_a
    c, _ = _fake_client(app, user)
    async with c:
        r1 = await c.post("/api/auth/refresh", json={"refresh_token": token_a})
        assert r1.status_code == 200, r1.text
        token_b = r1.json()["refresh_token"]
        assert token_b != token_a
        # Retry bersamaan dengan token lama (dalam grace) tetap lolos.
        r2 = await c.post("/api/auth/refresh", json={"refresh_token": token_a})
        assert r2.status_code == 200, r2.text
        assert r2.json()["refresh_token"] != token_a


async def test_refresh_reuse_after_grace_revokes_family():
    """Token lama dipakai lagi SETELAH grace habis = reuse: 401 + keluarga dicabut."""
    from app.routers import auth as auth_router

    auth_router.reset_refresh_state()
    settings = get_settings()
    app = create_app()
    user = _make_fake_user()
    token_a, jti_a = create_refresh_token(user.id, settings)
    user.refresh_token_hash = hash_token(token_a)
    user.refresh_token_jti = jti_a
    c, _ = _fake_client(app, user)
    async with c:
        r1 = await c.post("/api/auth/refresh", json={"refresh_token": token_a})
        assert r1.status_code == 200, r1.text
        token_b = r1.json()["refresh_token"]
        # Lewatkan grace window secara manual (tanpa menunggu 10 detik).
        entry = auth_router._recent_refresh[user.id]
        auth_router._recent_refresh[user.id] = (
            entry[0], entry[1], time.monotonic() - 1.0,
        )
        # Token lama dipakai lagi di luar grace -> reuse.
        r2 = await c.post("/api/auth/refresh", json={"refresh_token": token_a})
        assert r2.status_code == 401, r2.text
        assert "dipakai ulang" in r2.json()["detail"]
        # Keluarga tercabut: hash + jti aktif ikut hilang.
        assert user.refresh_token_hash is None
        assert user.refresh_token_jti is None
        # Token hasil rotasi (yang mungkin dipegang penyerang) ikut mati.
        r3 = await c.post("/api/auth/refresh", json={"refresh_token": token_b})
        assert r3.status_code == 401, r3.text


async def test_refresh_unknown_token_no_revoke():
    """Token asing (tidak pernah sah) hanya 401 biasa, tanpa pencabutan."""
    from app.routers import auth as auth_router

    auth_router.reset_refresh_state()
    settings = get_settings()
    app = create_app()
    user = _make_fake_user()
    token_a, jti_a = create_refresh_token(user.id, settings)
    user.refresh_token_hash = hash_token(token_a)
    user.refresh_token_jti = jti_a
    stranger, _ = create_refresh_token(999, settings)
    c, _ = _fake_client(app, user)
    async with c:
        r = await c.post("/api/auth/refresh", json={"refresh_token": stranger})
        assert r.status_code == 401, r.text
        assert "dipakai ulang" not in r.json()["detail"]
        # Sesi sah tidak ikut tercabut.
        assert user.refresh_token_hash == hash_token(token_a)


# ---------- 4.9: lockout per (identitas, IP) ----------

def test_login_lockout_keyed_by_username_and_ip():
    from app.routers import auth as auth_router

    auth_router.reset_login_attempts()
    assert not auth_router._login_locked("alice", "1.1.1.1")
    for _ in range(5):
        auth_router._login_failed("alice", "1.1.1.1")
    assert auth_router._login_locked("alice", "1.1.1.1")
    # Username sama dari IP lain TIDAK terkunci.
    assert not auth_router._login_locked("alice", "2.2.2.2")
    # Username lain dari IP yang sama TIDAK terkunci.
    assert not auth_router._login_locked("bob", "1.1.1.1")
    # Login sukses membersihkan hanya kombinasi itu.
    auth_router._login_succeeded("alice", "1.1.1.1")
    assert not auth_router._login_locked("alice", "1.1.1.1")


def test_key_lockout_keyed_by_key_and_ip():
    from app.routers import external as ext_router

    ext_router._KEY_FAILURES.clear()
    for _ in range(5):
        ext_router._record_key_failure(7, "1.1.1.1")
    assert ext_router._key_locked(7, "1.1.1.1")
    assert not ext_router._key_locked(7, "2.2.2.2")
    assert not ext_router._key_locked(8, "1.1.1.1")


# ---------- 4.14: guest sintetis hanya bila baris tak ada DAN env aktif ----------

async def test_guest_token_without_row_follows_env(app_client, monkeypatch):
    """Token guest tanpa baris DB: env mati -> 401, env hidup -> sintetis diizinkan."""
    app, _, db = app_client
    # Pastikan tidak ada baris guest di DB tes ini.
    assert await db.get(User, 9) is None
    tok = create_access_token("guest", "guest", "guest", get_settings())
    async with _client(app) as c:
        monkeypatch.setattr(get_settings(), "guest_enabled", False)
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, r.text
        monkeypatch.setattr(get_settings(), "guest_enabled", True)
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        assert r.json()["username"] == "guest"


# ---------- 4.1: ganti password / nonaktifkan mencabut refresh ----------

async def test_change_password_revokes_refresh(app_client):
    """PUT password baru -> refresh_token_hash dan jti jadi None (semua sesi mati)."""
    from sqlalchemy import select
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    admin = make_user(role="super_admin")
    target = make_user(
        id=2, username="korban", role="user",
        refresh_token_hash="hash-lama", refresh_token_jti="jti-lama",
    )
    db.add_all([admin, target])
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.put(
            "/api/admin/users/2",
            json={"password": "PasswordBaru1234"},
        )
        assert r.status_code == 200, r.text
    row = (await db.execute(select(User).where(User.id == 2))).scalars().first()
    assert row.refresh_token_hash is None
    assert row.refresh_token_jti is None


async def test_deactivate_user_revokes_refresh(app_client):
    """Menonaktifkan akun -> refresh tercabut (sesi curian tidak hidup terus)."""
    from sqlalchemy import select
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    admin = make_user(role="super_admin")
    target = make_user(
        id=2, username="korban", role="user",
        refresh_token_hash="hash-lama", refresh_token_jti="jti-lama",
    )
    db.add_all([admin, target])
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.put("/api/admin/users/2", json={"is_active": False})
        assert r.status_code == 200, r.text
    row = (await db.execute(select(User).where(User.id == 2))).scalars().first()
    assert row.refresh_token_hash is None
    assert row.refresh_token_jti is None
    assert row.is_active is False


async def test_create_user_weak_password_rejected(app_client):
    """4.12: password baru yang lemah ditolak 400 (admin dan user)."""
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/users",
            json={"username": "a1", "password": "password123", "role": "admin"},
        )
        assert r.status_code == 400, r.text
        r = await c.post(
            "/api/admin/users",
            json={"username": "u1", "password": "pendek", "role": "user"},
        )
        assert r.status_code == 400, r.text
        r = await c.post(
            "/api/admin/users",
            json={"username": "u2", "password": "rahasia123456", "role": "user"},
        )
        assert r.status_code == 201, r.text


# ---------- 4.3 + 4.19: kedaluwarsa + batas panjang API key ----------

async def _seed_stream(db):
    from app.models.streams import Stream

    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
               main_url="rtsp://cam/1", is_active=True)
    db.add(s)
    await db.commit()
    return s


async def test_api_key_expires_at(app_client):
    """4.3: expires_at bisa diisi lewat API; kunci kedaluwarsa ditolak external."""
    from datetime import datetime, timedelta, timezone

    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    await _seed_stream(db)
    auth_as(app, make_user(role="super_admin"))
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/api-keys",
            json={"name": "mitra", "stream_ids": [1], "expires_at": future},
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body["expires_at"] is not None
        raw = body["key"]
        key_id = body["id"]
        # Hapus kedaluwarsa lewat update dengan null eksplisit.
        r = await c.put(f"/api/admin/api-keys/{key_id}", json={"expires_at": None})
        assert r.status_code == 200, r.text
        assert r.json()["expires_at"] is None
        # Kunci masih hidup: external menerimanya.
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": raw})
        assert r.status_code == 200, r.text
    # Lewatkan kedaluwarsa di DB -> external menolak 403.
    from app.models.keys import ApiKey

    key = await db.get(ApiKey, key_id)
    key.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()
    async with _client(app) as c:
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": raw})
        assert r.status_code == 403, r.text


async def test_api_key_field_length_limits(app_client):
    """4.19: domain_lock >255 / custom_camera_name >128 ditolak 422."""
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    await _seed_stream(db)
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/api-keys",
            json={"name": "x", "stream_ids": [1], "domain_lock": "a" * 256},
        )
        assert r.status_code == 422, r.text
        r = await c.post(
            "/api/admin/api-keys",
            json={"name": "x", "stream_ids": [1], "custom_camera_name": "a" * 129},
        )
        assert r.status_code == 422, r.text
        r = await c.post(
            "/api/admin/api-keys",
            json={"name": "x", "stream_ids": [1], "password": "p" * 73},
        )
        assert r.status_code == 422, r.text


# ---------- 4.20: URL iklan hanya http/https (atau path relatif) ----------

async def test_ad_config_rejects_dangerous_urls(app_client):
    """click_url javascript:/data: dan image_url data: ditolak 422."""
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/ad-config",
            json={"click_url": "javascript:alert(1)"},
        )
        assert r.status_code == 422, r.text
        r = await c.post(
            "/api/admin/ad-config",
            json={"image_url": "data:text/html,<script>alert(1)</script>"},
        )
        assert r.status_code == 422, r.text
        r = await c.post(
            "/api/admin/ad-config",
            json={"click_url": "https://contoh.id/promo", "image_url": "/uploads/iklan.jpg"},
        )
        assert r.status_code == 200, r.text


# ---------- 4.4: token sesi file playback ----------

async def test_file_session_token_roundtrip_and_binding(app_client):
    """Token sesi file: sah untuk kamera+rentang itu, ditolak untuk yang lain."""
    from datetime import datetime, timedelta, timezone

    import pytest

    from app.models.keys import ApiKey, ApiKeyStream
    from app.routers.external import (
        _file_session_token,
        _validate_file_session_token,
    )
    from tests.conftest import make_user

    app, _, db = app_client
    key = ApiKey(
        name="mitra", key_hash=hashlib.sha256(b"KUNCI-1").hexdigest(),
        is_active=True, session_ttl_mnt=60,
    )
    db.add(key)
    await db.flush()
    db.add(ApiKeyStream(api_key_id=key.id, stream_id=1))
    await _seed_stream(db)
    start = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc)
    tok = _file_session_token(key, 1, start, end, 60)
    assert await _validate_file_session_token(
        db, tok, start.isoformat(), end.isoformat()
    ) == (key.id, 1)
    # Rentang lain ditolak.
    with pytest.raises(ValueError, match="rentang"):
        await _validate_file_session_token(
            db, tok, start.isoformat(),
            (end + timedelta(hours=1)).isoformat(),
        )
    # Token kedaluwarsa ditolak (TTL negatif = sudah lewat).
    expired = _file_session_token(key, 1, start, end, -1)
    with pytest.raises(ValueError):
        await _validate_file_session_token(
            db, expired, start.isoformat(), end.isoformat()
        )
    # Token sesi embed biasa (tanpa kind playback_file) ditolak.
    from app.routers.external import _session_token

    plain = _session_token(key, 1, 60)
    with pytest.raises(ValueError, match="bukan token sesi file"):
        await _validate_file_session_token(
            db, plain, start.isoformat(), end.isoformat()
        )


async def test_external_playback_file_url_uses_session(
    app_client, monkeypatch, tmp_path
):
    """4.4: URL file playback memakai ?session= (bukan ?key=&pass=)."""
    import os

    from app.models.keys import ApiKey, ApiKeyStream

    app, _, db = app_client
    monkeypatch.setattr(get_settings(), "recordings_dir", str(tmp_path))
    key = ApiKey(
        name="mitra", key_hash=hashlib.sha256(b"KUNCI-RAHASIA-123").hexdigest(),
        is_active=True, session_ttl_mnt=60,
    )
    db.add(key)
    await db.flush()
    await _seed_stream(db)
    db.add(ApiKeyStream(api_key_id=key.id, stream_id=1))
    await db.commit()
    # Dua segmen supaya segmen pertama punya end = awal segmen kedua.
    d = os.path.join(str(tmp_path), "stream_1")
    os.makedirs(d, exist_ok=True)
    for name in ("2026-11-02_10-00-00-000000.mp4", "2026-11-02_11-00-00-000000.mp4"):
        with open(os.path.join(d, name), "wb") as f:
            f.write(b"v" * 2048)
    async with _client(app) as c:
        r = await c.get(
            "/api/external/playback",
            params={"camera": 1, "date": "2026-11-02"},
            headers={"X-Api-Key": "KUNCI-RAHASIA-123"},
        )
        assert r.status_code == 200, r.text
        segs = r.json()["segments"]
        assert len(segs) == 2
        url = segs[0]["url"]
        assert "session=" in url
        assert "key=" not in url and "pass=" not in url
        # URL sesi bisa dipakai mengunduh berkas (rentang penuh segmen).
        r = await c.get(url)
        assert r.status_code == 200, r.text
        assert r.content == b"v" * 2048
        # Token sesi terikat kamera 1: kamera lain ditolak.
        r = await c.get(url.replace("camera=1", "camera=2"))
        assert r.status_code == 403, r.text
        # URL lama ?key=&pass= DITOLAK 400 (breaking change
        # 2026-11-18: kredensial embed tidak lagi lewat query string).
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(url).query)
        legacy = (
            "/api/external/playback/file?key=KUNCI-RAHASIA-123&camera=1"
            f"&start={q['start'][0]}&end={q['end'][0]}"
        )
        r = await c.get(legacy)
        assert r.status_code == 400, r.text


# ---------- 4.6: redaksi password hasil scan + brankas vault ----------

async def test_scan_response_redacts_password(app_client):
    """POST /admin/scan: password TIDAK muncul di respons, hanya **** + scan_id."""
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.post("/api/admin/scan", json={
            "brand": "dahua", "host": "192.168.1.11",
            "user": "admin", "password": "katasandi-scan", "probe": False,
        })
        assert r.status_code == 200, r.text
        assert "katasandi-scan" not in r.text
        assert "****" in r.text
        body = r.json()
        assert body.get("scan_id")
        assert all("katasandi-scan" not in (cand.get("main_url") or "")
                   for cand in body["candidates"])


async def test_scan_create_camera_restores_password_from_vault(app_client):
    """Kamera dibuat dari URL teredaksi + scan_ref -> tersimpan dengan password asli."""
    from sqlalchemy import select

    from app.models.streams import Stream
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.post("/api/admin/scan", json={
            "brand": "dahua", "host": "192.168.1.11",
            "user": "admin", "password": "katasandi-scan", "probe": False,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        scan_id = body["scan_id"]
        redacted = body["candidates"][0]["main_url"]
        assert "****" in redacted
        # Dengan scan_ref yang benar: dibuat, password asli dipulihkan.
        r = await c.post("/api/admin/streams", json={
            "name": "Cam Scan", "rtsp_url": redacted,
            "scan_ref": scan_id, "force": True,
        })
        assert r.status_code == 201, r.text
        row = (await db.execute(
            select(Stream).where(Stream.id == r.json()["id"])
        )).scalars().first()
        assert "katasandi-scan" in (row.rtsp_url or "")
        # Tanpa scan_ref: URL **** ditolak 400 (password **** tidak
        # boleh tersimpan harfiah).
        redacted2 = body["candidates"][0]["sub_url"]
        r = await c.post("/api/admin/streams", json={
            "name": "Cam Scan 2", "rtsp_url": redacted2, "force": True,
        })
        assert r.status_code == 400, r.text


async def test_subnet_scan_response_redacts_password(app_client, monkeypatch):
    """POST /admin/scan-subnet: password scan tidak bocor di hasil polling."""
    import asyncio

    import pytest_asyncio

    from app.routers import admin_scan
    from app.services import rtsp_discovery
    from app.services.rtsp_discovery import VideoProbe
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    app.include_router(admin_scan.router, prefix="/api")
    admin_scan._jobs.clear()
    auth_as(app, make_user(role="super_admin"))

    async def fake_alive(host: str, port: int) -> bool:
        return host == "192.168.1.10"

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        return "open" if url.endswith("/H.264") else "not_found"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        return VideoProbe(status="video", codec="h264",
                          width=800, height=448, fps=25.0, gop_seconds=2.0)

    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    monkeypatch.setattr(admin_scan, "_host_reachable", fake_alive)
    monkeypatch.setattr(admin_scan, "_port_open", fake_alive)

    async with _client(app) as c:
        r = await c.post("/api/admin/scan-subnet", json={
            "ip_range": "192.168.1.10/32", "port": 554,
            "username": "admin", "password": "pw-rahasia-xyz",
        })
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        body = None
        for _ in range(200):
            r = await c.get(f"/api/admin/scan-subnet/{job_id}")
            assert r.status_code == 200, r.text
            body = r.json()
            if body["status"] == "done":
                break
            await asyncio.sleep(0.05)
        assert body is not None and body["status"] == "done", body
        assert "pw-rahasia-xyz" not in r.text
        hosts = body["hosts"]
        assert len(hosts) == 1
        assert hosts[0]["status"] == "video"
        assert "****" in (hosts[0]["best_main"] or "")
        assert hosts[0]["best_main"].endswith("/H.264")


# ---------- 4.7: rate limit endpoint ----------

async def test_recordings_cameras_rate_limited(app_client):
    """GET /recordings/cameras dibatasi 30/menit (4.7): ke-31 harus 429."""
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    auth_as(app, make_user())
    async with _client(app) as c:
        statuses = []
        for _ in range(31):
            r = await c.get("/api/recordings/cameras")
            statuses.append(r.status_code)
        assert statuses[:30] == [200] * 30, statuses
        assert statuses[30] == 429, statuses


# ---------- 4.10: WS idle timeout + revalidasi berkala ----------

async def test_ws_idle_timeout_closes(app_client, monkeypatch):
    """Koneksi WS tanpa pesan apa pun ditutup setelah idle timeout."""
    import pytest
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.models.streams import Stream
    from app.routers import ws as ws_router
    from tests.conftest import make_user

    app, _, db = app_client
    db.add(make_user(role="super_admin"))
    db.add(Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
                  main_url="rtsp://cam/1", is_active=True, is_online=True))
    await db.commit()
    monkeypatch.setattr(ws_router, "WS_IDLE_SECONDS", 0.5)
    monkeypatch.setattr(ws_router, "WS_REVALIDATE_SECONDS", 300.0)
    tok = create_access_token(1, "admin", "super_admin", get_settings())
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={tok}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            # Tanpa ping: server menutup dengan 1000 setelah 0.5 detik.
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 1000


async def test_ws_revalidate_closes_when_user_deactivated(
    app_client, monkeypatch, tmp_path
):
    """User dinonaktifkan di tengah sesi WS -> koneksi ditutup 4401."""
    import asyncio
    import threading

    import pytest
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from starlette.websockets import WebSocketDisconnect

    from app.models.streams import Stream
    from app.routers import ws as ws_router
    from tests.conftest import make_user

    app, _, db = app_client
    db.add(make_user(role="super_admin"))
    db.add(Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
                  main_url="rtsp://cam/1", is_active=True, is_online=True))
    await db.commit()
    monkeypatch.setattr(ws_router, "WS_REVALIDATE_SECONDS", 0.5)
    monkeypatch.setattr(ws_router, "WS_IDLE_SECONDS", 120.0)
    # Factory sesi baru ke file sqlite yang sama (dipakai _revalidate
    # dan thread penonaktif, bukan sesi fixture yang terikat loop tes).
    engine2 = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/test.db", poolclass=NullPool
    )
    factory2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ws_router, "get_session_factory", lambda: factory2)
    tok = create_access_token(1, "admin", "super_admin", get_settings())

    def _deactivate():
        time.sleep(0.8)

        async def _run():
            async with factory2() as s:
                user = await s.get(User, 1)
                user.is_active = False
                await s.commit()

        asyncio.run(_run())

    try:
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws?token={tok}") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "snapshot"
                threading.Thread(target=_deactivate, daemon=True).start()
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws.receive_json()
                assert exc.value.code == 4401
    finally:
        await engine2.dispose()


# ---------- 4.16/4.18: header keamanan + docs mati ----------

async def test_docs_disabled_by_default(app_client):
    """/docs, /redoc, /openapi.json mati bila API_DOCS_ENABLED=false."""
    app, _, _ = app_client
    async with _client(app) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            r = await c.get(path)
            assert r.status_code == 404, (path, r.status_code)


async def test_hsts_only_on_https(app_client):
    """HSTS hanya bila request lewat HTTPS (4.16), tidak di HTTP biasa."""
    app, _, _ = app_client
    async with _client(app) as c:
        r = await c.get("/api/health")
        assert "strict-transport-security" not in {k.lower() for k in r.headers}
        r = await c.get("/api/health", headers={"X-Forwarded-Proto": "https"})
        assert r.headers.get("strict-transport-security", "").startswith(
            "max-age=31536000"
        )


# ---------- 4.15: audit log untuk auth ----------

async def test_login_failure_writes_audit_log(app_client):
    """Login gagal tercatat di AuditLog (POST /api/auth/login)."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.models.misc import AuditLog

    app, _, db = app_client
    engine = db.bind
    app.state.audit_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with _client(app) as c:
        r = await c.post(
            "/api/auth/login", json={"username": "nope", "password": "salah"}
        )
        assert r.status_code == 401, r.text
    rows = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "POST /api/auth/login")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].detail["status_code"] == 401


# ---------- 4.17: guard probe SSRF ----------

def test_probe_guard_blocks_internal(monkeypatch):
    """host_allowed_for_probe: loopback/link-local/metadata selalu ditolak."""
    from app.services.stream_resolver import host_allowed_for_probe

    monkeypatch.setattr(get_settings(), "camera_probe_allow_loopback", False)
    assert host_allowed_for_probe("127.0.0.1") is False
    assert host_allowed_for_probe("::1") is False
    assert host_allowed_for_probe("localhost") is False
    assert host_allowed_for_probe("169.254.169.254") is False
    assert host_allowed_for_probe("0.0.0.0") is False
    assert host_allowed_for_probe("224.0.0.1") is False
    assert host_allowed_for_probe("") is False
    # Hostname yang gagal resolve = tolak. (DNS sandbox menjawab semua
    # nama host, jadi paksa kegagalan resolve lewat monkeypatch.)
    monkeypatch.setattr(
        "app.services.stream_resolver.socket.getaddrinfo",
        lambda *a, **k: (_ for _ in ()).throw(
            __import__("socket").gaierror("nxdomain")
        ),
    )
    assert host_allowed_for_probe("host-yang-tidak-ada.invalid") is False


def test_probe_guard_allows_lan_and_camera_networks(monkeypatch):
    """IP privat LAN diizinkan default; CAMERA_NETWORKS membatasi."""
    from app.services.stream_resolver import host_allowed_for_probe

    monkeypatch.setattr(get_settings(), "camera_networks", "")
    assert host_allowed_for_probe("10.12.13.5") is True
    assert host_allowed_for_probe("192.168.1.10") is True
    monkeypatch.setattr(get_settings(), "camera_networks", "10.12.13.0/24")
    assert host_allowed_for_probe("10.12.13.5") is True
    assert host_allowed_for_probe("192.168.1.10") is False
    # Loopback tetap ditolak walau CAMERA_NETWORKS mengizinkan 127/8.
    monkeypatch.setattr(get_settings(), "camera_networks", "127.0.0.0/8")
    monkeypatch.setattr(get_settings(), "camera_probe_allow_loopback", False)
    assert host_allowed_for_probe("127.0.0.1") is False
    # Escape hatch tes/lab: loopback diizinkan hanya bila flag nyala.
    monkeypatch.setattr(get_settings(), "camera_probe_allow_loopback", True)
    assert host_allowed_for_probe("127.0.0.1") is True


# ---------- 4.11: auth control API MediaMTX ----------

def test_mediamtx_auth_from_settings(monkeypatch):
    """get_mediamtx() mengirim Basic auth bila user/password dikonfigurasi."""
    from app.services.mediamtx import get_mediamtx
    from app.services.system_settings import set_mediamtx_password_cache

    # Cache password DB (diisi lifespan atau tes system_settings) menang
    # atas env; kosongkan dulu supaya tes ini menguji jalur env.
    set_mediamtx_password_cache(None)
    monkeypatch.setattr(get_settings(), "mediamtx_api_user", "netravision")
    monkeypatch.setattr(get_settings(), "mediamtx_api_password", "s3cret")
    client = get_mediamtx()
    # httpx membungkus tuple (user, pass) menjadi BasicAuth dengan
    # header "Basic base64(user:pass)".
    assert client._client.auth._auth_header == "Basic bmV0cmF2aXNpb246czNjcmV0"
    monkeypatch.setattr(get_settings(), "mediamtx_api_password", "")
    client2 = get_mediamtx()
    assert client2._client.auth is None


# ---------- 4.8: proxy tepercaya untuk X-Forwarded-For ----------

def test_client_ip_ignores_spoofed_forwarded_for(monkeypatch):
    """Peer privat yang tidak terdaftar tidak boleh memalsukan IP via XFF."""
    from starlette.requests import Request

    from app.core.rate_limit import client_ip

    def _req(peer, headers=None):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": (peer, 1234),
            "server": ("testserver", 80),
            "scheme": "http",
        }
        return Request(scope)

    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    # Peer privat 10.0.0.5 + XFF palsu -> IP klien = peer, bukan XFF.
    r = _req("10.0.0.5", {"X-Forwarded-For": "1.2.3.4"})
    assert client_ip(r) == "10.0.0.5"
    # Peer loopback (Apache di host yang sama) -> XFF dipercaya.
    r = _req("127.0.0.1", {"X-Forwarded-For": "1.2.3.4"})
    assert client_ip(r) == "1.2.3.4"
    # Peer privat yang didaftarkan eksplisit -> XFF dipercaya.
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    r = _req("10.0.0.5", {"X-Forwarded-For": "1.2.3.4"})
    assert client_ip(r) == "1.2.3.4"
    # Peer publik -> XFF tidak dipercaya.
    r = _req("8.8.8.8", {"X-Forwarded-For": "1.2.3.4"})
    assert client_ip(r) == "8.8.8.8"
