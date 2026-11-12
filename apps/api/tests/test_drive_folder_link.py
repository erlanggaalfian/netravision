"""Test mode folder-link + rclone multi-tautan (Google Drive)."""

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
async def test_gdrive_folders_crud(app_client):
    app, _, _ = app_client
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.get("/api/admin/storage/google-drive")
        assert r.status_code == 200
        assert r.json()["folders"] == []

        # Tambah dua folder
        r = await c.post(
            "/api/admin/storage/google-drive",
            json={
                "folder_url": "https://drive.google.com/drive/folders/1AbC_-xYz09",
                "folder_name": "CCTV-1",
                "local_path": "/mnt/gdrive1",
            },
        )
        assert r.status_code == 201
        f1 = r.json()
        assert f1["folder_id"] == "1AbC_-xYz09"
        assert f1["local_path"] == "/mnt/gdrive1"

        r = await c.post(
            "/api/admin/storage/google-drive",
            json={
                "folder_url": "https://drive.google.com/drive/folders/2QwE_-rTy12",
                "folder_name": "CCTV-2",
            },
        )
        assert r.status_code == 201
        f2 = r.json()

        r = await c.get("/api/admin/storage/google-drive")
        assert len(r.json()["folders"]) == 2

        # Ubah
        r = await c.put(
            f"/api/admin/storage/google-drive/{f1['id']}",
            json={
                "folder_url": "https://drive.google.com/drive/folders/1AbC_-xYz09",
                "folder_name": "CCTV-Utama",
                "local_path": "/mnt/gdrive1",
            },
        )
        assert r.status_code == 200
        assert r.json()["folder_name"] == "CCTV-Utama"

        # Hapus
        r = await c.delete(f"/api/admin/storage/google-drive/{f2['id']}")
        assert r.status_code == 200
        r = await c.get("/api/admin/storage/google-drive")
        assert len(r.json()["folders"]) == 1


@pytest.mark.asyncio
async def test_gdrive_folder_invalid_url(app_client):
    app, _, _ = app_client
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/storage/google-drive",
            json={"folder_url": "https://drive.google.com/drive/home"},
        )
        assert r.status_code == 400
        assert "tidak dikenali" in r.json()["detail"]


@pytest.mark.asyncio
async def test_disks_includes_google_drive_folders(app_client, monkeypatch, tmp_path):
    app, _, _ = app_client
    auth_as(app, make_user(role="super_admin"))
    s = get_settings()
    monkeypatch.setattr(s, "gdrive_record_path", str(tmp_path / "staging"))
    monkeypatch.setattr(s, "gdrive_quota_tb", 5.0)
    try:
        async with _client(app) as c:
            await c.post(
                "/api/admin/storage/google-drive",
                json={
                    "folder_url": "https://drive.google.com/drive/folders/1AbC_-xYz09",
                    "folder_name": "CCTV",
                    "local_path": str(tmp_path / "staging"),
                },
            )
            r = await c.get("/api/admin/disk-summary")
            assert r.status_code == 200
            body = r.json()
            assert "google_drive" in body
            assert "google_drive_folders" in body
            assert len(body["google_drive_folders"]) == 1
            gd = body["google_drive_folders"][0]
            assert gd["storage_type"] == "google_drive"
            assert gd["size_bytes"] == 5 * (1024**4)
    finally:
        get_settings.cache_clear()


def test_mirror_tick_multi_folder(monkeypatch, tmp_path):
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
    # B-S6: mirror menolak staging yang bukan mount hidup. Tes ini menguji
    # logika penyalinan multi-folder, bukan cek mount, jadi matikan syaratnya.
    monkeypatch.setattr(s, "drive_mirror_require_mount", False)
    folders = [
        (1, "CCTV-1", str(tmp_path / "staging1")),
        (2, "CCTV-2", str(tmp_path / "staging2")),
    ]
    try:
        # Kamera 7 -> folder 2 saja; kamera 8 -> default (folder 1)
        _mirror_tick([(7, "Gudang", 2), (8, "Parkir", None)], folders)
        assert (tmp_path / "staging2" / "stream_7" / "2026-11-02_10-00-00.mp4").exists()
        assert not (tmp_path / "staging1" / "stream_7").exists()
        assert not (tmp_path / "staging2" / "stream_7" / "2026-11-02_10-05-00.mp4").exists()
        # idempotent
        _mirror_tick([(7, "Gudang", 2)], folders)
        assert len(list((tmp_path / "staging2" / "stream_7").iterdir())) == 1
    finally:
        get_settings.cache_clear()
