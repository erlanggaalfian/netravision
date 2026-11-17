"""Tes perbaikan Area 5 (Background loop & worker) audit 2026-11-17.

5.1 shutdown bersih, 5.2 antrean OAuth berbatas+dedup+scan batch,
5.3/5.4 sync MediaMTX paralel+deadline+aclose, 5.5 poster paralel,
5.6 cleanup sesi per tahap+batas file, 5.7 retensi per akun,
5.8 metrik loop di /api/health, 5.9 prune staging sejam sekali,
5.10 cache/registry berbatas, 5.11 stagger startup.
"""

import asyncio
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.db
import app.main as main_mod
import app.services.drive as drive_mod
import app.services.drive_accounts as da_mod
import app.services.drive_mirror as mirror_mod
import app.services.gdrive_rclone as gr_mod
import app.services.loop_health as lh
import app.services.posters as posters_mod
import app.services.stream_paths as sp_mod
from app.db.base import Base
from app.models.drive import GoogleDriveFolder
from app.models.streams import Stream
from app.services.drive import DriveUploader
from tests.test_drive import FakeDrive, _settings


@pytest.fixture(autouse=True)
def _reset_loop_health():
    lh.reset()
    mirror_mod._last_prune.clear()
    # Klaim upload (Area 3) dipegang sampai 1800 dtk; tes _mirror_one di
    # file ini meninggalkan klaim (stream 7, "2026-11-02_10-00-00.mp4")
    # yang akan memblokir tes mirror lain dengan nama file sama bila
    # tidak dibersihkan.
    from app.services import upload_claims as _claims

    _claims._claims.clear()
    yield
    lh.reset()
    mirror_mod._last_prune.clear()
    _claims._claims.clear()


async def _make_factory(tmp_path):
    """Factory sesi sqlite per-test (mirip conftest.db_session)."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/t5.db", poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


# ---------------------------------------------------------------- 5.1
async def test_cancel_and_wait_menunggu_task_selesai():
    done = []

    async def _worker():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            done.append("dibatalkan")
            await asyncio.sleep(0.01)  # simulasi penyelesaian aman
            done.append("selesai")

    t = asyncio.create_task(_worker())
    await asyncio.sleep(0)
    assert await main_mod._cancel_and_wait([t], timeout=5.0) is True
    assert done == ["dibatalkan", "selesai"]
    assert t.done()


async def test_cancel_and_wait_timeout_bila_task_mengabaikan_cancel():
    async def _bandel():
        while True:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                # Abaikan pembatalan (kasus terburuk): shutdown tidak
                # boleh menggantung selamanya.
                await asyncio.sleep(60)

    t = asyncio.create_task(_bandel())
    await asyncio.sleep(0)
    assert await main_mod._cancel_and_wait([t], timeout=0.2) is False
    t.cancel()
    try:
        await asyncio.wait_for(t, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


async def test_cancel_and_wait_tanpa_task():
    assert await main_mod._cancel_and_wait([]) is True


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeUploader:
    """Uploader palsu: loop-nya menunggu event, catat bila dibersihkan."""

    def __init__(self):
        self.cleaned = False
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def run_upload_loop(self):
        self.started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cleaned = True
            await asyncio.sleep(0.01)
            raise
        finally:
            self.stopped.set()

    async def scan_and_enqueue(self, db=None):
        return 0

    async def apply_drive_retention(self, days):
        return 0


async def test_drive_loop_finally_menunggu_child(monkeypatch):
    """5.1: _drive_loop yang dibatalkan menunggu child upload loop
    selesai (dulu hanya cancel tanpa tunggu)."""
    fake_up = _FakeUploader()

    async def _active(db):
        return {"k": fake_up}

    monkeypatch.setattr(da_mod, "active_uploaders", _active)
    monkeypatch.setattr(
        main_mod, "get_session_factory", lambda: (lambda: _FakeSession())
    )
    task = asyncio.create_task(main_mod._drive_loop(initial_delay=0))
    await asyncio.wait_for(fake_up.started.wait(), timeout=5)
    task.cancel()
    await asyncio.wait_for(task, timeout=5)
    assert fake_up.cleaned is True
    assert fake_up.stopped.is_set()


# ---------------------------------------------------------------- 5.2
async def test_queue_upload_dedup(tmp_path):
    up = DriveUploader(settings=_settings(tmp_path), service=FakeDrive())
    p = str(tmp_path / "a.mp4")
    assert await up.queue_upload(p, "Cam A") is True
    assert await up.queue_upload(p, "Cam A") is False  # duplikat ditolak
    assert up.queue_size() == 1


async def test_queue_upload_penuh_tidak_memblokir(monkeypatch, tmp_path):
    monkeypatch.setattr(drive_mod, "_QUEUE_MAXSIZE", 2)
    up = DriveUploader(settings=_settings(tmp_path), service=FakeDrive())
    assert await up.queue_upload(str(tmp_path / "a.mp4"), "Cam A") is True
    assert await up.queue_upload(str(tmp_path / "b.mp4"), "Cam A") is True
    # Antrean penuh: ditolak langsung (False), bukan menggantung di put.
    assert await up.queue_upload(str(tmp_path / "c.mp4"), "Cam A") is False
    assert up.queue_size() == 2


async def test_run_upload_loop_menghapus_dedup_set(tmp_path):
    svc = FakeDrive()
    up = DriveUploader(settings=_settings(tmp_path), service=svc)
    p = tmp_path / "q.mp4"
    p.write_bytes(b"v" * 8)
    await up.queue_upload(str(p), "Cam A")
    assert str(p) in up._queued
    task = asyncio.create_task(up.run_upload_loop())
    try:
        await asyncio.wait_for(up._queue.join(), timeout=5)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Sudah diproses: keluar dari set dedup, jadi scan berikut boleh
    # mengantrekan ulang bila file masih ada (mis. upload gagal).
    assert str(p) not in up._queued


async def test_scan_batch_satu_listing_per_folder(tmp_path):
    """5.2: scan 2 segmen dalam 1 folder = 1 panggilan list (dulu 2x
    find_file, satu panggilan Drive API per segmen)."""
    svc = FakeDrive()
    calls = {"list": 0}
    orig_list = svc.list

    def _counting_list(*a, **k):
        calls["list"] += 1
        return orig_list(*a, **k)

    svc.list = _counting_list
    up = DriveUploader(settings=_settings(tmp_path), service=svc)
    d = tmp_path / "stream_7"
    d.mkdir()
    (d / "a.mp4").write_bytes(b"1")
    (d / "b.mp4").write_bytes(b"2")
    n = await up.scan_and_enqueue()
    assert n == 2
    # 1 list untuk ensure_folder (cari root) + 1 untuk cari folder
    # stream_7 + 1 list_files batch = 3; yang penting TIDAK 2x find_file
    # (satu per segmen) lagi: total list kecil dan tetap.
    assert calls["list"] == 3
    assert up.queue_size() == 2


async def test_scan_dilewati_bila_scan_sebelumnya_belum_selesai(tmp_path):
    """5.2: scan yang belum selesai tidak ditumpuk scan berikutnya."""
    up = DriveUploader(settings=_settings(tmp_path), service=FakeDrive())
    await up._scan_lock.acquire()
    try:
        assert await up.scan_and_enqueue() == 0
    finally:
        up._scan_lock.release()


# ------------------------------------------------------------ 5.3 + 5.4
class _FakeMTX:
    def __init__(self, fail_get_paths=False, delay=0.0):
        self.fail_get_paths = fail_get_paths
        self.delay = delay
        self.aclose_calls = 0
        self.deleted = []

    async def get_paths(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_get_paths:
            raise RuntimeError("mediamtx down")
        return [{"name": "stream_1"}, {"name": "stream_99"}]

    async def delete_path(self, name):
        self.deleted.append(name)

    async def aclose(self):
        self.aclose_calls += 1


async def _seed_streams(factory, n=2):
    async with factory() as db:
        for i in range(1, n + 1):
            db.add(Stream(
                id=i, name=f"Cam {i}", rtsp_url=f"rtsp://x/{i}",
                main_url=f"rtsp://x/{i}", is_active=True,
                recording_enabled=False, retention_days=7,
            ))
        await db.commit()


async def test_sync_mediamtx_aclose_saat_get_paths_gagal(monkeypatch, tmp_path):
    """5.4: client httpx ditutup walau get_paths gagal (dulu bocor)."""
    engine, factory = await _make_factory(tmp_path)
    try:
        await _seed_streams(factory, 1)
        fake = _FakeMTX(fail_get_paths=True)
        monkeypatch.setattr(app.db, "get_session_factory", lambda: factory)
        monkeypatch.setattr(
            "app.services.mediamtx.get_mediamtx", lambda: fake
        )
        await main_mod._sync_mediamtx_once()
        assert fake.aclose_calls == 1
    finally:
        await engine.dispose()


async def test_sync_mediamtx_paralel_dan_tutup_client(monkeypatch, tmp_path):
    """5.3: registrasi kamera jalan paralel; 5.4: client ditutup."""
    engine, factory = await _make_factory(tmp_path)
    try:
        await _seed_streams(factory, 4)
        fake = _FakeMTX()
        calls = []
        active = {"n": 0, "max": 0}

        async def _fake_register(mediamtx, sid, *a, **k):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            try:
                await asyncio.sleep(0.05)
            finally:
                active["n"] -= 1
            calls.append(sid)

        monkeypatch.setattr(app.db, "get_session_factory", lambda: factory)
        monkeypatch.setattr(
            "app.services.mediamtx.get_mediamtx", lambda: fake
        )
        monkeypatch.setattr(sp_mod, "register_stream", _fake_register)
        await main_mod._sync_mediamtx_once()
        assert sorted(calls) == [1, 2, 3, 4]
        assert active["max"] > 1  # benar-benar paralel, bukan sekuensial
        assert fake.aclose_calls == 1
        assert fake.deleted == ["stream_99"]  # path yatim dihapus
    finally:
        await engine.dispose()


async def test_sync_mediamtx_deadline_tetap_tutup_client(monkeypatch, tmp_path):
    """5.3: iterasi yang melebihi deadline dibatalkan; 5.4: client
    tetap ditutup."""
    engine, factory = await _make_factory(tmp_path)
    try:
        await _seed_streams(factory, 1)
        fake = _FakeMTX(delay=5.0)
        monkeypatch.setattr(app.db, "get_session_factory", lambda: factory)
        monkeypatch.setattr(
            "app.services.mediamtx.get_mediamtx", lambda: fake
        )
        monkeypatch.setattr(main_mod, "_SYNC_DEADLINE_SEC", 0.05)
        await main_mod._sync_mediamtx_once()
        assert fake.aclose_calls == 1
        assert lh.snapshot()["mediamtx_sync"]["consecutive_failures"] == 1
    finally:
        await engine.dispose()


# ---------------------------------------------------------------- 5.5
async def test_poster_round_lewati_poster_segar(tmp_path):
    """5.5: kamera yang posternya masih segar dilewati (hemat sesi RTSP)."""
    posters_dir = tmp_path / "posters"
    posters_dir.mkdir()
    segar = posters_dir / "stream_1.jpg"
    segar.write_bytes(b"x" * 100)  # mtime baru
    lama = posters_dir / "stream_2.jpg"
    lama.write_bytes(b"x" * 100)
    old = time.time() - 3600
    os.utime(lama, (old, old))
    called = []

    def _fake_capture(sid, url, out):
        called.append(sid)
        return True

    streams = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    n = await posters_mod._poster_round(
        streams, "127.0.0.1", str(posters_dir), 60, _capture=_fake_capture
    )
    assert called == [2]
    assert n == 1


async def test_poster_round_paralel():
    """5.5: penangkapan poster jalan paralel (semaphore)."""
    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def _fake_capture(sid, url, out):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.05)
        with lock:
            active["n"] -= 1
        return True

    streams = [SimpleNamespace(id=i) for i in range(6)]
    n = await posters_mod._poster_round(
        streams, "127.0.0.1", "/tmp/tidak-ada", 60,
        max_concurrency=3, _capture=_fake_capture,
    )
    assert n == 6
    assert active["max"] == 3


# ---------------------------------------------------------------- 5.6
def _fake_rclone_lsjson_delete(monkeypatch, n_old=5):
    """Palsukan _rclone_run_sync: lsjson kembalikan n_old file tua,
    delete selalu sukses."""
    deleted = []

    def _fake(args, timeout=60):
        if args[0] == "lsjson":
            entries = [
                {
                    "Path": f"stream_1/2020-01-0{i}_10-00-00.mp4",
                    "Name": f"2020-01-0{i}_10-00-00.mp4",
                    "ModTime": f"2020-01-0{i}T10:00:00Z",
                }
                for i in range(1, n_old + 1)
            ]
            return 0, json.dumps(entries), ""
        if args[0] == "delete":
            deleted.append(args[1])
            return 0, "", ""
        return 0, "", ""

    import app.services.disks as disks_mod

    monkeypatch.setattr(disks_mod, "_rclone_run_sync", _fake)
    return deleted


async def test_cleanup_folder_retention_batas_per_putaran(
    monkeypatch, db_session
):
    """5.6: satu putaran retensi folder dibatasi max_files."""
    import app.services.disks as disks_mod

    db_session.add(GoogleDriveFolder(
        folder_url="https://drive/x", folder_id="folder1",
        folder_name="CCTV", retention_days=30,
    ))
    await db_session.commit()
    deleted = _fake_rclone_lsjson_delete(monkeypatch, n_old=5)
    n = await disks_mod.cleanup_folder_retention(db_session, max_files=2)
    assert n == 2
    # Penghapusan kini batch (satu `rclone delete --files-from` per
    # folder): yang penting 2 file terhitung terhapus dan tepat satu
    # panggilan delete batch dikeluarkan.
    assert len(deleted) == 1


async def test_cleanup_rclone_remote_batas_per_putaran(monkeypatch, db_session):
    """5.6: satu putaran cleanup remote dibatasi max_files."""
    import app.services.disks as disks_mod

    db_session.add(GoogleDriveFolder(
        folder_url="https://drive/x", folder_id="folder1",
        folder_name="CCTV",
    ))
    await db_session.commit()
    _fake_rclone_lsjson_delete(monkeypatch, n_old=5)

    async def _usage(remote):
        return 99.0  # selalu penuh supaya tidak berhenti di target

    monkeypatch.setattr(disks_mod, "_rclone_usage_pct", _usage)
    n = await disks_mod.cleanup_rclone_remote(
        db_session, "gdrive", 90.0, 50.0, max_files=3
    )
    assert n == 3


# ---------------------------------------------------------------- 5.7
def test_retention_schedule_sukses_sehari_gagal_backoff():
    """5.7: sukses -> +24 jam; gagal -> retry backoff, bukan 24 jam."""
    sched = main_mod._DriveRetentionSchedule()
    assert sched.due("a", now=1000.0) is True
    sched.mark_success("a", now=1000.0)
    assert sched.due("a", now=2000.0) is False
    assert sched.due("a", now=1000.0 + 86400) is True
    # Gagal: retry pertama 5 menit, lalu 10 menit, lalu 20 menit...
    sched.mark_failure("b", now=1000.0)
    assert sched.due("b", now=1000.0 + 299) is False
    assert sched.due("b", now=1000.0 + 300) is True
    sched.mark_failure("b", now=1300.0)
    assert sched.due("b", now=1300.0 + 599) is False
    assert sched.due("b", now=1300.0 + 600) is True
    # Backoff dibatasi maks 1 jam.
    for _ in range(8):
        sched.mark_failure("c", now=1000.0)
    assert sched.due("c", now=1000.0 + 3599) is False
    assert sched.due("c", now=1000.0 + 3600) is True


# ---------------------------------------------------------------- 5.8
def test_loop_health_registry():
    lh.record_tick("sync")
    lh.record_success("sync", 12.5)
    snap = lh.snapshot()
    assert snap["sync"]["last_tick_at"] is not None
    assert snap["sync"]["last_success_at"] is not None
    assert snap["sync"]["consecutive_failures"] == 0
    assert snap["sync"]["last_duration_ms"] == 12.5
    lh.record_failure("sync", ValueError("boom"))
    snap = lh.snapshot()
    assert snap["sync"]["consecutive_failures"] == 1
    assert snap["sync"]["last_error"] == "boom"
    lh.record_success("sync")
    assert lh.snapshot()["sync"]["consecutive_failures"] == 0
    assert lh.snapshot()["sync"]["last_error"] is None


async def test_health_memuat_loops(monkeypatch, app_client):
    """5.8: GET /api/health memuat denyut loop latar."""
    import app.routers.system as system_mod
    from httpx import ASGITransport, AsyncClient

    app, _fake, _db = app_client
    system_mod.reset_health_cache()
    lh.record_tick("poster")
    lh.record_success("poster", 5.0)

    async def _ok_db():
        return {"name": "database", "status": "ok", "latency_ms": 1.0}

    async def _ok_mtx():
        return {"name": "mediamtx", "status": "ok", "latency_ms": 1.0}

    monkeypatch.setattr(system_mod, "check_database", _ok_db)
    monkeypatch.setattr(system_mod, "check_mediamtx", _ok_mtx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["loops"]["poster"]["consecutive_failures"] == 0
    assert r.json()["loops"]["poster"]["last_success_at"] is not None


# ---------------------------------------------------------------- 5.9
def test_prune_due_sejam_sekali():
    assert mirror_mod._prune_due("/staging/stream_1") is True
    assert mirror_mod._prune_due("/staging/stream_1") is False
    mirror_mod._last_prune["/staging/stream_1"] = time.time() - 3601
    assert mirror_mod._prune_due("/staging/stream_1") is True


def test_mirror_one_prune_paling_sekali_sejam(monkeypatch, tmp_path):
    """5.9: dua putaran mirror berurutan hanya memanggil prune sekali."""
    from app.core.config import get_settings

    rec = tmp_path / "recordings" / "stream_7"
    rec.mkdir(parents=True)
    stable = rec / "2026-11-02_10-00-00.mp4"
    stable.write_bytes(b"x" * 100)
    old = time.time() - 60
    os.utime(stable, (old, old))
    s = get_settings()
    monkeypatch.setattr(s, "drive_mirror_require_mount", False)
    calls = []
    orig_prune = mirror_mod._prune_staging
    monkeypatch.setattr(
        mirror_mod, "_prune_staging",
        lambda *a, **k: calls.append(a),
    )
    try:
        mirror_mod._mirror_one([str(rec)], str(tmp_path / "staging"), 7)
        mirror_mod._mirror_one([str(rec)], str(tmp_path / "staging"), 7)
        assert len(calls) == 1
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------- 5.10
async def test_folder_cache_kedaluwarsa(tmp_path):
    """5.10: entri cache folder yang kedaluwarsa di-resolve ulang."""
    svc = FakeDrive()
    calls = {"list": 0}
    orig_list = svc.list

    def _counting_list(*a, **k):
        calls["list"] += 1
        return orig_list(*a, **k)

    svc.list = _counting_list
    up = DriveUploader(settings=_settings(tmp_path), service=svc)
    fid = await up.ensure_folder("Cam A")
    n1 = calls["list"]
    assert await up.ensure_folder("Cam A") == fid
    assert calls["list"] == n1  # cache hit
    # Buat entri kedaluwarsa (TTL 1 jam).
    key = "name:Cam A"
    old_fid, _at = up._folder_cache[key]
    up._folder_cache[key] = (old_fid, time.monotonic() - 3601)
    assert await up.ensure_folder("Cam A") == fid
    assert calls["list"] > n1  # resolve ulang


async def test_prune_drive_client_cache_akun_dihapus(db_session):
    """5.10: client cache akun yang tidak lagi connected dibuang."""
    da_mod._clients["akun-hilang"] = object()
    ups = await da_mod.active_uploaders(db_session)
    assert ups == {}
    assert "akun-hilang" not in da_mod._clients


# --------------------------------------------------------------- 5.11
async def test_mirror_loop_initial_delay(monkeypatch):
    """5.11: mirror_loop tidur initial_delay dulu sebelum putaran pertama."""
    delays = []

    async def _fake_sleep(delay):
        delays.append(delay)
        if len(delays) >= 2:
            raise asyncio.CancelledError

    async def _no_folders():
        return []

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(mirror_mod, "_folders", _no_folders)
    await mirror_mod.mirror_loop(initial_delay=20)
    assert delays[0] == 20
    assert delays[1] == mirror_mod._INTERVAL_SEC


async def test_upload_loop_initial_delay(monkeypatch):
    """5.11: upload_loop tidur initial_delay dulu sebelum putaran pertama."""
    import app.services.drive_uploader as up_mod

    delays = []

    async def _fake_sleep(delay):
        delays.append(delay)
        if len(delays) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    await up_mod.upload_loop(initial_delay=45)
    # Putaran pertama ditunda 45 detik; sleep kedua adalah backoff
    # putaran yang gagal di env test (tanpa rclone), bukan interval.
    assert delays[0] == 45
    assert len(delays) >= 2


# ------------------------------------------------- 5.1 rclone cancel
async def test_run_rclone_dibatalkan_memastikan_proses_mati(monkeypatch, tmp_path):
    """5.1: _run_rclone yang dibatalkan (shutdown) mematikan proses
    rclone-nya, bukan meninggalkannya yatim."""
    import app.services.gdrive_rclone as gr

    pid_file = tmp_path / "child.pid"
    script = tmp_path / "fake-rclone.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"echo $$ > {pid_file}\n"
        "sleep 30\n"
    )
    script.chmod(0o755)
    monkeypatch.setattr(gr, "find_rclone", lambda: str(script))
    task = asyncio.create_task(gr._run_rclone("lsjson", "gdrive:x", timeout=60))
    # Tunggu proses anak benar-benar jalan.
    for _ in range(50):
        if pid_file.exists():
            break
        await asyncio.sleep(0.05)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text().strip())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Proses anak harus sudah mati (bukan yatim yang terus tidur).
    for _ in range(50):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("proses rclone yatim masih hidup setelah cancel")
