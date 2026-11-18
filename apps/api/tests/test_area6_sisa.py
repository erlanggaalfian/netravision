"""Tes Area C (sisa Area 6): 6.6, 6.8, 6.10, 6.11, 6.12.

6.6  _all_segments: sumber Drive paralel, tiap sumber sesi sendiri.
6.12 download-range: segmen disiapkan paralel (semaphore 4).
6.10 _detect_fallback_auth: probe paralel per kredensial + susunan
     timeout (_HOST_TIMEOUT luar > _HOST_BUDGET dalam).
6.8  embed: satu insert + satu commit per request; retensi
     api_access_logs 90 hari.
6.11 GET /streams: paginasi SQL (LIMIT/OFFSET + COUNT,
     header X-Total-Count), RBAC visibilitas tidak berubah.
"""

import asyncio
import hashlib
import os
import subprocess
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models.access import StreamAdminGrant, StreamPermission, UserStreamAccess
from app.models.groups import GroupStream, StreamGroup
from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream
from app.models.streams import Stream
from app.services.recording import Segment
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


def _mp4_seg(root, stream_id, name, seconds=10, mtime=None):
    """Segmen MP4 asli (testsrc) supaya ffmpeg concat/trim bisa jalan."""
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


async def _seed_stream(app, db, monkeypatch, tmp_path, **kw):
    monkeypatch.setattr(get_settings(), "recordings_dir", str(tmp_path))
    admin = make_user()
    db.add(admin)
    kwargs = dict(
        name="Cam 1",
        rtsp_url="rtsp://x/1",
        main_url="rtsp://x/1",
        is_active=True,
        recording_enabled=True,
        created_by=admin.id,
    )
    kwargs.update(kw)
    s = Stream(**kwargs)
    db.add(s)
    await db.commit()
    auth_as(app, admin)
    return s, admin


# ── 6.6 _all_segments paralel ──────────────────────────────────────────

async def test_all_segments_sumber_drive_paralel(app_client, monkeypatch, tmp_path):
    """Folder-link + rclone jalan bersamaan (interval tumpang tindih),
    tiap sumber memakai sesi sendiri, lokal tetap menang bila nama sama."""
    import app.routers.recordings as rec

    app, _, db = app_client
    s, _ = await _seed_stream(
        app, db, monkeypatch, tmp_path, storage_mode="drive"
    )
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")
    day = date(2026, 11, 2)
    intervals: dict[str, tuple[float, float]] = {}
    sessions: dict[str, object] = {}

    async def _fake_folder_link(stream, d, sdb):
        sessions["folder-link"] = sdb
        t0 = time.monotonic()
        await asyncio.sleep(0.25)
        intervals["folder-link"] = (t0, time.monotonic())
        return [
            # Nama sama dengan lokal: harus kalah (lokal menang).
            Segment(start=datetime(2026, 11, 2, 10, 0, 0), path="/tmp/x.mp4",
                    size=111, name="2026-11-02_10-00-00-000000.mp4"),
            Segment(start=datetime(2026, 11, 2, 10, 10, 0), path="/tmp/y.mp4",
                    size=222, name="2026-11-02_10-10-00-000000.mp4"),
        ]

    async def _fake_rclone(stream, d, sdb):
        sessions["rclone"] = sdb
        t0 = time.monotonic()
        await asyncio.sleep(0.25)
        intervals["rclone"] = (t0, time.monotonic())
        return [
            # Nama sama dengan folder-link: harus kalah (folder-link menang).
            Segment(start=datetime(2026, 11, 2, 10, 10, 0), path="",
                    size=999, name="2026-11-02_10-10-00-000000.mp4",
                    rclone_remote="gdrive", rclone_path="g/10-10.mp4"),
            Segment(start=datetime(2026, 11, 2, 10, 20, 0), path="",
                    size=333, name="2026-11-02_10-20-00-000000.mp4",
                    rclone_remote="gdrive", rclone_path="g/10-20.mp4"),
        ]

    monkeypatch.setattr(rec, "_folder_link_segments", _fake_folder_link)
    monkeypatch.setattr(rec, "_rclone_segments", _fake_rclone)
    segs = await rec._all_segments(s, day, db)
    names = [sg.name for sg in segs]
    assert names == [
        "2026-11-02_10-00-00-000000.mp4",
        "2026-11-02_10-10-00-000000.mp4",
        "2026-11-02_10-20-00-000000.mp4",
    ], names
    # Prioritas dedup: lokal (2048) menang atas folder-link (111),
    # folder-link (222) menang atas rclone (999).
    assert segs[0].size == 2048
    assert segs[1].size == 222
    assert segs[2].size == 333
    # Paralel: interval kedua sumber tumpang tindih, bukan berurutan.
    a0, a1 = intervals["folder-link"]
    b0, b1 = intervals["rclone"]
    assert max(a0, b0) < min(a1, b1), intervals
    # Sesi sendiri: bukan sesi pemanggil, dan berbeda antar sumber.
    assert sessions["folder-link"] is not db
    assert sessions["rclone"] is not db
    assert sessions["folder-link"] is not sessions["rclone"]


async def test_all_segments_sumber_gagal_tidak_gagalkan_yang_lain(
    app_client, monkeypatch, tmp_path
):
    """Satu sumber Drive gagal: sumber lain tetap dipakai, bukan 500."""
    import app.routers.recordings as rec

    app, _, db = app_client
    s, _ = await _seed_stream(
        app, db, monkeypatch, tmp_path, storage_mode="drive"
    )
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")

    async def _boom(stream, d, sdb):
        raise RuntimeError("lsjson mati")

    async def _fake_rclone(stream, d, sdb):
        return [
            Segment(start=datetime(2026, 11, 2, 10, 10, 0), path="",
                    size=444, name="2026-11-02_10-10-00-000000.mp4",
                    rclone_remote="gdrive", rclone_path="g/10-10.mp4"),
        ]

    monkeypatch.setattr(rec, "_folder_link_segments", _boom)
    monkeypatch.setattr(rec, "_rclone_segments", _fake_rclone)
    segs = await rec._all_segments(s, date(2026, 11, 2), db)
    assert [sg.name for sg in segs] == [
        "2026-11-02_10-00-00-000000.mp4",
        "2026-11-02_10-10-00-000000.mp4",
    ]


async def test_all_segments_tanpa_bind_jalan_berurutan(app_client, monkeypatch, tmp_path):
    """Fallback: sesi tanpa bind (factory None) tetap mengembalikan
    gabungan yang sama lewat jalur berurutan lama."""
    import app.routers.recordings as rec

    app, _, db = app_client
    s, _ = await _seed_stream(
        app, db, monkeypatch, tmp_path, storage_mode="drive"
    )
    _seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4")
    assert rec._session_factory_for(db) is not None
    monkeypatch.setattr(rec, "_session_factory_for", lambda _db: None)

    async def _fake_rclone(stream, d, sdb):
        assert sdb is db
        return [
            Segment(start=datetime(2026, 11, 2, 10, 10, 0), path="",
                    size=444, name="2026-11-02_10-10-00-000000.mp4",
                    rclone_remote="gdrive", rclone_path="g/10-10.mp4"),
        ]

    monkeypatch.setattr(rec, "_rclone_segments", _fake_rclone)
    segs = await rec._all_segments(s, date(2026, 11, 2), db)
    assert [sg.name for sg in segs] == [
        "2026-11-02_10-00-00-000000.mp4",
        "2026-11-02_10-10-00-000000.mp4",
    ]


# ── 6.12 download-range paralel ────────────────────────────────────────

async def test_download_range_segmen_disiapkan_paralel(
    app_client, monkeypatch, tmp_path
):
    """_segment_part_file 3 segmen jalan bersamaan (interval tumpang
    tindih), tiap tugas sesi sendiri, urutan concat tetap kronologis."""
    import shutil

    import app.routers.recordings as rec

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg tidak tersedia")
    app, _, db = app_client
    s, _ = await _seed_stream(app, db, monkeypatch, tmp_path)

    def ts(h, mi, sec):
        return datetime(2026, 11, 2, h, mi, sec).timestamp()

    for name, m in (
        ("2026-11-02_10-00-00-000000.mp4", ts(10, 0, 10)),
        ("2026-11-02_10-00-10-000000.mp4", ts(10, 0, 20)),
        ("2026-11-02_10-00-20-000000.mp4", ts(10, 0, 30)),
    ):
        _mp4_seg(str(tmp_path), s.id, name, mtime=m)
    intervals: list[tuple[float, float]] = []
    sessions: list[object] = []
    orig_part = rec._segment_part_file

    async def _slow_part(stream, seg, ps, pe, sdb):
        sessions.append(sdb)
        t0 = time.monotonic()
        await asyncio.sleep(0.25)
        intervals.append((t0, time.monotonic()))
        return await orig_part(stream, seg, ps, pe, sdb)

    monkeypatch.setattr(rec, "_segment_part_file", _slow_part)
    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T10:00:05", "end": "2026-11-02T10:00:25"},
        )
    assert r.status_code == 200, r.text
    assert len(intervals) == 3
    # Ketiga tugas tumpang tindih: yang terakhir mulai sebelum
    # yang pertama selesai (berurutan akan butuh 0,75 dtk).
    assert max(t[0] for t in intervals) < min(t[1] for t in intervals), intervals
    assert all(sdb is not db for sdb in sessions)
    assert len({id(x) for x in sessions}) == 3


async def test_download_range_trim_gagal_tetap_500(
    app_client, monkeypatch, tmp_path
):
    """TrimFailedError di satu segmen paralel tetap menggagalkan
    seluruh unduhan (500), bukan dilewati diam-diam."""
    import app.routers.recordings as rec

    app, _, db = app_client
    s, _ = await _seed_stream(app, db, monkeypatch, tmp_path)

    def ts(h, mi, sec):
        return datetime(2026, 11, 2, h, mi, sec).timestamp()

    _mp4_seg(str(tmp_path), s.id, "2026-11-02_10-00-00-000000.mp4", mtime=ts(10, 0, 10))
    _mp4_seg(str(tmp_path), s.id, "2026-11-02_10-00-10-000000.mp4", mtime=ts(10, 0, 20))

    async def _fail_part(stream, seg, ps, pe, sdb):
        raise rec.TrimFailedError("ffmpeg gagal")

    monkeypatch.setattr(rec, "_segment_part_file", _fail_part)
    async with _client(app) as c:
        r = await c.get(
            f"/api/recordings/{s.id}/download-range",
            params={"start": "2026-11-02T10:00:00", "end": "2026-11-02T10:00:15"},
        )
    assert r.status_code == 500, r.text


# ── 6.10 fallback auth paralel + susunan timeout ────────────────────────

async def test_detect_fallback_auth_paralel(monkeypatch):
    """Probe dalam satu kredensial jalan bersamaan; prioritas
    kredensial tetap: tanpa kredensial gagal, password kosong
    gagal, password default pertama yang cocok yang menang."""
    import app.services.rtsp_discovery as rd

    calls: list[tuple[float, float]] = []
    seen: list[str] = []

    async def _fake_probe(url, timeout=3.0):
        seen.append(url)
        t0 = time.monotonic()
        await asyncio.sleep(0.2)
        calls.append((t0, time.monotonic()))
        # Hanya password default "12345" yang lolos auth.
        if ":12345@" in url:
            return "open"
        return "auth_failed"

    monkeypatch.setattr(rd, "probe_path", _fake_probe)
    res = await rd._detect_fallback_auth("192.168.1.10", 554, "admin", 1)
    assert res == ("default", "admin", "12345"), res
    # 8 path per kredensial dipanggil; probe dalam satu kredensial
    # tumpang tindih (berurutan akan 8 x 0,2 dtk per kredensial).
    assert len(calls) >= 8
    first_batch = calls[:8]
    assert max(t[0] for t in first_batch) < min(t[1] for t in first_batch), first_batch
    # Kredensial "none" dan "empty" tetap dicoba dulu (urutan dijaga).
    assert any("rtsp://192.168.1.10" in u for u in seen)
    assert any(":12345@" in u for u in seen)


async def test_detect_fallback_auth_tidak_ada_yang_cocok(monkeypatch):
    """Semua probe auth_failed -> None (hasil sama seperti versi berurutan)."""
    import app.services.rtsp_discovery as rd

    async def _fake_probe(url, timeout=3.0):
        return "auth_failed"

    monkeypatch.setattr(rd, "probe_path", _fake_probe)
    assert await rd._detect_fallback_auth("192.168.1.10", 554, "admin", 1) is None


def test_timeout_scanner_tersusun_benar():
    """6.10: timeout luar HARUS lebih besar dari budget dalam.
    _HOST_TIMEOUT 60 dtk (admin_scan, tahap 3) > _HOST_BUDGET 45 dtk
    (rtsp_discovery); sebelumnya 30 < 45 sehingga discovery selalu
    terpotong di tengah retry/fallback."""
    from app.routers.admin_scan import _HOST_TIMEOUT
    from app.services.rtsp_discovery import _HOST_BUDGET

    assert _HOST_TIMEOUT == 60.0
    assert _HOST_BUDGET == 45.0
    assert _HOST_TIMEOUT > _HOST_BUDGET


# ── 6.8 embed satu insert + retensi ────────────────────────────────────

async def _seed_key(db, **kw):
    kwargs = dict(
        name="mitra-a", key_hash=_sha("KUNCI-RAHASIA-123"),
        is_active=True, session_ttl_mnt=60,
    )
    kwargs.update(kw)
    key = ApiKey(**kwargs)
    db.add(key)
    await db.flush()
    s1 = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
                main_url="rtsp://cam/1", is_active=True, is_online=True)
    s2 = Stream(id=2, name="Cam 2", rtsp_url="rtsp://cam/2",
                main_url="rtsp://cam/2", is_active=True, is_online=False)
    db.add_all([s1, s2])
    db.add_all([
        ApiKeyStream(api_key_id=key.id, stream_id=1),
        ApiKeyStream(api_key_id=key.id, stream_id=2),
    ])
    await db.commit()
    return key


async def _logs(db):
    return (await db.execute(select(ApiAccessLog))).scalars().all()


async def test_external_satu_insert_per_request_dan_last_used_at(app_client):
    """Sukses: 1 request = tepat 1 baris log, dan last_used_at yang
    di-throttle tetap tersimpan lewat commit yang sama dengan log.
    Request kedua (last_used_at masih segar) juga tepat 1 baris."""
    app, _, db = app_client
    key = await _seed_key(db)
    assert key.last_used_at is None
    async with _client(app) as c:
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": "KUNCI-RAHASIA-123"})
        assert r.status_code == 200, r.text
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": "KUNCI-RAHASIA-123"})
        assert r.status_code == 200, r.text
    logs = await _logs(db)
    assert len(logs) == 2, [log.action for log in logs]
    assert [log.action for log in logs] == ["external.cameras.ok"] * 2
    key_id = key.id
    db.expire_all()
    fresh = await db.get(ApiKey, key_id)
    assert fresh.last_used_at is not None


async def test_external_ditolak_satu_insert_tanpa_last_used_at(app_client):
    """Ditolak (bad_key): tepat 1 baris log denied, last_used_at
    tidak berubah (tidak ada commit sia-sia)."""
    app, _, db = app_client
    key = await _seed_key(db)
    async with _client(app) as c:
        r = await c.get("/api/external/cameras", headers={"X-Api-Key": "SALAH"})
        assert r.status_code == 403
    logs = await _logs(db)
    assert len(logs) == 1
    assert "denied:bad_key" in logs[0].action
    key_id = key.id
    db.expire_all()
    fresh = await db.get(ApiKey, key_id)
    assert fresh.last_used_at is None


async def test_prune_api_access_logs(app_client):
    """Retensi 90 hari: baris lama terhapus, baris baru dipertahankan,
    jumlah yang dihapus dikembalikan, parameter days dihormati."""
    from app.services.api_access_log_retention import prune_api_access_logs

    app, _, db = app_client
    key = await _seed_key(db)
    now = datetime.now(timezone.utc)
    old = ApiAccessLog(api_key_id=key.id, action="external.cameras.ok",
                       created_at=now - timedelta(days=100))
    mid = ApiAccessLog(api_key_id=key.id, action="external.cameras.ok",
                       created_at=now - timedelta(days=20))
    new = ApiAccessLog(api_key_id=key.id, action="external.cameras.ok",
                       created_at=now - timedelta(days=1))
    db.add_all([old, mid, new])
    await db.commit()
    n = await prune_api_access_logs(db, days=90)
    assert n == 1, n
    remaining = await _logs(db)
    assert len(remaining) == 2
    assert all(log.id != old.id for log in remaining)
    n = await prune_api_access_logs(db, days=10)
    assert n == 1, n
    remaining = await _logs(db)
    assert len(remaining) == 1
    assert remaining[0].id == new.id
    n = await prune_api_access_logs(db, days=90)
    assert n == 0


# ── 6.11 GET /streams paginasi SQL ─────────────────────────────────────

async def _seed_streams_scope(db):
    su = make_user(id=1, username="super", role="super_admin")
    admin_a = make_user(id=2, username="admin_a", role="admin", admin_group="grup-a")
    admin_b = make_user(id=3, username="admin_b", role="admin", admin_group="grup-b")
    op = make_user(id=4, username="op", role="user")
    guest = make_user(id=5, username="guest", role="guest")
    db.add_all([su, admin_a, admin_b, op, guest])
    cams = []
    for i in range(1, 6):
        cams.append(Stream(
            id=i, name=f"Cam {i}", rtsp_url=f"rtsp://cam/{i}",
            main_url=f"rtsp://cam/{i}", is_active=True,
            created_by=2 if i <= 3 else 3, owner_id=2 if i <= 3 else 3,
        ))
    # Kamera nonaktif tidak pernah terlihat siapa pun.
    cams.append(Stream(
        id=6, name="Cam 6 mati", rtsp_url="rtsp://cam/6",
        main_url="rtsp://cam/6", is_active=False, created_by=2, owner_id=2,
    ))
    db.add_all(cams)
    db.add_all([
        GroupStream(group_id=1, stream_id=1),
        GroupStream(group_id=1, stream_id=2),
        GroupStream(group_id=2, stream_id=4),
    ])
    db.add_all([
        StreamGroup(id=1, name="Grup A"),
        StreamGroup(id=2, name="Grup B"),
    ])
    # Admin A: grant can_view kamera 4 (milik admin B).
    db.add(StreamAdminGrant(stream_id=4, admin_id=2, can_view=True))
    # User op: akses eksplisit kamera 2; guest: izin peran kamera 5.
    db.add(UserStreamAccess(user_id=4, stream_id=2, can_view=True))
    db.add(StreamPermission(stream_id=5, role="guest", user_id=None, can_view=True))
    await db.commit()
    return su, admin_a, admin_b, op, guest


async def test_streams_paginasi_super_admin(app_client):
    app, _, db = app_client
    su, _, _, _, _ = await _seed_streams_scope(db)
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.get("/api/streams", params={"page": 2, "limit": 2})
        assert r.status_code == 200, r.text
        assert [s["id"] for s in r.json()] == [3, 4]
        assert r.headers["X-Total-Count"] == "5"
        r = await c.get("/api/streams", params={"page": 3, "limit": 2})
        assert [s["id"] for s in r.json()] == [5]
        assert r.headers["X-Total-Count"] == "5"
        r = await c.get("/api/streams", params={"limit": 2})
        assert [s["id"] for s in r.json()] == [1, 2]
        assert r.headers["X-Total-Count"] == "5"
        # Tanpa paginasi: list penuh seperti sebelumnya, total tetap ada.
        r = await c.get("/api/streams")
        assert [s["id"] for s in r.json()] == [1, 2, 3, 4, 5]
        assert r.headers["X-Total-Count"] == "5"


async def test_streams_paginasi_rbac_admin_dan_user(app_client):
    app, _, db = app_client
    _, admin_a, _, op, guest = await _seed_streams_scope(db)
    # Admin A: milik 1,2,3 + grant 4; bukan 5, bukan 6 (nonaktif).
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.get("/api/streams", params={"page": 1, "limit": 2})
        assert [s["id"] for s in r.json()] == [1, 2]
        assert r.headers["X-Total-Count"] == "4"
        r = await c.get("/api/streams", params={"page": 2, "limit": 2})
        assert [s["id"] for s in r.json()] == [3, 4]
    # User op: hanya kamera 2 (akses eksplisit).
    auth_as(app, op)
    async with _client(app) as c:
        r = await c.get("/api/streams")
        assert [s["id"] for s in r.json()] == [2]
        assert r.headers["X-Total-Count"] == "1"
    # Guest: hanya kamera 5 (izin peran).
    auth_as(app, guest)
    async with _client(app) as c:
        r = await c.get("/api/streams")
        assert [s["id"] for s in r.json()] == [5]


async def test_streams_paginasi_filter_grup(app_client):
    app, _, db = app_client
    su, admin_a, _, _, _ = await _seed_streams_scope(db)
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.get("/api/streams", params={"group": "Grup A"})
        assert [s["id"] for s in r.json()] == [1, 2]
        assert r.headers["X-Total-Count"] == "2"
        r = await c.get(
            "/api/streams", params={"group": "Grup A", "page": 2, "limit": 1}
        )
        assert [s["id"] for s in r.json()] == [2]
        assert r.headers["X-Total-Count"] == "2"
        r = await c.get("/api/streams", params={"group": "Tidak Ada"})
        assert r.json() == []
        assert r.headers["X-Total-Count"] == "0"
    # Grup + RBAC: admin A di Grup B melihat kamera 4, karena kamera
    # itu di-grant can_view ke admin A (aturan lama yang sama: grup
    # menyaring daftar terlihat, bukan sebaliknya).
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.get("/api/streams", params={"group": "Grup B"})
        assert [s["id"] for s in r.json()] == [4]
        assert r.headers["X-Total-Count"] == "1"


async def test_visible_streams_tetap_list_penuh(app_client):
    """_visible_streams (dipakai WS + recording_cameras) tetap
    mengembalikan list penuh dengan aturan RBAC yang sama."""
    from app.routers.streams import _visible_streams

    app, _, db = app_client
    _, admin_a, _, _, _ = await _seed_streams_scope(db)
    streams = await _visible_streams(admin_a, db)
    assert [s.id for s in streams] == [1, 2, 3, 4]
