"""Test multi-remote rclone (mock, tanpa biner rclone dan tanpa network).

rclone TIDAK terinstal di VM ini, jadi semua verifikasi live tidak
mungkin; _run_rclone / subprocess dimock.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.models.drive import GoogleDriveFolder
from app.services import disks as disks_mod
from app.services import gdrive_rclone as gr
from tests.conftest import auth_as, make_user

TOKEN = json.dumps(
    {"refresh_token": "refresh-1", "access_token": "acc-1",
     "token_type": "Bearer", "expiry": "2030-01-01T00:00:00Z"}
)
TOKEN2 = json.dumps(
    {"refresh_token": "refresh-2", "access_token": "acc-2",
     "token_type": "Bearer", "expiry": "2030-01-01T00:00:00Z"}
)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _write_conf(tmp_path, text):
    p = tmp_path / ".rclone.conf"
    p.write_text(text)
    return p


async def _fake_run_ok(*args, timeout=60):
    if args and args[0] == "about":
        return 0, json.dumps({"total": 1000, "used": 100, "free": 900}), ""
    return 0, "", ""


async def test_save_token_preserves_other_remotes(tmp_path, monkeypatch):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    _write_conf(tmp_path, f"[gdrive]\ntype = drive\nscope = drive\ntoken = {TOKEN}\n")
    monkeypatch.setattr(gr, "_run_rclone", _fake_run_ok)
    info = await gr.save_token(TOKEN2, "gdrive-2")
    assert info["email"] == "terhubung"
    text = (tmp_path / ".rclone.conf").read_text()
    assert "[gdrive]" in text
    assert "refresh-1" in text
    assert "[gdrive-2]" in text
    assert "refresh-2" in text
    assert gr.list_remote_names() == ["gdrive", "gdrive-2"]


async def test_save_token_failure_restores_old_conf(tmp_path, monkeypatch):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    old = f"[gdrive]\ntype = drive\nscope = drive\ntoken = {TOKEN}\n"
    _write_conf(tmp_path, old)

    async def _fail(*args, timeout=60):
        return 1, "", "token ditolak"

    monkeypatch.setattr(gr, "_run_rclone", _fail)
    with pytest.raises(RuntimeError, match="Token ditolak"):
        await gr.save_token(TOKEN2, "gdrive-2")
    assert (tmp_path / ".rclone.conf").read_text() == old
    assert gr.list_remote_names() == ["gdrive"]


async def test_save_token_default_remote_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gr, "_run_rclone", _fake_run_ok)
    info = await gr.save_token(TOKEN)
    assert info["email"] == "terhubung"
    assert gr.list_remote_names() == ["gdrive"]


async def test_list_and_delete_remote(tmp_path, monkeypatch):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    _write_conf(
        tmp_path,
        "[gdrive]\ntype = drive\ntoken = {}\n\n[gdrive-2]\ntype = drive\ntoken = {}\n",
    )
    assert gr.list_remote_names() == ["gdrive", "gdrive-2"]
    assert gr.delete_remote("gdrive-2") is True
    assert gr.list_remote_names() == ["gdrive"]
    assert gr.delete_remote("gdrive-2") is False
    assert gr.delete_remote("nama jelek!") is False


async def test_upload_segment_uses_given_remote(tmp_path, monkeypatch):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    seen = []

    async def _cap(*args, timeout=60):
        seen.append(args)
        return 0, "", ""

    monkeypatch.setattr(gr, "_run_rclone", _cap)
    p = tmp_path / "2026-11-12_10-00-00-000000.mp4"
    p.write_bytes(b"v")
    await gr.upload_segment(str(p), "folder1", "gdrive-2")
    assert seen[0][2] == "gdrive-2:folder1/2026-11-12_10-00-00-000000.mp4"
    # Kompatibilitas lama: argumen ketiga "Kamera/segmen.mp4" = jalur tujuan
    await gr.upload_segment(str(p), "folder1", "CamA/2026-11-12_10-00-00-000000.mp4")
    assert seen[1][2] == "gdrive:folder1/CamA/2026-11-12_10-00-00-000000.mp4"


async def test_remote_status_no_rclone(tmp_path, monkeypatch):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    _write_conf(tmp_path, "[gdrive]\ntype = drive\ntoken = {}\n")
    monkeypatch.setattr(gr, "find_rclone", lambda: None)
    st = await gr.remote_status("gdrive")
    assert st["connected"] is False
    assert "rclone tidak ditemukan" in st["error"]
    st2 = await gr.connection_status()
    assert st2["connected"] is False


async def test_remote_status_connected(tmp_path, monkeypatch):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    _write_conf(tmp_path, "[gdrive-2]\ntype = drive\ntoken = {}\n")
    monkeypatch.setattr(gr, "_run_rclone", _fake_run_ok)
    st = await gr.remote_status("gdrive-2")
    assert st["connected"] is True
    assert st["total_bytes"] == 1000
    assert st["used_bytes"] == 100
    assert st["free_bytes"] == 900


def test_list_disks_includes_rclone(tmp_path, monkeypatch):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    _write_conf(tmp_path, "[gdrive-2]\ntype = drive\ntoken = {}\n")
    monkeypatch.setattr(gr, "find_rclone", lambda: "/usr/bin/rclone")

    def _fake_run(cmd, **kw):
        class R:
            returncode = 0

            def __init__(self, stdout):
                self.stdout = stdout

        if cmd[0] == "df":
            return R(
                "target size avail fstype\n"
                "/ 100000000000 50000000000 ext4\n"
            )
        assert cmd[0] == "/usr/bin/rclone"
        assert "gdrive-2:" in cmd
        return R(json.dumps({"total": 107374182400, "used": 53687091200,
                             "free": 53687091200}))

    monkeypatch.setattr(disks_mod.subprocess, "run", _fake_run)
    out = disks_mod.list_disks()
    rclone_entries = [d for d in out if d["fstype"] == "rclone"]
    assert len(rclone_entries) == 1
    e = rclone_entries[0]
    assert e["mount"] == "rclone:gdrive-2"
    assert e["size_bytes"] == 107374182400
    assert e["avail_bytes"] == 53687091200
    assert e["usage_pct"] == 50.0


async def test_cleanup_rclone_remote_deletes_oldest_mp4_only(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    db_session.add(GoogleDriveFolder(
        folder_url="https://drive.google.com/drive/folders/folder1",
        folder_id="folder1", folder_name="CCTV",
    ))
    await db_session.commit()
    deleted: list[str] = []

    def _fake(cmd_args, timeout=60):
        if cmd_args[0] == "about":
            used = max(5, 95 - 30 * len(deleted))
            return 0, json.dumps({"total": 100, "used": used, "free": 100 - used}), ""
        if cmd_args[0] == "lsjson":
            return 0, json.dumps([
                {"Path": "CamA/2026-11-10_10-00-00-000000.mp4",
                 "Name": "2026-11-10_10-00-00-000000.mp4",
                 "ModTime": "2026-11-10T10:00:00Z"},
                {"Path": "CamA/2026-11-11_10-00-00-000000.mp4",
                 "Name": "2026-11-11_10-00-00-000000.mp4",
                 "ModTime": "2026-11-11T10:00:00Z"},
                {"Path": "CamA/2026-11-12_10-00-00-000000.mp4",
                 "Name": "2026-11-12_10-00-00-000000.mp4",
                 "ModTime": "2026-11-12T10:00:00Z"},
                {"Path": "CamA/catatan.txt", "Name": "catatan.txt",
                 "ModTime": "2026-11-09T10:00:00Z"},
            ]), ""
        if cmd_args[0] == "delete":
            deleted.append(cmd_args[1])
            return 0, "", ""
        raise AssertionError(f"perintah tak terduga: {cmd_args}")

    monkeypatch.setattr(disks_mod, "_rclone_run_sync", _fake)
    n = await disks_mod.cleanup_rclone_remote(db_session, "gdrive-2", 90.0, 80.0)
    assert n == 3
    assert deleted == [
        "gdrive-2:folder1/CamA/2026-11-10_10-00-00-000000.mp4",
        "gdrive-2:folder1/CamA/2026-11-11_10-00-00-000000.mp4",
        "gdrive-2:folder1/CamA/2026-11-12_10-00-00-000000.mp4",
    ]
    assert all("catatan.txt" not in d for d in deleted)


async def test_cleanup_rclone_remote_below_threshold(db_session, monkeypatch):
    def _fake(cmd_args, timeout=60):
        return 0, json.dumps({"total": 100, "used": 10, "free": 90}), ""

    monkeypatch.setattr(disks_mod, "_rclone_run_sync", _fake)
    n = await disks_mod.cleanup_rclone_remote(db_session, "gdrive-2", 90.0, 80.0)
    assert n == 0


async def test_drive_remotes_endpoints(app_client, monkeypatch):
    app, _, _ = app_client
    auth_as(app, make_user(role="super_admin"))

    async def _fake_save(token_json, remote_name="gdrive"):
        return {"email": "terhubung"}

    async def _fake_status(remote_name):
        return {"connected": True, "email": "terhubung",
                "remote_name": remote_name, "total_bytes": 1000,
                "used_bytes": 100, "free_bytes": 900}

    monkeypatch.setattr(gr, "save_token", _fake_save)
    monkeypatch.setattr(gr, "remote_status", _fake_status)
    monkeypatch.setattr(gr, "find_rclone", lambda: "/usr/bin/rclone")
    async with _client(app) as c:
        r = await c.get("/api/admin/drive-remotes")
        assert r.status_code == 200
        assert r.json() == []

        r = await c.post("/api/admin/drive-remotes", json={
            "token": TOKEN, "remote_name": "nama jelek!", "label": "x",
        })
        assert r.status_code == 400

        r = await c.post("/api/admin/drive-remotes", json={
            "token": TOKEN, "remote_name": "gdrive-2", "label": "akun2@mail.test",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["remote_name"] == "gdrive-2"
        assert body["label"] == "akun2@mail.test"
        assert body["connected"] is True

        r = await c.get("/api/admin/drive-remotes")
        assert r.status_code == 200
        assert [x["remote_name"] for x in r.json()] == ["gdrive-2"]

        r = await c.get("/api/admin/drive-remotes/gdrive-2/status")
        assert r.status_code == 200
        assert r.json()["connected"] is True
        assert r.json()["total_bytes"] == 1000

        r = await c.get("/api/admin/drive-remotes/tidak-ada/status")
        assert r.status_code == 404

        r = await c.delete("/api/admin/drive-remotes/tidak-ada")
        assert r.status_code == 404

        r = await c.delete("/api/admin/drive-remotes/gdrive-2")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        r = await c.get("/api/admin/drive-remotes")
        assert r.json() == []


async def test_drive_remote_create_token_invalid(app_client, monkeypatch):
    app, _, _ = app_client
    auth_as(app, make_user(role="super_admin"))

    async def _fake_save(token_json, remote_name="gdrive"):
        raise ValueError("Token bukan JSON valid.")

    monkeypatch.setattr(gr, "save_token", _fake_save)
    async with _client(app) as c:
        r = await c.post("/api/admin/drive-remotes", json={
            "token": "bukan-json", "remote_name": "gdrive-2",
        })
        assert r.status_code == 400


async def test_drive_authorize_endpoints(app_client, monkeypatch):
    app, _, _ = app_client
    auth_as(app, make_user(role="super_admin"))

    async def _fake_start(remote_name):
        job = {
            "job_id": "abc123",
            "remote_name": remote_name,
            "status": "waiting",
            "auth_url": "http://127.0.0.1:53682/auth?state=x",
            "token": None,
            "error": None,
        }
        gr._AUTHORIZE_JOBS["abc123"] = job
        return {"job_id": "abc123"}

    monkeypatch.setattr(gr, "start_authorize", _fake_start)
    monkeypatch.setattr(gr, "find_rclone", lambda: "/usr/bin/rclone")
    async with _client(app) as c:
        # Tanpa label -> 400.
        r = await c.post("/api/admin/drive-remotes/authorize", json={"label": ""})
        assert r.status_code == 400

        # Mulai authorize -> 200, nama remote pertama gdrive.
        r = await c.post("/api/admin/drive-remotes/authorize", json={"label": "Akun Tes"})
        assert r.status_code == 200
        assert r.json()["job_id"] == "abc123"
        assert r.json()["remote_name"] == "gdrive"
        assert r.json()["label"] == "Akun Tes"

        # Poll job -> waiting + auth_url.
        r = await c.get("/api/admin/drive-remotes/authorize/abc123")
        assert r.status_code == 200
        assert r.json()["status"] == "waiting"
        assert r.json()["auth_url"].startswith("http://127.0.0.1:53682/auth?state=")

        # Job tidak dikenal -> 404.
        r = await c.get("/api/admin/drive-remotes/authorize/tidak-ada")
        assert r.status_code == 404
