"""Test router external/embed: validasi key, domain lock, password, logging."""

import hashlib
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream
from app.models.streams import Stream


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _seed(db, raw_key="KUNCI-RAHASIA-123", **kw):
    kwargs = dict(
        name="mitra-a",
        key_hash=_sha(raw_key),
        is_active=True,
        session_ttl_mnt=60,
    )
    kwargs.update(kw)
    key = ApiKey(**kwargs)
    db.add(key)
    await db.flush()
    s1 = Stream(
        id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
        main_url="rtsp://cam/1", is_active=True, is_online=True,
    )
    s2 = Stream(
        id=2, name="Cam 2", rtsp_url="rtsp://cam/2",
        main_url="rtsp://cam/2", is_active=True, is_online=False,
    )
    db.add_all([s1, s2])
    db.add_all([
        ApiKeyStream(api_key_id=key.id, stream_id=1),
        ApiKeyStream(api_key_id=key.id, stream_id=2),
    ])
    await db.commit()
    return key


async def _logs(db):
    result = await db.execute(select(ApiAccessLog))
    return result.scalars().all()


async def test_cameras_ok(app_client):
    app, _, db = app_client
    await _seed(db)
    async with _client(app) as c:
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": "KUNCI-RAHASIA-123"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list) and len(data) == 2
        assert {d["id"] for d in data} == {1, 2}
        assert all("name" in d and "is_online" in d for d in data)
    logs = await _logs(db)
    assert any(log.action == "external.cameras.ok" for log in logs)


async def test_bad_key_ditolak(app_client):
    app, _, db = app_client
    await _seed(db)
    async with _client(app) as c:
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": "SALAH"})
        assert r.status_code == 403
        r = await c.get("/api/external/stream", params={"camera": 1}, headers={"X-Api-Key": "SALAH"})
        assert r.status_code == 403
    logs = await _logs(db)
    assert any("denied:bad_key" in log.action for log in logs)


async def test_expired_ditolak(app_client):
    app, _, db = app_client
    await _seed(
        db,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    async with _client(app) as c:
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": "KUNCI-RAHASIA-123"})
        assert r.status_code == 403


async def test_inactive_ditolak(app_client):
    app, _, db = app_client
    await _seed(db, is_active=False)
    async with _client(app) as c:
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": "KUNCI-RAHASIA-123"})
        assert r.status_code == 403


async def test_password_wajib(app_client):
    from app.core.security import hash_password

    app, _, db = app_client
    await _seed(db, password_hash=hash_password("sandi123"))
    async with _client(app) as c:
        r = await c.get(
            "/api/external/cameras",
            headers={"X-Api-Key": "KUNCI-RAHASIA-123"},
        )
        assert r.status_code == 403  # tanpa password
        r = await c.get(
            "/api/external/cameras",
            headers={
                "X-Api-Key": "KUNCI-RAHASIA-123",
                "X-Api-Key-Password": "keliru",
            },
        )
        assert r.status_code == 403  # password salah
        r = await c.get(
            "/api/external/cameras",
            headers={
                "X-Api-Key": "KUNCI-RAHASIA-123",
                "X-Api-Key-Password": "sandi123",
            },
        )
        assert r.status_code == 200  # password benar via header


async def test_query_key_ditolak_400(app_client):
    """2026-11-18 (BREAKING CHANGE): kredensial embed lewat query
    string (?key=/?password=/?pass=) ditolak 400; jalur sah hanya header.
    Header yang sama harus tetap diterima (200)."""
    app, _, db = app_client
    await _seed(db)
    async with _client(app) as c:
        r = await c.get("/api/external/cameras?key=KUNCI-RAHASIA-123")
        assert r.status_code == 400, r.text
        r = await c.get(
            "/api/external/cameras?key=KUNCI-RAHASIA-123&pass=sandi123"
        )
        assert r.status_code == 400, r.text
        r = await c.get(
            "/api/external/cameras",
            headers={"X-Api-Key": "KUNCI-RAHASIA-123"},
        )
        assert r.status_code == 200, r.text


async def test_domain_lock(app_client):
    app, _, db = app_client
    await _seed(db, domain_lock="mitra.example.com")
    async with _client(app) as c:
        # tanpa referer/origin -> tolak
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": "KUNCI-RAHASIA-123"})
        assert r.status_code == 403
        # referer cocok (termasuk subdomain)
        r = await c.get(
            "/api/external/cameras",
            headers={
                "X-Api-Key": "KUNCI-RAHASIA-123",
                "referer": "https://app.mitra.example.com/embed",
            },
        )
        assert r.status_code == 200
        # domain penyerang mirip -> tolak
        r = await c.get(
            "/api/external/cameras",
            headers={
                "X-Api-Key": "KUNCI-RAHASIA-123",
                "origin": "https://notmitra.example.com",
            },
        )
        assert r.status_code == 403


async def test_stream_ok_dan_kamera_salah(app_client):
    app, _, db = app_client
    await _seed(db)
    async with _client(app) as c:
        # camera=1 -> kamera pertama
        r = await c.get(
            "/api/external/stream",
            params={"camera": 1},
            headers={"X-Api-Key": "KUNCI-RAHASIA-123"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "url" in data and "expires_at" in data  # bentuk kontrak FROZEN
        assert "/whep/stream_1/whep" in data["url"]

        # stream_id sebagai alias
        r = await c.get(
            "/api/external/stream",
            params={"stream_id": 2},
            headers={"X-Api-Key": "KUNCI-RAHASIA-123"},
        )
        assert r.status_code == 200
        assert "/whep/stream_2/whep" in r.json()["url"]

        # kamera di luar hak kunci -> 403
        r = await c.get(
            "/api/external/stream",
            params={"camera": 99},
            headers={"X-Api-Key": "KUNCI-RAHASIA-123"},
        )
        assert r.status_code == 403
    logs = await _logs(db)
    assert any(log.action == "external.stream.ok" for log in logs)


async def test_playback_tidak_lagi_503(app_client):
    """BUG diperbaiki: /external/playback tidak lagi 503 (ImportError).

    Tanpa rekaman -> 200 dengan daftar tanggal (kosong), bukan 503.
    """
    app, _, db = app_client
    await _seed(db)
    async with _client(app) as c:
        r = await c.get(
            "/api/external/playback",
            params={"camera": 1},
            headers={"X-Api-Key": "KUNCI-RAHASIA-123"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "dates" in data
        assert data["camera"] == 1


async def test_session_token_dicabut_bila_key_nonaktif(app_client):
    """S-2: token sesi embed ditolak bila key dinonaktifkan, kedaluwarsa,
    atau kamera tidak lagi terikat key itu (pencabutan langsung)."""
    import pytest

    from app.routers.external import _session_token, _validate_session_token

    _, _, db = app_client
    key = await _seed(db)
    token = _session_token(key, 1, 60)
    assert await _validate_session_token(db, token, 1) == key.id

    # Key dinonaktifkan -> token mati walau belum kedaluwarsa.
    key.is_active = False
    await db.commit()
    with pytest.raises(ValueError, match="tidak aktif"):
        await _validate_session_token(db, token, 1)
    key.is_active = True

    # Kamera dilepas dari key -> token mati.
    row = (await db.execute(
        select(ApiKeyStream).where(
            ApiKeyStream.api_key_id == key.id,
            ApiKeyStream.stream_id == 1,
        )
    )).scalars().first()
    await db.delete(row)
    await db.commit()
    with pytest.raises(ValueError, match="tidak lagi terikat"):
        await _validate_session_token(db, token, 1)

    # Key kedaluwarsa -> token mati.
    db.add(ApiKeyStream(api_key_id=key.id, stream_id=1))
    key.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()
    with pytest.raises(ValueError, match="kedaluwarsa"):
        await _validate_session_token(db, token, 1)
