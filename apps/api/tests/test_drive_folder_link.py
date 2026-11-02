"""Test mode folder-link + rclone (Google Drive ala fieriindra)."""

import os
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.routers.admin_drive import parse_gdrive_folder_id
from app.services.drive_mirror import _mirror_tick
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_parse_gdrive_folder_id():
    assert (
        parse_gdrive_folder_id("https://drive.google.com/drive/folders/1AbC_-xYz09")
        == "1AbC_-xYz09"
    )
    assert (
        parse_gdrive_folder_id("https://drive.google.com/drive/folders/1AbC_-xYz09?usp=sharing")
        == "1AbC_-xYz09"
    )
    assert (
        parse_gdrive_folder_id("https://drive.google.com/open?id=1Q2w3E4r5T")
        == "1Q2w3E4r5T"
    )
    assert parse_gdrive_folder_id("https://drive.google.com/drive/home") == ""
    assert parse_gdrive_folder_id("") == ""
    assert parse_gdrive_folder_id("bukan url") == ""


@pytest.mark.asyncio
async def test_gdrive_setting_roundtrip(app_client):
    app, _, _ = app_client
    auth_as(app, make_user())
    async with _client(app) as c:
        r = await c.get("/api/admin/storage/google-drive")
        assert r.status_code == 200
        assert r.json()["configured"] is False

        r = await c.put(
            "/api/admin/storage/google-drive",
            json={
                "folder_url": "https://drive.google.com/drive/folders/1AbC_-xYz09",
                "folder_name": "CCTV",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is True
        assert body["folder_id"] == "1AbC_-xYz09"
        assert body["folder_name"] == "CCTV"
        assert body["updated_by"] == "admin"

        r = await c.get("/api/admin/storage/google-drive")
        assert r.json()["folder_id"] == "1AbC_-xYz09"


@pytest.mark.asyncio
async def test_gdrive_setting_invalid_url(app_client):
    app, _, _ = app_client
    auth_as(app, make_user())
    async with _client(app) as c:
        r = await c.put(
            "/api/admin/storage/google-drive",
            json={"folder_url": "https://drive.google.com/drive/home"},
        )
        assert r.status_code == 400
        assert "tidak dikenali" in r.json()["detail"]


@pytest.mark.asyncio
async def test_disks_includes_google_drive(app_client, monkeypatch, tmp_path):
    app, _, _ = app_client
    auth_as(app, make_user())
    s = get_settings()
    monkeypatch.setattr(s, "gdrive_record_path", str(tmp_path / "staging"))
    monkeypatch.setattr(s, "gdrive_quota_tb", 5.0)
    try:
        async with _client(app) as c:
            r = await c.get("/api/admin/disks")
            assert r.status_code == 200
            body = r.json()
            assert "google_drive" in body
            gd = body["google_drive"]
            assert gd["storage_type"] == "google_drive"
            assert gd["size_bytes"] == 5 * (1024**4)
            assert gd["label"] == "Google Drive"
    finally:
        get_settings.cache_clear()


def test_mirror_tick_copies_stable_files(monkeypatch, tmp_path):
    rec = tmp_path / "recordings" / "stream_7"
    rec.mkdir(parents=True)
    stable = rec / "2026-11-02_10-00-00.mp4"
    stable.write_bytes(b"x" * 100)
    old = time.time() - 60
    os.utime(stable, (old, old))
    fresh = rec / "2026-11-02_10-05-00.mp4"
    fresh.write_bytes(b"y" * 100)  # mtime baru → belum stabil

    s = get_settings()
    monkeypatch.setattr(s, "recordings_dir", str(tmp_path / "recordings"))
    monkeypatch.setattr(s, "gdrive_record_path", str(tmp_path / "staging"))
    try:
        _mirror_tick([(7, "Gudang")])
        dst = tmp_path / "staging" / "stream_7"
        assert (dst / "2026-11-02_10-00-00.mp4").exists()
        assert not (dst / "2026-11-02_10-05-00.mp4").exists()
        # idempotent: putaran kedua tidak error & tidak duplikat
        _mirror_tick([(7, "Gudang")])
        assert len(list(dst.iterdir())) == 1
    finally:
        get_settings.cache_clear()
