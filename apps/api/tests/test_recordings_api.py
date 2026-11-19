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


async def test_timeline_segmen_terakhir_mtime_lama_tidak_nol(app_client, monkeypatch, tmp_path):
    """Timeline: segmen terakhir dengan mtime lebih lama dari start
    tetap punya durasi, bukan end=start.

    Segmen 356 2026-11-18 14:39 punya mtime file 07:48 (salinan/mount
    rclone), sehingga end=max(start, mtime)=start dan unduhan
    /file?start=X&end=X ditolak 400 ("end harus setelah start").
    """
    from datetime import datetime

    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    p = _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")
    # mtime 07:00, jauh sebelum start segmen 10:00.
    old = datetime(2026, 11, 2, 7, 0, 0).timestamp()
    os.utime(p, (old, old))

    async with _client(app) as c:
        r = await c.get(f"/api/recordings/{s.id}/timeline", params={"date": "2026-11-02"})
        assert r.status_code == 200, r.text
        entries = r.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["start"] == "2026-11-02T10:00:00"
        assert entries[0]["end"] > entries[0]["start"]


async def test_cameras_drive_tanpa_lsjson(app_client, monkeypatch, tmp_path):
    """GET /recordings/cameras: kamera Drive dikenali lewat drive_uploads.

    Perintah user 2026-11-17 (Putar Ulang sangat lambat): kamera mode
    Drive yang tidak punya segmen lokal harus tampil bila ada jejak
    upload di drive_uploads, TANPA memanggil _all_segments (rclone
    lsjson ~2 detik + list_files Drive API). Tes ini memastikan kamera
    Drive muncul walau _all_segments dibuat gagal total.
    """
    from app.models.drive import DriveUpload

    app, _, db = app_client
    admin = make_user()
    db.add(admin)
    s = Stream(
        name="Cam Drive",
        rtsp_url="rtsp://x/9",
        main_url="rtsp://x/9",
        is_active=True,
        recording_enabled=True,
        storage_mode="drive",
        created_by=admin.id,
    )
    db.add(s)
    await db.flush()
    db.add(
        DriveUpload(
            stream_id=s.id,
            segment_name="2026-11-02_10-00-00-000000.mp4",
            folder_name="f1",
        )
    )
    await db.commit()
    auth_as(app, admin)
    monkeypatch.setattr(get_settings(), "recordings_dir", str(tmp_path))

    import app.routers.recordings as rec

    async def _boom(*args, **kwargs):
        raise AssertionError("_all_segments tidak boleh dipanggil")

    monkeypatch.setattr(rec, "_all_segments", _boom)

    async with _client(app) as cl:
        r = await cl.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
        ids = {k["id"] for k in r.json()}
        assert s.id in ids


async def test_cameras_drive_tanpa_folder_tidak_panggil_all_segments(app_client, monkeypatch, tmp_path):
    """GET /recordings/cameras: kamera Drive tanpa folder tidak memicu fallback.

    Kamera mode Drive tanpa drive_folder_id, tanpa segmen lokal, dan
    tanpa jejak upload tidak punya rekaman yang bisa diputar. Fallback
    _all_segments untuk kamera seperti ini menebak folder default +
    nama kamera yang tidak ada, dan rclone lsjson menggantung sampai
    timeout 60 detik per kamera (9 kamera baru MIM Gudang: endpoint
    120 detik, pemilih kamera Putar Ulang macet di "Memuat kamera...").
    """
    app, _, db = app_client
    admin = make_user()
    db.add(admin)
    s = Stream(
        name="Cam Drive Tanpa Folder",
        rtsp_url="rtsp://x/9",
        main_url="rtsp://x/9",
        is_active=True,
        recording_enabled=False,
        storage_mode="drive",
        drive_folder_id=None,
        created_by=admin.id,
    )
    db.add(s)
    await db.commit()
    auth_as(app, admin)
    monkeypatch.setattr(get_settings(), "recordings_dir", str(tmp_path))

    import app.routers.recordings as rec

    async def _boom(*args, **kwargs):
        raise AssertionError("_all_segments tidak boleh dipanggil")

    monkeypatch.setattr(rec, "_all_segments", _boom)

    async with _client(app) as cl:
        r = await cl.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
        ids = {k["id"] for k in r.json()}
        assert s.id not in ids


async def test_cameras_hanya_yang_punya_segmen(app_client, monkeypatch, tmp_path):
    """GET /recordings/cameras hanya kembalikan kamera yang punya segmen.

    - recording aktif + ada segmen -> tampil.
    - recording aktif tapi tanpa segmen -> tidak tampil (belum ada playback).
    - recording mati tapi punya segmen lama -> tampil (masih bisa diputar).
    """
    app, _, db = app_client
    a = await _seed(app, db, monkeypatch, tmp_path)
    _seg(str(tmp_path), a.id, "2026-11-02_10-00-00-000000.mp4")
    b = Stream(
        name="Cam tanpa segmen",
        rtsp_url="rtsp://x/2",
        main_url="rtsp://x/2",
        is_active=True,
        recording_enabled=True,
        created_by=1,
    )
    db.add(b)
    c = Stream(
        name="Cam rekaman lama",
        rtsp_url="rtsp://x/3",
        main_url="rtsp://x/3",
        is_active=True,
        recording_enabled=False,
        created_by=1,
    )
    db.add(c)
    await db.commit()
    _seg(str(tmp_path), c.id, "2026-11-01_09-00-00-000000.mp4")

    async with _client(app) as cl:
        r = await cl.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
        ids = {k["id"] for k in r.json()}
        assert a.id in ids
        assert b.id not in ids
        assert c.id in ids


async def test_stream_file_playbackurl_nextplayable(app_client, monkeypatch, tmp_path):
    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")

    async with _client(app) as c:
        # A-1.8: segmen palsu (bukan mp4 asli) tidak bisa dipotong
        # ffmpeg; rentang parsial kini 500 "gagal memotong", bukan lagi
        # segmen utuh yang disajikan diam-diam.
        r = await c.get(
            f"/api/recordings/{s.id}/stream",
            params={"start": "2026-11-02T10:15:00"},
        )
        assert r.status_code == 500, r.text
        assert "gagal memotong" in r.json()["detail"]

        r = await c.get(
            f"/api/recordings/{s.id}/file",
            params={"start": "2026-11-02T10:15:00", "end": "2026-11-02T10:20:00"},
        )
        assert r.status_code == 500, r.text
        assert "gagal memotong" in r.json()["detail"]

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

    async def _fake_list(remote_name, path, timeout=60):
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

    async def _fake_download(remote_name, path, dest_path):
        assert remote_name == "gdrive"
        assert path == "netravision/Cam 1/2026-11-02_10-00-00-000000.mp4"
        # Unduh utuh sekali (perintah user 2026-11-17: percepat Putar
        # Ulang); Range dilayani dari disk, bukan satu `rclone cat`
        # per potongan 1 MB, dan bukan dari RAM (temuan 3.5).
        with open(dest_path, "wb") as f:
            f.write(b"v" * 5000)
        return 5000

    monkeypatch.setattr(gr, "list_rclone_files", _fake_list)
    monkeypatch.setattr(gr, "download_rclone_file_to", _fake_download)

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


async def test_playback_rclone_satu_unduhan_untuk_file_besar(
    app_client, monkeypatch, tmp_path
):
    """Segmen Drive >1 MB hanya memicu SATU `rclone cat`.

    Perintah user 2026-11-17 (Putar Ulang "Memuat video..." sangat
    lambat): sebelumnya tiap potongan 1 MB memicu satu proses `rclone
    cat` baru, jadi segmen 3 MB berarti 3 proses berurutan. Kini
    `download_rclone_file_to` dipanggil sekali, Range dilayani dari
    disk (temuan 3.5: bukan dari RAM).
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

    calls = {"n": 0}

    async def _fake_list(remote_name, path, timeout=60):
        return [
            {"name": "2026-11-02_10-00-00-000000.mp4", "size": 3 * 1024 * 1024, "id": "f1"},
        ]

    async def _fake_download(remote_name, path, dest_path):
        calls["n"] += 1
        with open(dest_path, "wb") as f:
            f.write(b"v" * (3 * 1024 * 1024))
        return 3 * 1024 * 1024

    monkeypatch.setattr(gr, "list_rclone_files", _fake_list)
    monkeypatch.setattr(gr, "download_rclone_file_to", _fake_download)

    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/segments", params={"date": "2026-11-02"}
        )
        assert r.status_code == 200, r.text
        url = r.json()[0]["url"]
        r = await c.get(url)
        assert r.status_code == 200, r.text
        assert len(r.content) == 3 * 1024 * 1024
        assert calls["n"] == 1


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

    async def _fake_list(remote_name, path, timeout=60):
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


def _mp4_seg(root, stream_id, name, seconds=10, mtime=None):
    """Segmen MP4 asli (testsrc) supaya ffmpeg concat/trim bisa jalan."""
    import subprocess

    d = os.path.join(root, f"stream_{stream_id}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i",
         f"testsrc=duration={seconds}:size=128x72:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "10",
         "-movflags", "+faststart", p],
        check=True,
    )
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def _mp4_duration(path):
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


async def test_download_range_gabung_dan_potong(app_client, monkeypatch, tmp_path):
    """Unduh rentang: 3 segmen lokal digabung, ujung dipotong ke rentang."""
    import shutil
    from datetime import datetime as dt

    import pytest

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg tidak tersedia")
    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)

    def ts(h, mi, sec):
        return dt(2026, 11, 2, h, mi, sec).timestamp()

    _mp4_seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4",
             mtime=ts(10, 0, 10))
    _mp4_seg(str(tmp_path), s.id, "2026-11-02_10-00-10-000000.mp4",
             mtime=ts(10, 0, 20))
    _mp4_seg(str(tmp_path), s.id, "2026-11-02_10-00-20-000000.mp4",
             mtime=ts(10, 0, 30))

    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T10:00:05", "end": "2026-11-02T10:00:25"},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("video/mp4")
        assert "rekaman-" in r.headers.get("content-disposition", "")
        out = tmp_path / "range.mp4"
        out.write_bytes(r.content)
        dur = _mp4_duration(str(out))
        # 5 + 10 + 5 detik, toleransi seek keyframe.
        assert 18 <= dur <= 22, dur


async def test_download_range_validasi_dan_kosong(app_client, monkeypatch, tmp_path):
    """Rentang invalid (400) dan tanpa rekaman (404)."""
    from datetime import datetime as dt

    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    p = _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")
    # Segmen tunggal: end diambil dari mtime, jadi set ke 10:10 supaya
    # tidak dianggap menjangkau 12:00.
    t = dt(2026, 11, 2, 10, 10, 0).timestamp()
    os.utime(p, (t, t))

    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T10:00:00", "end": "2026-11-02T10:00:00"},
        )
        assert r.status_code == 400, r.text
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T10:00:00", "end": "2026-11-02T12:00:01"},
        )
        assert r.status_code == 400, r.text
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T12:00:00", "end": "2026-11-02T12:10:00"},
        )
        assert r.status_code == 404, r.text


async def test_dates_drive_tanpa_lsjson(app_client, monkeypatch, tmp_path):
    """6.5: GET /dates kamera Drive dijawab dari drive_uploads
    (listdir lokal + jejak upload), TANPA _all_segments penuh."""
    from app.models.drive import DriveUpload

    app, _, db = app_client
    admin = make_user()
    db.add(admin)
    s = Stream(
        name="Cam Drive",
        rtsp_url="rtsp://x/9",
        main_url="rtsp://x/9",
        is_active=True,
        recording_enabled=True,
        storage_mode="drive",
        created_by=admin.id,
    )
    db.add(s)
    await db.flush()
    db.add(
        DriveUpload(
            stream_id=s.id,
            segment_name="2026-11-02_10-00-00-000000.mp4",
            folder_name="f1",
        )
    )
    await db.commit()
    auth_as(app, admin)
    monkeypatch.setattr(get_settings(), "recordings_dir", str(tmp_path))

    import app.routers.recordings as rec

    async def _boom(*args, **kwargs):
        raise AssertionError("_all_segments tidak boleh dipanggil")

    monkeypatch.setattr(rec, "_all_segments", _boom)

    async with _client(app) as cl:
        r = await cl.get(f"/api/recordings/{s.id}/dates")
        assert r.status_code == 200, r.text
        assert r.json() == {"dates": ["2026-11-02"]}


async def test_playback_url_tanpa_pindai_penuh(app_client, monkeypatch, tmp_path):
    """6.3: playback-url hanya memindai jendela hari-1..hari+1,
    bukan seluruh riwayat (_all_segments tanpa hari)."""
    import app.routers.recordings as rec

    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")

    seen_days = []
    orig = rec._all_segments

    async def _spy(stream, day, db):
        seen_days.append(day)
        return await orig(stream, day, db)

    monkeypatch.setattr(rec, "_all_segments", _spy)

    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/playback-url",
            params={"time": "2026-11-02T09:00:00"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["url"].startswith(f"/api/recordings/{s.id}/file?")
    assert seen_days, "playback-url harus memindai jendela hari"
    assert all(d is not None for d in seen_days), seen_days
    assert set(seen_days) <= {
        date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3),
    }, seen_days


async def test_playback_oauth_satu_unduhan(app_client, monkeypatch, tmp_path):
    """6.1: segmen Drive-OAuth 3 MB disajikan dengan SATU get_media
    (download_drive_file), bukan satu panggilan per potongan 1 MB."""
    from tests.test_drive import FakeDrive, _settings as _drive_settings

    from app.services.drive import DriveUploader

    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    s.storage_mode = "drive"
    await db.commit()

    svc = FakeDrive()
    up = DriveUploader(settings=_drive_settings(), service=svc)
    folder_id = await up.ensure_folder(s.name, s.id)
    name = "2026-11-02_10-00-00-000000.mp4"
    svc._files[(folder_id, name)] = {
        "id": "f-oauth-1",
        "name": name,
        "size": 3 * 1024 * 1024,
        "createdTime": "",
        "content": b"v" * (3 * 1024 * 1024),
    }

    async def _fake_uploader(db, stream):
        return up

    import app.services.drive_accounts as da

    monkeypatch.setattr(da, "uploader_for_stream", _fake_uploader)
    monkeypatch.setattr(get_settings(), "drive_enabled", True)

    async with _client(app) as c:
        # Segmen utuh (10:00-10:10) supaya tidak perlu potong ffmpeg.
        r = await c.get(
            f"/api/recordings/{s.id}/file",
            params={"start": "2026-11-02T10:00:00", "end": "2026-11-02T10:10:00"},
        )
        assert r.status_code == 200, r.text
        assert len(r.content) == 3 * 1024 * 1024
    assert svc.media_calls == 1, svc.media_calls


async def test_download_range_recordings_dir_relatif(app_client, monkeypatch, tmp_path):
    """Regresi: recordings_dir relatif (produksi) harus tetap bisa digabung.

    Concat demuxer membaca jalur relatif terhadap lokasi file list (/tmp),
    bukan cwd API, jadi jalur segmen harus dijadikan absolut dulu.
    """
    import shutil
    from datetime import datetime as dt

    import pytest

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg tidak tersedia")
    # Simulasi produksi: cwd = tmp_path, recordings_dir relatif "rec".
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(get_settings(), "recordings_dir", "rec")
    app, _, db = app_client
    s = await _seed(app, db, monkeypatch, tmp_path)
    # _seed menimpa recordings_dir ke tmp_path absolut, kembalikan ke "rec".
    monkeypatch.setattr(get_settings(), "recordings_dir", "rec")

    def ts(h, mi, sec):
        return dt(2026, 11, 2, h, mi, sec).timestamp()

    _mp4_seg(str(tmp_path / "rec"), s.id, "2026-11-02_10-00-00-000000.mp4",
             mtime=ts(10, 0, 10))
    _mp4_seg(str(tmp_path / "rec"), s.id, "2026-11-02_10-00-10-000000.mp4",
             mtime=ts(10, 0, 20))
    _mp4_seg(str(tmp_path / "rec"), s.id, "2026-11-02_10-00-20-000000.mp4",
             mtime=ts(10, 0, 30))

    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T10:00:05", "end": "2026-11-02T10:00:25"},
        )
        assert r.status_code == 200, r.text
        out = tmp_path / "range-rel.mp4"
        out.write_bytes(r.content)
        dur = _mp4_duration(str(out))
        assert 18 <= dur <= 22, dur


async def test_timeline_drive_uploads_saat_lsjson_gagal(app_client, monkeypatch, tmp_path):
    """Linimasa tetap menampilkan segmen Drive dari drive_uploads bila
    rclone lsjson gagal (Google lambat/rate-limit).

    Regresi 2026-11-20: MIM MRI 1 punya 26 segmen Drive hari itu tapi
    linimasa hanya menampilkan 40 menit (segmen lokal), karena
    _rclone_segments timeout 8 detik saat Google lambat dan tidak ada
    sumber Drive lain. Jejak drive_uploads (DB lokal) kini menjadi
    penopang: segmen yang terkonfirmasi terunggah tetap tampil tanpa
    memanggil Google."""
    from app.models.drive import DriveUpload, GoogleDriveFolder
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
    db.add_all(
        [
            DriveUpload(
                stream_id=s.id,
                segment_name="2026-11-02_10-00-00-000000.mp4",
                folder_name="netravision",
            ),
            DriveUpload(
                stream_id=s.id,
                segment_name="2026-11-02_10-10-00-000000.mp4",
                folder_name="netravision",
            ),
        ]
    )
    await db.commit()

    async def _fake_list_gagal(remote_name, path, timeout=60):
        raise RuntimeError("rclone lsjson gagal: timeout")

    monkeypatch.setattr(gr, "list_rclone_files", _fake_list_gagal)

    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/timeline", params={"date": "2026-11-02"}
        )
        assert r.status_code == 200, r.text
        entries = r.json()["entries"]
        assert len(entries) == 2, entries
        assert entries[0]["start"].startswith("2026-11-02T10:00:00")
        assert entries[1]["start"].startswith("2026-11-02T10:10:00")
