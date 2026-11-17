"""Test perbaikan temuan Area 1 audit backend+database 2026-11-17.

Nomor tes mengikuti nomor temuan (1.1-1.27)."""

import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select

from app.core.config import get_settings
from app.models.access import StreamAdminGrant, UserStreamAccess
from app.models.drive import GoogleDriveFolder
from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream
from app.models.streams import Stream
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _seg(root, stream_id, name, size=2048):
    d = os.path.join(root, f"stream_{stream_id}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(b"v" * size)
    return p


# ---------- 1.1: super_admin terakhir tidak bisa dinonaktifkan ----------

async def _seed_super(db, n=1):
    users = []
    for i in range(n):
        u = make_user(
            id=10 + i, username=f"su{i}", role="super_admin", is_active=True
        )
        db.add(u)
        users.append(u)
    await db.commit()
    return users


async def test_1_1_nonaktifkan_super_admin_terakhir_ditolak(app_client):
    app, _, db = app_client
    (su,) = await _seed_super(db, 1)
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.put(f"/api/admin/users/{su.id}", json={"is_active": False})
        assert r.status_code == 400, r.text
        assert "terakhir" in r.json()["detail"]
        # Menurunkan peran + menghapus tetap ditolak juga.
        r = await c.put(f"/api/admin/users/{su.id}", json={"role": "admin"})
        assert r.status_code == 400, r.text
        r = await c.delete(f"/api/admin/users/{su.id}")
        assert r.status_code == 400, r.text


async def test_1_1_nonaktifkan_boleh_bila_ada_super_admin_lain(app_client):
    app, _, db = app_client
    su0, su1 = await _seed_super(db, 2)
    auth_as(app, su0)
    async with _client(app) as c:
        r = await c.put(f"/api/admin/users/{su1.id}", json={"is_active": False})
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        # Kini su0 satu-satunya yang aktif: menonaktifkan dirinya ditolak.
        r = await c.put(f"/api/admin/users/{su0.id}", json={"is_active": False})
        assert r.status_code == 400, r.text


async def test_1_1_hitung_hanya_yang_aktif(app_client):
    """Satu super_admin nonaktif + satu aktif dihitung 1, bukan 2:
    guard demote/hapus atas yang aktif tetap berlaku."""
    app, _, db = app_client
    su0, su1 = await _seed_super(db, 2)
    su1.is_active = False
    await db.commit()
    auth_as(app, su0)
    async with _client(app) as c:
        # Demote yang aktif (satu-satunya aktif) ditolak...
        r = await c.put(f"/api/admin/users/{su0.id}", json={"role": "admin"})
        assert r.status_code == 400, r.text
        # ...tapi demote yang sudah nonaktif dibolehkan.
        r = await c.put(f"/api/admin/users/{su1.id}", json={"role": "admin"})
        assert r.status_code == 200, r.text
        # Hapus super_admin nonaktif juga dibolehkan.
        r = await c.delete(f"/api/admin/users/{su1.id}")
        assert r.status_code == 200, r.text


# ---------- 1.2: Range end < start + suffix range ----------

def test_1_2_parse_range():
    from app.routers.recordings import _parse_range

    assert _parse_range("bytes=500-100", 5000) == (0, 4999, False)
    assert _parse_range("bytes=-500", 5000) == (4500, 4999, True)
    assert _parse_range("bytes=-99999", 5000) == (0, 4999, True)
    assert _parse_range("bytes=0-99", 5000) == (0, 99, True)
    assert _parse_range("bytes=100-", 5000) == (100, 4999, True)
    assert _parse_range("bytes=5000-6000", 5000) == (0, 4999, False)
    assert _parse_range("bytes=-0", 5000) == (0, 4999, False)


async def test_1_2_range_end_lt_start_dilayani_200_utuh(
    app_client, monkeypatch, tmp_path
):
    """Cabang rclone: bytes=500-100 tidak lagi menghasilkan
    Content-Range 500-100 + Content-Length negatif (206)."""
    from app.services import gdrive_rclone as gr
    from tests.test_recordings_api import _seed as _rec_seed

    app, _, db = app_client
    s = await _rec_seed(app, db, monkeypatch, tmp_path)
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
        return [{"name": "2026-11-02_10-00-00-000000.mp4", "size": 5000, "id": "f1"}]

    async def _fake_download(remote_name, path, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"v" * 5000)
        return 5000

    monkeypatch.setattr(gr, "list_rclone_files", _fake_list)
    monkeypatch.setattr(gr, "download_rclone_file_to", _fake_download)
    async with _client(app) as c:
        r = await c.get(f"/api/recordings/{s.id}/segments",
                        params={"date": "2026-11-02"})
        url = r.json()[0]["url"]
        r = await c.get(url, headers={"Range": "bytes=500-100"})
        assert r.status_code == 200, r.text
        assert "Content-Range" not in r.headers
        assert len(r.content) == 5000
        # Suffix range dilayani sebagai 206 yang benar.
        r = await c.get(url, headers={"Range": "bytes=-100"})
        assert r.status_code == 206, r.text
        assert r.headers["Content-Range"] == "bytes 4900-4999/5000"
        assert len(r.content) == 100


# ---------- 1.3: reconnect hanya super_admin/pemilik ----------

async def _seed_reconnect(db):
    admin = make_user(id=1, username="admin", role="admin")
    pemilik = make_user(id=2, username="pemilik", role="admin")
    op = make_user(id=3, username="op", role="user")
    s = Stream(
        id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
        main_url="rtsp://cam/1", is_active=True, created_by=2,
    )
    db.add_all([
        admin, pemilik, op, s,
        UserStreamAccess(user_id=3, stream_id=1, can_view=True),
        StreamAdminGrant(stream_id=1, admin_id=1, can_view=True, can_playback=True),
    ])
    await db.commit()
    return admin, pemilik, op


async def test_1_3_reconnect_ditolak_penonton_dan_admin_bukan_pemilik(app_client):
    app, _, db = app_client
    admin, pemilik, op = await _seed_reconnect(db)
    async with _client(app) as c:
        # User hanya bisa menonton (can_view): sebelumnya bisa reconnect.
        auth_as(app, op)
        r = await c.post("/api/streams/1/reconnect")
        assert r.status_code == 403, r.text
        # Admin biasa dengan grant can_view tapi bukan pemilik: 403.
        auth_as(app, admin)
        r = await c.post("/api/streams/1/reconnect")
        assert r.status_code == 403, r.text
        # Pemilik kamera boleh.
        auth_as(app, pemilik)
        r = await c.post("/api/streams/1/reconnect")
        assert r.status_code == 200, r.text
        # Super_admin boleh.
        auth_as(app, make_user(id=9, username="su", role="super_admin"))
        r = await c.post("/api/streams/1/reconnect")
        assert r.status_code == 200, r.text


# ---------- 1.6: password API key > 72 byte ----------

def test_1_6_hash_password_lebih_dari_72_byte():
    from app.core.security import hash_password

    with pytest.raises(ValueError, match="72"):
        hash_password("x" * 73)
    assert hash_password("x" * 72)


async def test_1_6_api_key_password_panjang_422(app_client):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    db.add(Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
                  main_url="rtsp://cam/1", is_active=True))
    await db.commit()
    async with _client(app) as c:
        r = await c.post("/api/admin/api-keys", json={
            "name": "k", "stream_ids": [1], "password": "x" * 73,
        })
        assert r.status_code == 422, r.text


# ---------- 1.7: datetime aware dikonversi ke waktu lokal server ----------

def test_1_7_to_server_naive():
    from app.routers.recordings import _to_server_naive

    aware = datetime(2026, 11, 17, 10, 5, tzinfo=timezone(timedelta(hours=7)))
    naive = _to_server_naive(aware)
    assert naive.tzinfo is None
    # Sama dengan konversi astimezone() (zona lokal proses), bukan
    # sekadar buang tzinfo (yang akan menghasilkan 10:05).
    assert naive == aware.astimezone().replace(tzinfo=None)
    assert naive != aware.replace(tzinfo=None)
    assert _to_server_naive(datetime(2026, 11, 17, 10, 5)) == datetime(
        2026, 11, 17, 10, 5
    )
    assert _to_server_naive(None) is None


async def test_1_7_playback_url_waktu_wib(app_client, monkeypatch, tmp_path):
    """?time=10:05 WIB menemukan segmen 03:05 waktu server (UTC)."""
    from tests.test_recordings_api import _seed as _rec_seed

    app, _, db = app_client
    s = await _rec_seed(app, db, monkeypatch, tmp_path)
    at = datetime(2026, 11, 17, 10, 5, tzinfo=timezone(timedelta(hours=7)))
    base = at.astimezone().replace(tzinfo=None)  # waktu lokal server
    # Segmen 03:00-03:10 dan 03:10-03:20 waktu server.
    for delta in (0, 10):
        t = base - timedelta(minutes=5) + timedelta(minutes=delta)
        _seg(str(tmp_path), s.id, t.strftime("%Y-%m-%d_%H-%M-%S-000000.mp4"))
    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/playback-url",
            params={"time": "2026-11-17T10:05:00+07:00"},
        )
        assert r.status_code == 200, r.text
        start = (base - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
        assert f"start={start}" in r.json()["url"]


# ---------- 1.8: trim gagal -> 500, bukan segmen utuh ----------

async def test_1_8_trim_gagal_500_bukan_segmen_utuh(
    app_client, monkeypatch, tmp_path
):
    from tests.test_recordings_api import _seed as _rec_seed

    app, _, db = app_client
    s = await _rec_seed(app, db, monkeypatch, tmp_path)
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")
    _seg(str(tmp_path), s.id, "2026-11-02_10-10-00-000000.mp4")
    async with _client(app) as c:
        # Rentang parsial (butuh potong; file palsu -> ffmpeg gagal).
        r = await c.get(
            f"/api/recordings/{s.id}/file",
            params={"start": "2026-11-02T10:02:00", "end": "2026-11-02T10:05:00"},
        )
        assert r.status_code == 500, r.text
        assert "gagal memotong" in r.json()["detail"]
        # Rentang utuh segmen (tidak perlu potong) tetap 200.
        r = await c.get(
            f"/api/recordings/{s.id}/file",
            params={"start": "2026-11-02T10:00:00", "end": "2026-11-02T10:10:00"},
        )
        assert r.status_code == 200, r.text
        assert len(r.content) == 2048


def _seg_mp4_asli(root, stream_id, name, durasi_detik=1800):
    """Buat segmen MP4 asli (testsrc 1fps) supaya ffmpeg bisa memotong."""
    import shutil
    import subprocess

    assert shutil.which("ffmpeg"), "ffmpeg dibutuhkan tes ini"
    d = os.path.join(root, f"stream_{stream_id}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={durasi_detik}:size=160x120:rate=1",
         "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-y", p],
        check=True,
    )
    return p


async def test_1_8_trim_mp4_asli_berhasil_200(
    app_client, monkeypatch, tmp_path
):
    """Happy path 1.8: segmen MP4 asli yang rentangnya dipotong
    berhasil disajikan (200), bukan 500."""
    from tests.test_recordings_api import _seed as _rec_seed

    app, _, db = app_client
    s = await _rec_seed(app, db, monkeypatch, tmp_path)
    _seg_mp4_asli(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")
    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/stream",
            params={"start": "2026-11-02T10:15:00"},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "video/mp4"
        assert len(r.content) > 0
        r = await c.get(
            f"/api/recordings/{s.id}/file",
            params={"start": "2026-11-02T10:15:00", "end": "2026-11-02T10:20:00"},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/octet-stream"
        assert len(r.content) > 0


# ---------- 1.9: _log embed gagal tidak mengubah respons ----------

async def test_1_9_log_gagal_tidak_melempar():
    """_log dengan sesi DB rusak: tidak raise, respons pemanggil utuh."""
    from starlette.requests import Request

    from app.routers.external import _log

    class _BrokenSession:
        def add(self, obj):
            pass

        async def commit(self):
            raise RuntimeError("db down")

        async def rollback(self):
            pass

    scope = {
        "type": "http", "method": "GET", "headers": [],
        "client": ("127.0.0.1", 1234),
    }
    req = Request(scope)
    await _log(_BrokenSession(), req, "external.cameras.ok", key_id=1)


# ---------- 1.10: disk-summary cache + thread + rate limit ----------

async def test_1_10_disk_summary_cache_dan_rate_limit(
    app_client, monkeypatch, tmp_path
):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "a.mp4").write_bytes(b"x" * 1_000_000)
    db.add(GoogleDriveFolder(
        folder_url="https://drive.google.com/drive/folders/abc",
        folder_id="abc", folder_name="CCTV", local_path=str(staging),
    ))
    await db.commit()
    s = get_settings()
    monkeypatch.setattr(s, "gdrive_quota_tb", 5.0)
    try:
        async with _client(app) as c:
            r = await c.get("/api/admin/disk-summary")
            assert r.status_code == 200, r.text
            avail1 = r.json()["google_drive_folders"][0]["avail_bytes"]
            # Tambah file: hasil kedua masih cache (avail sama).
            (staging / "b.mp4").write_bytes(b"x" * 1_000_000)
            r = await c.get("/api/admin/disk-summary")
            assert r.status_code == 200, r.text
            assert r.json()["google_drive_folders"][0]["avail_bytes"] == avail1
            # Setelah reset cache, hasil baru terlihat.
            from app.routers import admin_streams as _as

            _as.reset_disk_cache()
            r = await c.get("/api/admin/disk-summary")
            assert r.status_code == 200, r.text
            assert (
                r.json()["google_drive_folders"][0]["avail_bytes"]
                == avail1 - 1_000_000
            )
            # Rate limit 20/menit: 21 panggilan berurutan -> 429.
            for _ in range(17):
                await c.get("/api/admin/disk-summary")
            r = await c.get("/api/admin/disk-summary")
            assert r.status_code == 429, r.text
    finally:
        get_settings.cache_clear()


# ---------- 1.11: job scan running tidak pernah dihapus ----------

async def test_1_11_prune_tidak_hapus_job_running(app_client):
    from app.routers import admin_scan as scan_mod

    try:
        for i in range(11):
            job = scan_mod._ScanJob(job_id=f"j{i}", total=1)
            scan_mod._jobs[job.job_id] = job
        async with scan_mod._jobs_lock:
            scan_mod._prune_jobs_locked()
        assert len(scan_mod._jobs) == 11
    finally:
        scan_mod._jobs.clear()


async def test_1_11_scan_baru_429_bila_penuh(app_client):
    from app.routers import admin_scan as scan_mod

    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    try:
        for i in range(10):
            scan_mod._jobs[f"j{i}"] = scan_mod._ScanJob(
                job_id=f"j{i}", total=1
            )
        async with _client(app) as c:
            r = await c.post(
                "/api/admin/scan-subnet",
                json={"ip_range": "10.0.0.0/30"},
            )
            assert r.status_code == 429, r.text
    finally:
        scan_mod._jobs.clear()


# ---------- 1.12: N+1 di tiga daftar admin ----------

def _attach_counter(engine):
    """Hitung SELECT selama request (dilepas pemanggil via event.remove).

    AsyncEngine tidak menerima listener sinkron; pasang di sync_engine.
    """
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counts["n"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _before)
    return counts, _before


async def test_1_12_list_users_tanpa_n_plus_1(app_client):
    app, _, db = app_client
    admin = make_user(id=1, username="admin", role="admin",
                      admin_group="grup-jakarta")
    db.add(admin)
    for i in range(2, 7):
        db.add(make_user(id=i, username=f"u{i}", role="user",
                         admin_group="grup-jakarta", parent_admin_id=1))
    await db.commit()
    auth_as(app, admin)
    counts, fn = _attach_counter(db.bind)
    try:
        async with _client(app) as c:
            r = await c.get("/api/admin/users")
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", fn)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 6
    # 1 query daftar + 1 query parent = 2 (sebelumnya 1 + 5).
    assert counts["n"] <= 3, counts


async def test_1_12_list_keys_tanpa_n_plus_1(app_client):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    for i in range(1, 4):
        key = ApiKey(name=f"k{i}", key_hash=_sha(f"K{i}"), is_active=True)
        db.add(key)
        await db.flush()
        db.add(ApiKeyStream(api_key_id=key.id, stream_id=1))
    db.add(Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
                  main_url="rtsp://cam/1", is_active=True))
    await db.commit()
    counts, fn = _attach_counter(db.bind)
    try:
        async with _client(app) as c:
            r = await c.get("/api/admin/api-keys")
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", fn)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3
    # 1 query keys + 1 query stream_ids = 2 (sebelumnya 1 + 3).
    assert counts["n"] <= 3, counts


async def test_1_12_list_streams_tanpa_n_plus_1(app_client):
    app, _, db = app_client
    admin = make_user(id=1, username="admin", role="admin")
    db.add(admin)
    for i in range(1, 4):
        db.add(Stream(
            id=i, name=f"Cam {i}", rtsp_url=f"rtsp://cam/{i}",
            main_url=f"rtsp://cam/{i}", is_active=True, created_by=1,
        ))
    await db.commit()
    auth_as(app, admin)
    counts, fn = _attach_counter(db.bind)
    try:
        async with _client(app) as c:
            r = await c.get("/api/admin/streams")
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", fn)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3
    # visible(2 query) + batch mask(1) = 3 (sebelumnya 2 + 3).
    assert counts["n"] <= 4, counts


# ---------- 1.13: recording_cameras batch + fallback konkuren ----------

async def test_1_13_cameras_hanya_playback_diizinkan(
    app_client, monkeypatch, tmp_path
):
    """User can_view tanpa can_playback tidak tampil di Putar Ulang."""
    from tests.test_recordings_api import _seed as _rec_seed

    app, _, db = app_client
    s = await _rec_seed(app, db, monkeypatch, tmp_path)
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")
    op = make_user(id=2, username="op", role="user")
    db.add(op)
    db.add(UserStreamAccess(user_id=2, stream_id=s.id,
                            can_view=True, can_playback=False))
    await db.commit()
    auth_as(app, op)
    async with _client(app) as c:
        r = await c.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
        assert r.json() == []
        # Dengan can_playback, kamera tampil.
        row = (await db.execute(
            select(UserStreamAccess).where(
                UserStreamAccess.user_id == 2,
                UserStreamAccess.stream_id == s.id,
            )
        )).scalars().first()
        row.can_playback = True
        await db.commit()
        r = await c.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
        assert [k["id"] for k in r.json()] == [s.id]


async def test_1_13_fallback_drive_dua_kamera_bersamaan(
    app_client, monkeypatch, tmp_path
):
    """Dua kamera Drive tanpa jejak upload tapi punya segmen folder-link
    sama-sama tampil (fallback jalan bersamaan, sesi per tugas)."""
    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    staging = tmp_path / "staging"
    for sid in (1, 2):
        s = Stream(
            id=sid, name=f"Cam {sid}", rtsp_url=f"rtsp://x/{sid}",
            main_url=f"rtsp://x/{sid}", is_active=True,
            recording_enabled=True, storage_mode="drive",
        )
        db.add(s)
        d = staging / f"stream_{sid}"
        d.mkdir(parents=True)
        (d / "2026-11-02_10-00-00-000000.mp4").write_bytes(b"v" * 100)
    db.add(GoogleDriveFolder(
        folder_url="https://drive.google.com/drive/folders/abc",
        folder_id="abc", folder_name="CCTV", local_path=str(staging),
    ))
    await db.commit()
    auth_as(app, admin)
    monkeypatch.setattr(get_settings(), "recordings_dir", str(tmp_path))
    async with _client(app) as c:
        r = await c.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
        assert {k["id"] for k in r.json()} == {1, 2}


# ---------- 1.14-1.18: external ----------

async def _seed_key(db, raw_key="KUNCI-RAHASIA-123", stream_ids=(1, 2), **kw):
    kwargs = dict(
        name="mitra-a", key_hash=_sha(raw_key), is_active=True,
        session_ttl_mnt=60,
    )
    kwargs.update(kw)
    key = ApiKey(**kwargs)
    db.add(key)
    await db.flush()
    for pos, sid in enumerate(stream_ids):
        db.add(ApiKeyStream(api_key_id=key.id, stream_id=sid, position=pos))
    await db.commit()
    return key


async def _seed_streams(db, with_sub=True):
    s1 = Stream(
        id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
        main_url="rtsp://cam/1",
        sub_url="rtsp://cam/1_sub" if with_sub else None,
        is_active=True, is_online=True,
    )
    s2 = Stream(
        id=2, name="Cam 2", rtsp_url="rtsp://cam/2",
        main_url="rtsp://cam/2", is_active=True, is_online=False,
    )
    db.add_all([s1, s2])
    await db.commit()
    return s1, s2


async def test_1_14_playback_cameras_urut_kunci(app_client):
    """Urutan `cameras` mengikuti urutan kamera di kunci (3, 1),
    selaras dengan penomoran ?camera=N."""
    from app.models.drive import DriveUpload  # noqa: F401 (registrasi)

    app, _, db = app_client
    s1 = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
                main_url="rtsp://cam/1", is_active=True)
    s3 = Stream(id=3, name="Cam 3", rtsp_url="rtsp://cam/3",
                main_url="rtsp://cam/3", is_active=True)
    db.add_all([s1, s3])
    await _seed_key(db, stream_ids=(3, 1))
    async with _client(app) as c:
        r = await c.get("/api/external/playback",
                        params={"key": "KUNCI-RAHASIA-123"})
        assert r.status_code == 200, r.text
        assert [cam["id"] for cam in r.json()["cameras"]] == [3, 1]
        # ?camera=1 berarti kamera pertama di daftar (id 3).
        r = await c.get("/api/external/playback",
                        params={"key": "KUNCI-RAHASIA-123", "camera": 1})
        assert r.json()["camera"] == 1
        assert r.json()["camera_name"] == "Cam 3"


async def test_1_15_webrtc_sub_none_tanpa_sub_url(app_client):
    app, _, db = app_client
    await _seed_streams(db, with_sub=False)
    await _seed_key(db)
    async with _client(app) as c:
        r = await c.get("/api/external/stream",
                        params={"key": "KUNCI-RAHASIA-123", "camera": 1})
        assert r.status_code == 200, r.text
        assert r.json()["stream"]["webrtc_url_sub"] is None


async def test_1_15_webrtc_sub_ada_bila_punya_sub(app_client):
    app, _, db = app_client
    await _seed_streams(db, with_sub=True)
    await _seed_key(db)
    async with _client(app) as c:
        r = await c.get("/api/external/stream",
                        params={"key": "KUNCI-RAHASIA-123", "camera": 1})
        assert r.status_code == 200, r.text
        assert r.json()["stream"]["webrtc_url_sub"] is not None
        assert "stream_1_sub" in r.json()["stream"]["webrtc_url_sub"]


async def test_1_16_playback_file_start_sama_dengan_end_ditolak(app_client):
    app, _, db = app_client
    await _seed_streams(db)
    await _seed_key(db)
    async with _client(app) as c:
        r = await c.get(
            "/api/external/playback/file",
            params={
                "key": "KUNCI-RAHASIA-123", "camera": 1,
                "start": "2026-11-02T10:00:00", "end": "2026-11-02T10:00:00",
            },
        )
        assert r.status_code == 403, r.text
        assert "end harus setelah start" in r.json()["detail"]


async def test_1_17_playback_date_dan_time_bersamaan_ditolak(app_client):
    app, _, db = app_client
    await _seed_streams(db)
    await _seed_key(db)
    async with _client(app) as c:
        r = await c.get(
            "/api/external/playback",
            params={
                "key": "KUNCI-RAHASIA-123", "camera": 1,
                "date": "2026-11-02", "time": "2026-11-02T10:00:00",
            },
        )
        assert r.status_code == 403, r.text


async def test_1_18_ad_config_embed_memuat_field_v3(app_client):
    """Config iklan embed memuat field v3.0 (position, display_mode,
    audience, click_url, ...), bukan hanya 16 field v2.0."""
    from app.routers.external import invalidate_ad_config_cache

    app, _, db = app_client
    await _seed_streams(db)
    await _seed_key(db)
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.post("/api/admin/ad-config", json={
            "position": "top", "display_mode": "periodic",
            "periodic_trigger": "hover", "audience": "roles",
            "audience_roles": ["guest"], "click_url": "https://contoh.id",
            "banner_height": 120, "marquee_text": "promo",
        })
        assert r.status_code == 200, r.text
        invalidate_ad_config_cache()
        r = await c.get("/api/external/stream",
                        params={"key": "KUNCI-RAHASIA-123", "camera": 1})
        assert r.status_code == 200, r.text
        ad = r.json()["ad"]
        assert ad["position"] == "top"
        assert ad["display_mode"] == "periodic"
        assert ad["periodic_trigger"] == "hover"
        assert ad["audience"] == "roles"
        assert ad["audience_roles"] == ["guest"]
        assert ad["click_url"] == "https://contoh.id"
        assert ad["banner_height"] == 120
        assert ad["marquee_text"] == "promo"


# ---------- 1.19: satu akun Drive default ----------

async def _mk_account(db, name, **kw):
    from app.models.drive import DriveAccount

    acc = DriveAccount(name=name, **kw)
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    return acc


async def test_1_19_matikan_default_terakhir_ditolak(app_client):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    a = await _mk_account(db, "A", is_default=True)
    async with _client(app) as c:
        r = await c.put(f"/api/admin/drive-accounts/{a.id}",
                        json={"is_default": False})
        assert r.status_code == 400, r.text


async def test_1_19_hapus_default_promosi_akun_lain(app_client):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    a = await _mk_account(db, "A", is_default=True)
    b = await _mk_account(db, "B", is_default=False)
    async with _client(app) as c:
        r = await c.delete(f"/api/admin/drive-accounts/{a.id}")
        assert r.status_code == 200, r.text
        r = await c.get("/api/admin/drive-accounts")
        rows = {x["name"]: x for x in r.json()}
        assert rows["B"]["is_default"] is True


async def test_1_19_indeks_unik_tolak_default_kedua(db_session):
    """Indeks unik parsial: dua baris is_default=True tidak bisa
    tersimpan bersamaan (jaring pengaman race dua POST)."""
    from sqlalchemy.exc import IntegrityError

    from app.models.drive import DriveAccount

    await _mk_account(db_session, "A", is_default=True)
    db_session.add(DriveAccount(name="B", is_default=True))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    # Dua akun bukan default tetap boleh.
    db_session.add(DriveAccount(name="B", is_default=False))
    db_session.add(DriveAccount(name="C", is_default=False))
    await db_session.commit()


# ---------- 1.20: null eksplisit menghapus koordinat ----------

async def test_1_20_null_hapus_koordinat_put_tidak_mengubah(app_client):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
               main_url="rtsp://cam/1", is_active=True,
               latitude=-7.5, longitude=111.0)
    db.add(s)
    await db.commit()
    async with _client(app) as c:
        # PUT tanpa field latitude/longitude: tidak berubah.
        r = await c.put("/api/admin/streams/1", json={"name": "Cam 1 baru"})
        assert r.status_code == 200, r.text
        assert r.json()["latitude"] == -7.5
        assert r.json()["longitude"] == 111.0
        # PUT latitude/longitude null eksplisit: koordinat terhapus.
        r = await c.put("/api/admin/streams/1",
                        json={"latitude": None, "longitude": None})
        assert r.status_code == 200, r.text
        assert r.json()["latitude"] is None
        assert r.json()["longitude"] is None


# ---------- 1.21: remote Drive tanpa token tersimpan ----------

async def test_1_21_remote_tanpa_kunci_token_ditolak(
    app_client, monkeypatch
):
    """Bila DRIVE_TOKEN_KEY tidak ada, POST /admin/drive-remotes
    menolak 400 (bukan 201 dengan baris tanpa token_encrypted)."""
    from app.services import gdrive_rclone as gr

    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    monkeypatch.setenv("DRIVE_TOKEN_KEY", "")
    get_settings.cache_clear()

    async def _fake_save(*args, **kwargs):
        return "ok"

    monkeypatch.setattr(gr, "save_token", _fake_save)
    try:
        async with _client(app) as c:
            r = await c.post("/api/admin/drive-remotes", json={
                "name": "gdrive", "remote_name": "gdrive",
                "token": '{"access_token": "x", "token_type": "Bearer", '
                         '"refresh_token": "r", "expiry": "2099-01-01T00:00:00Z"}',
            })
            assert r.status_code == 400, r.text
            assert "tidak bisa disimpan" in r.json()["detail"]
    finally:
        monkeypatch.delenv("DRIVE_TOKEN_KEY", raising=False)
        get_settings.cache_clear()


# ---------- 1.22: batas panjang + path lokal ----------

async def test_1_22_ad_config_terlalu_panjang_422(app_client):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.post("/api/admin/ad-config",
                         json={"marquee_text": "x" * 2001})
        assert r.status_code == 422, r.text
        r = await c.post("/api/admin/ad-config",
                         json={"audience_roles": [f"r{i}" for i in range(51)]})
        assert r.status_code == 422, r.text


async def test_1_22_folder_path_lokal_sistem_ditolak(app_client):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    payload = {
        "folder_url": "https://drive.google.com/drive/folders/abc",
        "folder_name": "CCTV",
    }
    async with _client(app) as c:
        for bad in ("/etc", "/etc/passwd", "data/x", "/root/x"):
            r = await c.post("/api/admin/storage/google-drive",
                             json={**payload, "local_path": bad})
            assert r.status_code == 400, (bad, r.text)


# ---------- 1.23: websocket banjir + pesan raksasa ----------

async def test_1_23_ws_pesan_20kib_ditutup_1009(app_client):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.core.security import create_access_token

    app, _, db = app_client
    # Token WS divalidasi ke DB: user super_admin id=1 harus ada.
    db.add(make_user(role="super_admin"))
    await db.commit()
    token = create_access_token(1, "admin", "super_admin", get_settings())
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={token}") as ws:
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            ws.send_text("x" * (20 * 1024))
            import pytest as _pt

            with _pt.raises(Exception):
                ws.receive_text()


async def test_1_23_ws_ping_dibatasi_jendela(app_client):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.core.security import create_access_token

    app, _, db = app_client
    db.add(make_user(role="super_admin"))
    await db.commit()
    token = create_access_token(1, "admin", "super_admin", get_settings())
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={token}") as ws:
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            for _ in range(25):
                ws.send_text("ping")
            pongs = [ws.receive_json() for _ in range(20)]
            assert all(p["type"] == "pong" for p in pongs)


# ---------- 1.24: download-range dibatasi segmen + byte ----------

async def test_1_24_download_range_terlalu_banyak_segmen(
    app_client, monkeypatch, tmp_path
):
    from tests.test_recordings_api import _seed as _rec_seed

    app, _, db = app_client
    s = await _rec_seed(app, db, monkeypatch, tmp_path)
    base = datetime(2026, 11, 2, 10, 0)
    for i in range(65):
        t = base + timedelta(minutes=i)
        _seg(str(tmp_path), s.id, t.strftime("%Y-%m-%d_%H-%M-%S-000000.mp4"),
             size=100)
    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T10:00:00",
                    "end": "2026-11-02T12:00:00"},
        )
        assert r.status_code == 400, r.text
        assert "65 segmen" in r.json()["detail"]


async def test_1_24_download_range_terlalu_besar(
    app_client, monkeypatch, tmp_path
):
    from tests.test_recordings_api import _seed as _rec_seed

    app, _, db = app_client
    s = await _rec_seed(app, db, monkeypatch, tmp_path)
    # Segmen sparse 3 GiB (tanpa isi disk) + penutup rentang.
    p = _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4", size=0)
    with open(p, "wb") as f:
        f.truncate(3 * 1024**3)
    _seg(str(tmp_path), s.id, "2026-11-02_10-10-00-000000.mp4", size=100)
    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T10:00:00",
                    "end": "2026-11-02T10:05:00"},
        )
        assert r.status_code == 400, r.text
        assert "2 GiB" in r.json()["detail"]


# ---------- 1.25: hapus log wajib konfirmasi ----------

async def test_1_25_clear_logs_wajib_konfirmasi(app_client):
    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))
    db.add_all([
        ApiAccessLog(api_key_id=None, action="a", ip="127.0.0.1"),
        ApiAccessLog(api_key_id=None, action="b", ip="127.0.0.1"),
    ])
    await db.commit()
    async with _client(app) as c:
        r = await c.delete("/api/admin/api-access-logs")
        assert r.status_code == 400, r.text
        # days=365 tidak menghapus log baru.
        r = await c.delete("/api/admin/api-access-logs",
                           params={"days": 365})
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] == 0
        r = await c.delete("/api/admin/api-access-logs",
                           params={"confirm": "true"})
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] == 2
        r = await c.delete("/api/admin/api-access-logs",
                           params={"confirm": "true"})
        assert r.json()["deleted"] == 0


# ---------- 1.26: pesan error Drive generik ----------

async def test_1_26_error_drive_tidak_bocor_detail(
    app_client, monkeypatch, tmp_path
):
    from app.services import gdrive_rclone as gr
    from tests.test_recordings_api import _seed as _rec_seed

    app, _, db = app_client
    s = await _rec_seed(app, db, monkeypatch, tmp_path)
    s.storage_mode = "drive"
    folder = GoogleDriveFolder(
        folder_url="https://drive.google.com/drive/folders/folder-abc",
        folder_id="folder-abc", folder_name="netravision",
        remote_name="gdrive",
    )
    db.add(folder)
    await db.commit()
    s.drive_folder_id = folder.id
    await db.commit()

    async def _fake_list(remote_name, path):
        return [{"name": "2026-11-02_10-00-00-000000.mp4", "size": 1000,
                 "id": "f1"}]

    async def _fake_download(remote_name, path, dest_path):
        raise Exception("rclone: remote gdrive-2:/rahasia gagal: token bocor")

    monkeypatch.setattr(gr, "list_rclone_files", _fake_list)
    monkeypatch.setattr(gr, "download_rclone_file_to", _fake_download)
    async with _client(app) as c:
        r = await c.get(f"/api/recordings/{s.id}/segments",
                        params={"date": "2026-11-02"})
        url = r.json()[0]["url"]
        r = await c.get(url)
        assert r.status_code == 502, r.text
        assert r.json()["detail"] == "Google Drive tidak terjangkau"
        assert "rahasia" not in r.text and "bocor" not in r.text


# ---------- 1.27: verifikasi substream + brand auto ----------

async def test_1_27_tambah_sub_tidak_video_ditolak(
    app_client, monkeypatch
):
    from types import SimpleNamespace

    from app.services import rtsp_discovery

    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))

    async def _fake_verify(url, timeout=10):
        if "sub" in url:
            return SimpleNamespace(status="no_video")
        return SimpleNamespace(status="video")

    monkeypatch.setattr(rtsp_discovery, "verify_url", _fake_verify)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={
            "name": "Cam", "brand": "generic",
            "rtsp_url": "rtsp://cam/1",
            "main_url": "rtsp://cam/1", "sub_url": "rtsp://cam/1_sub",
            "owner": "admin",
        })
        assert r.status_code == 400, r.text
        assert "Substream" in r.json()["detail"]
        # force=true melewati verifikasi.
        r = await c.post("/api/admin/streams", json={
            "name": "Cam", "brand": "generic",
            "rtsp_url": "rtsp://cam/1",
            "main_url": "rtsp://cam/1", "sub_url": "rtsp://cam/1_sub",
            "owner": "admin", "force": True,
        })
        assert r.status_code == 201, r.text


async def test_1_27_resolve_brand_auto_jadi_generic():
    from app.services.stream_resolver import resolve_stream

    out = await resolve_stream(brand="auto", rtsp_url=None, host="10.0.0.1")
    assert out.brand == "generic"
    assert out.main_url.endswith("/onvif1")
    assert out.sub_url.endswith("/onvif2")
    out = await resolve_stream(brand=None, rtsp_url=None, host="10.0.0.1")
    assert out.brand == "generic"
    assert out.main_url.endswith("/onvif1")


async def test_1_27_tambah_host_brand_auto_201(app_client, monkeypatch):
    from app.services import stream_resolver as _sr

    app, _, db = app_client
    auth_as(app, make_user(role="super_admin"))

    async def _no_onvif(*args, **kwargs):
        return None

    monkeypatch.setattr(_sr, "_try_onvif", _no_onvif)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={
            "name": "Cam ONVIF", "host": "10.0.0.9", "brand": "auto",
            "user": "admin", "password": "x", "owner": "admin",
            "force": True,
        })
        assert r.status_code == 201, r.text
        # main_url di respons create selalu None (stream_to_out tidak
        # mengisinya); verifikasi yang tersimpan di DB.
        row = await db.get(Stream, r.json()["id"])
        assert row.brand == "generic"
        assert row.main_url.endswith("/onvif1")
        assert row.sub_url.endswith("/onvif2")
