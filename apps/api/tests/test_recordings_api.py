"""Test 8 endpoint recordings dengan segmen palsu."""

import os
from datetime import date

from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.models.streams import Stream
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _seg(root, stream_id, name, size=2048):
    d = os.path.join(root, f"stream_{stream_id}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(b"v" * size)
    return p


async def _seed(app, db, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "recordings_dir", str(tmp_path))
    admin = make_user()
    db.add(admin)
    s = Stream(
        name="Cam 1",
        rtsp_url="rtsp://x/1",
        main_url="rtsp://x/1",
        is_active=True,
        recording_enabled=True,
    )
    db.add(s)
    await db.commit()
    auth_as(app, admin)
    return s


async def test_cameras_timeline_segments_dates(app_client, monkeypatch, tmp_path):
    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")
    _seg(str(tmp_path), s.id, "2026-11-02_11-00-00-000000.mp4")

    async with _client(app) as c:
        r = await c.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
        assert any(k["id"] == s.id for k in r.json())

        r = await c.get(f"/api/recordings/{s.id}/timeline", params={"date": "2026-11-02"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["date"] == "2026-11-02"
        assert len(data["entries"]) == 2

        r = await c.get(
            f"/api/recordings/{s.id}/segments", params={"date": "2026-11-02", "hour": 10}
        )
        segs = r.json()
        assert len(segs) == 1
        assert segs[0]["size_bytes"] == 2048
        assert f"/api/recordings/{s.id}/file" in segs[0]["url"]

        r = await c.get(f"/api/recordings/{s.id}/dates")
        assert r.json() == {"dates": ["2026-11-02"]}


async def test_stream_file_playbackurl_nextplayable(app_client, monkeypatch, tmp_path):
    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")

    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/stream",
            params={"start": "2026-11-02T10:15:00"},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "video/mp4"

        r = await c.get(
            f"/api/recordings/{s.id}/file",
            params={"start": "2026-11-02T10:15:00", "end": "2026-11-02T10:20:00"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"
        assert len(r.content) == 2048

        r = await c.get(
            f"/api/recordings/{s.id}/playback-url",
            params={"time": "2026-11-02T10:15:00"},
        )
        assert r.status_code == 200
        assert r.json()["url"].startswith(f"/api/recordings/{s.id}/file?")

        r = await c.get(
            f"/api/recordings/{s.id}/next-playable",
            params={"after": "2026-11-02T09:00:00"},
        )
        data = r.json()
        assert data["available"] is True
        assert data["time"].startswith("2026-11-02T10:00:00")

        r = await c.get(
            f"/api/recordings/{s.id}/next-playable",
            params={"after": "2026-11-10T00:00:00"},
        )
        assert r.json() == {"available": False, "time": None}


async def test_404_dan_validasi(app_client, monkeypatch, tmp_path):
    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)

    async with _client(app) as c:
        r = await c.get("/api/recordings/999/timeline")
        assert r.status_code == 404

        r = await c.get(
            f"/api/recordings/{s.id}/file",
            params={"start": "2026-11-02T10:20:00", "end": "2026-11-02T10:15:00"},
        )
        assert r.status_code == 400

        r = await c.get(
            f"/api/recordings/{s.id}/stream",
            params={"start": "2020-01-01T00:00:00"},
        )
        assert r.status_code == 404


async def test_non_admin_butuh_grant(app_client, monkeypatch, tmp_path):
    app, _, db = app_client
    await _seed(app, db, monkeypatch, tmp_path)
    op = make_user(id=2, username="op", role="user")
    db.add(op)
    await db.commit()
    auth_as(app, op)

    async with _client(app) as c:
        r = await c.get("/api/recordings/cameras")
        assert r.status_code == 200  # list boleh, difilter grant
        r = await c.get("/api/recordings/1/timeline")
        assert r.status_code == 403  # tanpa grant ke stream 1


async def test_today_default_date(app_client, monkeypatch, tmp_path):
    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    today = date.today().strftime("%Y-%m-%d")
    _seg(str(tmp_path), s.id, f"{today}_08-00-00-000000.mp4")
    async with _client(app) as c:
        r = await c.get(f"/api/recordings/{s.id}/timeline")
        assert r.json()["date"] == today
        assert len(r.json()["entries"]) == 1
