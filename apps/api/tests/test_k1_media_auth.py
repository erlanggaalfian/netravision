"""Test K-1: live stream tanpa auth ditutup oleh proxy media ber-auth.

Yang dibuktikan di sini (tanpa MediaMTX sungguhan; upstream dipalsukan
dengan httpx.MockTransport):
- HLS/WHEP tanpa kredensial -> 401, token salah/kedaluwarsa/untuk kamera
  lain -> 401, pengguna tanpa akses kamera -> 403.
- Pengguna login bisa menerbitkan token media lalu memutar stream lewat
  proxy (WHEP 201 + HLS playlist ditulis ulang + segmen diteruskan).
- Kunci embed bisa memutar lewat token sesi embed (?session=) yang
  sudah diterbitkan /external/stream; kunci dicabut -> sesi mati.
- Playback (rekaman) tetap berfungsi seperti semula (tidak lewat proxy
  media, tidak rusak oleh perubahan ini).

Router media TIDAK didaftarkan di app/main.py (milik koordinator), jadi
test ini mendaftarkannya sendiri ke app hasil create_app(), persis
seperti registrasi produksi: app.include_router(media.router,
prefix="/api").
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.models.access import UserStreamAccess
from app.models.keys import ApiKey, ApiKeyStream
from app.models.streams import Stream
from app.routers import external as external_router
from app.routers import media as media_router
from app.routers.media import MediaUpstream, get_media_upstream
from app.services.media_auth import (
    create_media_token,
    parse_media_path,
    rewrite_playlist,
    validate_media_token,
)
from tests.conftest import auth_as, make_user

MASTER_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:6\n"
    "#EXT-X-STREAM-INF:BANDWIDTH=1000000\n"
    "variant.m3u8\n"
)

VARIANT_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:6\n"
    "#EXT-X-TARGETDURATION:1\n"
    "#EXT-X-MAP:URI=\"init.mp4\"\n"
    "#EXTINF:1.0,\n"
    "seg-1.m4s\n"
    "#EXTINF:1.0,\n"
    "seg-2.m4s\n"
)


def _fake_upstream_handler(request: httpx.Request) -> httpx.Response:
    """MediaMTX palsu: WHEP + HLS seperti aslinya (tanpa auth)."""
    host = request.url.host
    path = request.url.path
    if host == "mtx-whep":
        if request.method == "POST" and path == "/stream_1/whep":
            return httpx.Response(
                201,
                text="v=0\r\nanswer-sdp",
                headers={
                    "Content-Type": "application/sdp",
                    "Location": "/stream_1/whep/sesi-abc",
                },
            )
        if request.method == "DELETE" and path == "/stream_1/whep/sesi-abc":
            return httpx.Response(200, text="")
        return httpx.Response(404, text="tidak ada")
    if host == "mtx-hls":
        if path == "/stream_1/index.m3u8":
            return httpx.Response(
                200,
                text=MASTER_PLAYLIST,
                headers={"Content-Type": "application/vnd.apple.mpegurl"},
            )
        if path == "/stream_1/variant.m3u8":
            return httpx.Response(
                200,
                text=VARIANT_PLAYLIST,
                headers={"Content-Type": "application/vnd.apple.mpegurl"},
            )
        if path == "/stream_1/seg-1.m4s":
            return httpx.Response(
                200, content=b"SEGMEN-1", headers={"Content-Type": "video/iso.segment"}
            )
        if path == "/stream_1/init.mp4":
            return httpx.Response(
                200, content=b"INIT", headers={"Content-Type": "video/mp4"}
            )
        return httpx.Response(404, text="tidak ada")
    return httpx.Response(404, text="tidak ada")


@pytest_asyncio.fixture
async def media_app(app_client):
    """App + upstream MediaMTX palsu + DB. Kembalikan (app, db)."""
    app, _, db = app_client
    app.include_router(media_router.router, prefix="/api")
    transport = httpx.MockTransport(_fake_upstream_handler)
    upstream = MediaUpstream("http://mtx-whep", "http://mtx-hls", transport=transport)

    async def _override():
        yield upstream

    app.dependency_overrides[get_media_upstream] = _override
    return app, db


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_streams(db):
    s1 = Stream(
        id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
        main_url="rtsp://cam/1", sub_url="rtsp://cam/1/sub",
        is_active=True, is_online=True,
    )
    s2 = Stream(
        id=2, name="Cam 2", rtsp_url="rtsp://cam/2",
        main_url="rtsp://cam/2",
        is_active=True, is_online=False,
    )
    db.add_all([s1, s2])
    await db.commit()
    return s1, s2


async def _seed_user(db, user_id=2, role="user", granted=(1,)):
    user = make_user(id=user_id, username=f"u{user_id}", role=role)
    db.add(user)
    for sid in granted:
        db.add(UserStreamAccess(user_id=user_id, stream_id=sid, can_view=True))
    await db.commit()
    return user


async def _seed_key(db, raw_key="KUNCI-EMBED-1", **kw):
    kwargs = dict(
        name="mitra", key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        is_active=True, session_ttl_mnt=60,
    )
    kwargs.update(kw)
    key = ApiKey(**kwargs)
    db.add(key)
    await db.flush()
    db.add(ApiKeyStream(api_key_id=key.id, stream_id=1))
    await db.commit()
    return key


async def _login_token(app, db, stream_id=1, sub=False):
    """Terbitkan token media lewat endpoint, sebagai super_admin.

    Baris user JUGA ditulis ke DB: proxy memeriksa ulang pengguna
    (is_active + akses kamera) di tiap request, jadi token untuk
    user yang tidak ada di DB memang harus ditolak.
    """
    admin = make_user(id=1, username="admin", role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post(
            "/api/media/token", json={"stream_id": stream_id, "sub": sub}
        )
        assert r.status_code == 200, r.text
        return r.json()["token"]


# --- unit: media_auth ---

def test_parse_media_path_ok():
    assert parse_media_path("stream_1") == (1, False)
    assert parse_media_path("stream_12_sub") == (12, True)


def test_parse_media_path_rejects_traversal():
    for bad in ("", "stream_", "stream_0", "stream_-1", "../stream_1",
                "stream_1/../../etc/passwd", "stream_1_sub_extra",
                "STREAM_1", "stream_1/", "/stream_1"):
        with pytest.raises(ValueError):
            parse_media_path(bad)


def test_media_token_roundtrip_and_wrong_path():
    settings = get_settings()
    token, _ = create_media_token(
        settings, subject="7", stream_id=3, path="stream_3_sub"
    )
    payload = validate_media_token(token, settings)
    assert payload["stream_id"] == 3
    assert payload["path"] == "stream_3_sub"
    assert payload["type"] == "media"
    with pytest.raises(ValueError):
        create_media_token(settings, subject="7", stream_id=3, path="stream_4")


def test_media_token_expired_rejected():
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "7", "type": "media", "kind": "media",
        "stream_id": 1, "path": "stream_1",
        "iat": now - timedelta(minutes=10),
        "exp": now - timedelta(minutes=5),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(ValueError):
        validate_media_token(token, settings)


def test_rewrite_playlist_appends_credential():
    out = rewrite_playlist(VARIANT_PLAYLIST, "token=TOK")
    assert "init.mp4?token=TOK" in out
    assert "seg-1.m4s?token=TOK" in out
    assert "seg-2.m4s?token=TOK" in out
    assert "#EXTINF:1.0," in out
    out2 = rewrite_playlist(MASTER_PLAYLIST, "session=SES")
    assert "variant.m3u8?session=SES" in out2


def test_rewrite_playlist_leaves_absolute_urls():
    text = "#EXTM3U\nhttps://cdn.example.com/seg.m4s\nseg-1.m4s\n"
    out = rewrite_playlist(text, "token=TOK")
    assert "https://cdn.example.com/seg.m4s\n" in out
    assert "seg-1.m4s?token=TOK" in out


# --- tanpa kredensial: ditolak ---

async def test_whep_no_token_401(media_app):
    app, db = media_app
    await _seed_streams(db)
    async with _client(app) as c:
        r = await c.post(
            "/api/media/whep/stream_1/whep",
            content="v=0\r\noffer",
            headers={"Content-Type": "application/sdp"},
        )
        assert r.status_code == 401, r.text


async def test_hls_no_token_401(media_app):
    app, db = media_app
    await _seed_streams(db)
    async with _client(app) as c:
        r = await c.get("/api/media/hls/stream_1/index.m3u8")
        assert r.status_code == 401, r.text
        r = await c.get("/api/media/hls/stream_1/seg-1.m4s")
        assert r.status_code == 401, r.text


async def test_hls_bad_token_401(media_app):
    app, db = media_app
    await _seed_streams(db)
    async with _client(app) as c:
        r = await c.get(
            "/api/media/hls/stream_1/index.m3u8", params={"token": "bukan-token"}
        )
        assert r.status_code == 401, r.text


async def test_hls_token_wrong_camera_401(media_app):
    app, db = media_app
    await _seed_streams(db)
    token = await _login_token(app, db, stream_id=1)
    async with _client(app) as c:
        r = await c.get(
            "/api/media/hls/stream_2/index.m3u8", params={"token": token}
        )
        assert r.status_code == 401, r.text


async def test_hls_path_traversal_404(media_app):
    app, db = media_app
    await _seed_streams(db)
    token = await _login_token(app, db, stream_id=1)
    async with _client(app) as c:
        r = await c.get(
            "/api/media/hls/..%2F..%2Fetc/passwd", params={"token": token}
        )
        assert r.status_code in (401, 404), r.text
        r = await c.get("/api/media/hls/stream_1", params={"token": token})
        assert r.status_code == 404, r.text


# --- penerbitan token ---

async def test_issue_token_requires_login(media_app):
    app, db = media_app
    await _seed_streams(db)
    async with _client(app) as c:
        r = await c.post("/api/media/token", json={"stream_id": 1})
        assert r.status_code == 401, r.text


async def test_issue_token_forbidden_without_grant(media_app):
    app, db = media_app
    await _seed_streams(db)
    user = await _seed_user(db, user_id=2, granted=(1,))
    auth_as(app, user)
    async with _client(app) as c:
        r = await c.post("/api/media/token", json={"stream_id": 2})
        assert r.status_code == 403, r.text


async def test_issue_token_ok_returns_urls(media_app):
    app, db = media_app
    await _seed_streams(db)
    user = await _seed_user(db, user_id=2, granted=(1,))
    auth_as(app, user)
    async with _client(app) as c:
        r = await c.post(
            "/api/media/token", json={"stream_id": 1, "sub": True}
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["path"] == "stream_1_sub"
        assert data["whep_url"].startswith("/whep/stream_1_sub/whep?token=")
        assert data["hls_url"].startswith("/hls/stream_1_sub/index.m3u8?token=")
        payload = validate_media_token(data["token"], get_settings())
        assert payload["path"] == "stream_1_sub"


async def test_issue_token_sub_missing_404(media_app):
    app, db = media_app
    await _seed_streams(db)
    admin = make_user(id=1, username="admin", role="super_admin")
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/media/token", json={"stream_id": 2, "sub": True})
        assert r.status_code == 404, r.text


# --- proxy dengan token media ---

async def test_whep_proxied_with_media_token(media_app):
    app, db = media_app
    await _seed_streams(db)
    token = await _login_token(app, db, stream_id=1)
    async with _client(app) as c:
        r = await c.post(
            "/api/media/whep/stream_1/whep",
            params={"token": token},
            content="v=0\r\noffer",
            headers={"Content-Type": "application/sdp"},
        )
        assert r.status_code == 201, r.text
        assert r.text == "v=0\r\nanswer-sdp"
        assert r.headers["content-type"].startswith("application/sdp")
        # Location upstream ditulis ulang ke prefix publik /whep/.
        assert r.headers["location"] == "/whep/stream_1/whep/sesi-abc"


async def test_whep_bearer_token_ok(media_app):
    app, db = media_app
    await _seed_streams(db)
    token = await _login_token(app, db, stream_id=1)
    async with _client(app) as c:
        r = await c.post(
            "/api/media/whep/stream_1/whep",
            content="v=0\r\noffer",
            headers={
                "Content-Type": "application/sdp",
                "Authorization": f"Bearer {token}",
            },
        )
        assert r.status_code == 201, r.text


async def test_hls_playlist_rewritten_and_segment_ok(media_app):
    app, db = media_app
    await _seed_streams(db)
    token = await _login_token(app, db, stream_id=1)
    async with _client(app) as c:
        r = await c.get(
            "/api/media/hls/stream_1/index.m3u8", params={"token": token}
        )
        assert r.status_code == 200, r.text
        assert "variant.m3u8?token=" in r.text
        # Segmen yang ditempel token di playlist harus bisa diambil.
        r2 = await c.get(
            "/api/media/hls/stream_1/variant.m3u8", params={"token": token}
        )
        assert r2.status_code == 200, r2.text
        assert "seg-1.m4s?token=" in r2.text
        assert "init.mp4?token=" in r2.text
        r3 = await c.get(
            "/api/media/hls/stream_1/seg-1.m4s", params={"token": token}
        )
        assert r3.status_code == 200, r3.text
        assert r3.content == b"SEGMEN-1"


async def test_hls_revoked_grant_kills_token(media_app):
    """Grant dicabut setelah token terbit: proxy menolak (403)."""
    app, db = media_app
    await _seed_streams(db)
    user = await _seed_user(db, user_id=2, granted=(1,))
    auth_as(app, user)
    async with _client(app) as c:
        r = await c.post("/api/media/token", json={"stream_id": 1})
        assert r.status_code == 200, r.text
        token = r.json()["token"]
    grant = (
        await db.execute(
            UserStreamAccess.__table__.select().where(
                UserStreamAccess.user_id == 2,
                UserStreamAccess.stream_id == 1,
            )
        )
    ).first()
    assert grant is not None
    await db.execute(
        UserStreamAccess.__table__.delete().where(
            UserStreamAccess.user_id == 2,
            UserStreamAccess.stream_id == 1,
        )
    )
    await db.commit()
    async with _client(app) as c:
        r = await c.get(
            "/api/media/hls/stream_1/index.m3u8", params={"token": token}
        )
        assert r.status_code == 403, r.text


# --- embed: token sesi ---

async def test_embed_session_whep_ok(media_app):
    app, db = media_app
    await _seed_streams(db)
    key = await _seed_key(db)
    session = external_router._session_token(key, 1, 60)
    async with _client(app) as c:
        r = await c.post(
            "/api/media/whep/stream_1/whep",
            params={"session": session},
            content="v=0\r\noffer",
            headers={"Content-Type": "application/sdp"},
        )
        assert r.status_code == 201, r.text


async def test_embed_session_hls_ok(media_app):
    app, db = media_app
    await _seed_streams(db)
    key = await _seed_key(db)
    session = external_router._session_token(key, 1, 60)
    async with _client(app) as c:
        r = await c.get(
            "/api/media/hls/stream_1/index.m3u8", params={"session": session}
        )
        assert r.status_code == 200, r.text
        assert "variant.m3u8?session=" in r.text


async def test_embed_session_wrong_camera_401(media_app):
    app, db = media_app
    await _seed_streams(db)
    key = await _seed_key(db)
    session = external_router._session_token(key, 1, 60)
    async with _client(app) as c:
        r = await c.post(
            "/api/media/whep/stream_2/whep",
            params={"session": session},
            content="v=0\r\noffer",
            headers={"Content-Type": "application/sdp"},
        )
        assert r.status_code == 401, r.text


async def test_embed_key_revoked_kills_session(media_app):
    """Kunci dinonaktifkan setelah sesi terbit: proxy menolak (401)."""
    app, db = media_app
    await _seed_streams(db)
    key = await _seed_key(db)
    session = external_router._session_token(key, 1, 60)
    key.is_active = False
    await db.commit()
    async with _client(app) as c:
        r = await c.get(
            "/api/media/hls/stream_1/index.m3u8", params={"session": session}
        )
        assert r.status_code == 401, r.text


# --- Playback (rekaman) tidak rusak ---

async def test_playback_endpoints_untouched(media_app, tmp_path):
    """GET /api/recordings/cameras tetap butuh login dan tetap 200
    untuk super_admin; router media tidak membayangi jalurnya."""
    app, db = media_app
    await _seed_streams(db)
    async with _client(app) as c:
        r = await c.get("/api/recordings/cameras")
        assert r.status_code == 401, r.text
    admin = make_user(id=1, username="admin", role="super_admin")
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
