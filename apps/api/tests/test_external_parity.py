"""Test parity kontrak backend v2.0 (bukan ImportError/503, field aditif, filter)."""

import hashlib
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream
from app.models.misc import AdConfig
from app.models.streams import Stream
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _seed_key(db, raw_key="KUNCI-1"):
    key = ApiKey(
        name="mitra", key_hash=_sha(raw_key), is_active=True, session_ttl_mnt=60
    )
    db.add(key)
    await db.flush()
    s1 = Stream(
        id=11, name="Cam A", rtsp_url="rtsp://a/1", main_url="rtsp://a/1",
        sub_url="rtsp://a/1/sub", is_active=True, is_online=True,
        latitude=-6.2, longitude=106.8,
    )
    s2 = Stream(
        id=12, name="Cam B", rtsp_url="rtsp://b/1", main_url="rtsp://b/1",
        is_active=True,
    )
    db.add_all([s1, s2])
    db.add_all([
        ApiKeyStream(api_key_id=key.id, stream_id=11),
        ApiKeyStream(api_key_id=key.id, stream_id=12),
    ])
    await db.commit()
    return key


async def test_playback_tidak_503(app_client):
    """BUG KRITIS: /external/playback tidak boleh 503 (dulu ImportError)."""
    app, _, db = app_client
    await _seed_key(db)
    async with _client(app) as c:
        r = await c.get(
            "/api/external/playback", params={"key": "KUNCI-1", "camera": 1}
        )
        assert r.status_code == 200, r.text
        assert r.status_code != 503
        data = r.json()
        assert "dates" in data  # tanpa rekaman -> daftar tanggal kosong
        assert data["camera"] == 1
        assert data["total_cameras"] == 2


async def test_playback_bad_camera_403(app_client):
    app, _, db = app_client
    await _seed_key(db)
    async with _client(app) as c:
        r = await c.get(
            "/api/external/playback", params={"key": "KUNCI-1", "camera": 9}
        )
        assert r.status_code == 403


async def test_stream_field_aditif(app_client):
    """/external/stream: field v3.0 tetap + stream.* dan ad (v2.0, aditif)."""
    app, _, db = app_client
    await _seed_key(db)
    db.add(AdConfig(
        key="default",
        value={"is_active": True, "marquee_text": "Halo",
               "embed_timeout_seconds": 120, "click_to_play": False},
    ))
    await db.commit()
    async with _client(app) as c:
        r = await c.get(
            "/api/external/stream", params={"key": "KUNCI-1", "camera": 1}
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # field v3.0 tetap ada
        assert "url" in data and "expires_at" in data
        # field v2.0 aditif
        st = data["stream"]
        assert st["id"] == 11
        assert st["name"] == "Cam A"
        assert st["webrtc_url"] == data["url"]
        assert st["webrtc_url_sub"] is not None  # sub_url diset
        assert st["coordinates"] == "-6.2,106.8"
        assert st["embed_timeout_seconds"] == 120
        assert st["click_to_play"] is False
        ad = data["ad"]
        assert ad["marquee_text"] == "Halo"
        assert ad["is_active"] is True
        assert ad["box_width"] == 100  # default v2.0


async def test_stream_tanpa_sub(app_client):
    app, _, db = app_client
    await _seed_key(db)
    async with _client(app) as c:
        r = await c.get(
            "/api/external/stream", params={"key": "KUNCI-1", "camera": 2}
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Sub transkode selalu tersedia (pola v2), walau kamera tanpa sub_url.
        assert "/stream_12_sub/whep" in data["stream"]["webrtc_url_sub"]
        assert data["stream"]["coordinates"] is None


async def test_cameras_filter_satu_kamera(app_client):
    """/external/cameras mendukung ?camera= (v2.0 embed)."""
    app, _, db = app_client
    await _seed_key(db)
    async with _client(app) as c:
        r = await c.get(
            "/api/external/cameras",
            params={"key": "KUNCI-1", "camera": 2},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data) == 1 and data[0]["id"] == 12
        # tanpa filter -> semua
        r = await c.get("/api/external/cameras", params={"key": "KUNCI-1"})
        assert len(r.json()) == 2


async def test_streams_paginasi_dan_group(app_client):
    """/api/streams: ?page/?limit/?group (v2.0); tanpa param = list penuh."""
    app, _, db = app_client
    admin = make_user()
    db.add(admin)
    for i in range(1, 6):
        db.add(Stream(
            id=i, name=f"Cam {i}", rtsp_url=f"rtsp://x/{i}",
            main_url=f"rtsp://x/{i}", is_active=True,
            group_name="Gedung A" if i <= 2 else "Parkir",
        ))
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/streams")
        assert len(r.json()) == 5  # penuh
        r = await c.get("/api/streams", params={"page": 2, "limit": 2})
        assert [s["id"] for s in r.json()] == [3, 4]
        r = await c.get("/api/streams", params={"page": 1})  # limit default 20
        assert len(r.json()) == 5
        r = await c.get("/api/streams", params={"group": "Parkir"})
        assert {s["id"] for s in r.json()} == {3, 4, 5}
        r = await c.get(
            "/api/streams", params={"group": "Parkir", "page": 1, "limit": 2}
        )
        assert len(r.json()) == 2
        r = await c.get("/api/streams", params={"no_check": True})
        assert len(r.json()) == 5


async def _seed_logs(db):
    admin = make_user()
    db.add(admin)
    now = datetime.now(timezone.utc)
    logs = [
        ApiAccessLog(api_key_id=1, action="external.cameras.ok",
                     created_at=now - timedelta(days=10)),
        ApiAccessLog(api_key_id=1, action="external.stream.denied:bad_key",
                     created_at=now - timedelta(days=1)),
        ApiAccessLog(api_key_id=2, action="external.stream.ok",
                     created_at=now),
    ]
    db.add_all(logs)
    await db.commit()
    return admin


async def test_logs_status_dan_offset(app_client):
    app, _, db = app_client
    admin = await _seed_logs(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get(
            "/api/admin/api-access-logs", params={"status": "denied"}
        )
        assert r.status_code == 200, r.text
        assert len(r.json()) == 1
        r = await c.get("/api/admin/api-access-logs", params={"status": "hit"})
        assert len(r.json()) == 2
        r = await c.get(
            "/api/admin/api-access-logs", params={"limit": 1, "offset": 1}
        )
        assert len(r.json()) == 1
        # id desc -> offset 1 melewati yang terbaru
        r0 = await c.get("/api/admin/api-access-logs", params={"limit": 1})
        assert r.json()[0]["id"] != r0.json()[0]["id"]


async def test_delete_logs_days(app_client):
    app, _, db = app_client
    admin = await _seed_logs(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.delete(
            "/api/admin/api-access-logs", params={"days": 5}
        )
        assert r.status_code == 200, r.text
        res = await db.execute(select(ApiAccessLog))
        remaining = res.scalars().all()
        assert len(remaining) == 2  # yang 10 hari lalu terhapus
        # tanpa days = hapus semua
        r = await c.delete("/api/admin/api-access-logs")
        assert r.status_code == 200
        res = await db.execute(select(ApiAccessLog))
        assert res.scalars().all() == []
