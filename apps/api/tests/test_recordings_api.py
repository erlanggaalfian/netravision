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
        created_by=admin.id,  # paritas v2.0: admin membuka rekaman kamera pasangannya
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


async def test_playback_baca_drive_rclone(app_client, monkeypatch, tmp_path):
    """Putar Ulang baca segmen Drive rclone (disk1) bila storage drive.

    Lokal menang bila nama sama (mode both). File disajikan via rclone cat.
    """
    from app.models.drive import GoogleDriveFolder
    from app.services import gdrive_rclone as gr

    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    s.storage_mode = "drive"
    folder = GoogleDriveFolder(
        folder_url="https://drive.google.com/drive/folders/folder-abc",
        folder_id="folder-abc",
        folder_name="netravision",
        remote_name="gdrive",
    )
    db.add(folder)
    await db.commit()
    s.drive_folder_id = folder.id
    await db.commit()

    async def _fake_list(remote_name, path):
        assert remote_name == "gdrive"
        # Jalur rclone memakai NAMA folder (netravision), bukan ID Drive:
        # ID yang dipakai sebagai jalur membuat rclone membuat folder baru
        # bernama ID itu.
        assert path == "netravision/Cam 1"
        return [
            {"name": "2026-11-02_10-00-00-000000.mp4", "size": 5000, "id": "f1"},
            {"name": "2026-11-02_10-10-00-000000.mp4", "size": 6000, "id": "f2"},
            {"name": "bukan-segmen.txt", "size": 10, "id": "f3"},
        ]

    async def _fake_stream(remote_name, path, start, end):
        assert remote_name == "gdrive"
        assert path == "netravision/Cam 1/2026-11-02_10-00-00-000000.mp4"
        return b"v" * (end - start + 1)

    monkeypatch.setattr(gr, "list_rclone_files", _fake_list)
    monkeypatch.setattr(gr, "stream_rclone_file", _fake_stream)

    async with _client(app) as c:
        # Timeline memuat 2 segmen rclone.
        r = await c.get(
            f"/api/recordings/{s.id}/timeline", params={"date": "2026-11-02"}
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["entries"]) == 2

        # Segmen: URL file tersedia.
        r = await c.get(
            f"/api/recordings/{s.id}/segments", params={"date": "2026-11-02"}
        )
        assert r.status_code == 200, r.text
        segs = r.json()
        assert len(segs) == 2
        assert segs[0]["size_bytes"] == 5000

        # File disajikan via rclone cat (Range).
        url = segs[0]["url"]
        r = await c.get(url, headers={"Range": "bytes=0-99"})
        assert r.status_code == 206, r.text
        assert len(r.content) == 100
        assert r.headers.get("Content-Range") == "bytes 0-99/5000"


async def test_playback_both_utamakan_lokal(app_client, monkeypatch, tmp_path):
    """Mode both: segmen lokal menang bila nama sama dengan Drive."""
    from app.models.drive import GoogleDriveFolder
    from app.services import gdrive_rclone as gr

    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    s.storage_mode = "both"
    folder = GoogleDriveFolder(
        folder_url="https://drive.google.com/drive/folders/folder-abc",
        folder_id="folder-abc",
        folder_name="netravision",
        remote_name="gdrive",
    )
    db.add(folder)
    await db.commit()
    s.drive_folder_id = folder.id
    await db.commit()
    # Lokal punya segmen 10:00, Drive punya 10:00 + 10:10.
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4", size=2048)

    async def _fake_list(remote_name, path):
        return [
            {"name": "2026-11-02_10-00-00-000000.mp4", "size": 5000, "id": "f1"},
            {"name": "2026-11-02_10-10-00-000000.mp4", "size": 6000, "id": "f2"},
        ]

    monkeypatch.setattr(gr, "list_rclone_files", _fake_list)

    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/segments", params={"date": "2026-11-02"}
        )
        assert r.status_code == 200, r.text
        segs = r.json()
        assert len(segs) == 2
        # 10:00 dari lokal (size 2048), 10:10 dari Drive (size 6000).
        assert segs[0]["size_bytes"] == 2048
        assert segs[1]["size_bytes"] == 6000
