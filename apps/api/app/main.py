"""App factory: create_app(). JSON logging, CORS, mount router /api."""

import asyncio
import logging
import shutil
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core import audit, metrics, security_headers
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import dispose_engine, get_session_factory
from app.services.loop_health import (
    drive_retention_lock,
    record_failure,
    record_success,
    record_tick,
)

# Area 5, 5.1: shutdown menunggu task latar selesai (bukan hanya cancel).
_SHUTDOWN_TIMEOUT_SEC = 30.0
# Area 5, 5.3: satu iterasi sync MediaMTX dibatasi total 180 detik dan
# dijalankan paralel (semaphore 8), supaya interval 60 detik bukan ilusi.
_SYNC_DEADLINE_SEC = 180.0
_SYNC_MAX_CONCURRENCY = 8
# Area 5, 5.7: retensi Drive sekali sehari per akun bila sukses; bila
# gagal, coba lagi dengan backoff (bukan tertunda 24 jam diam-diam).
_DRIVE_RETENTION_INTERVAL_SEC = 86400
_DRIVE_RETENTION_RETRY_MAX_SEC = 3600
# Area 5, 5.6: batas hapus per putaran cleanup supaya satu putaran
# tidak berjalan berjam-jam.
_CLEANUP_MAX_FILES_PER_ROUND = 200
# Area 5, 5.7: satu putaran retensi Drive dibatasi 10 menit.
_DRIVE_RETENTION_TIMEOUT_SEC = 600
from app.routers import (
    admin_ads,
    admin_audit,
    admin_disks,
    admin_drive,
    admin_keys,
    admin_scan,
    admin_streams,
    admin_users,
    auth,
    external,
    maps,
    media,
    recordings,
    streams,
    system,
    ws,
)


async def _cancel_and_wait(
    tasks, timeout: float = _SHUTDOWN_TIMEOUT_SEC, log=None
) -> bool:
    """Batalkan task latar lalu TUNGGU sampai selesai (Area 5, 5.1).

    Dulu lifespan hanya `t.cancel()` lalu langsung `dispose_engine()`,
    sehingga upload/commit/hapus yang sedang berjalan bisa terpotong di
    tengah jalan. Return True bila semua task selesai sebelum timeout.
    Task yang mengabaikan pembatalan (mis. upload di thread yang tidak
    bisa diinterupsi) tetap dibiarkan: timeout mencegah shutdown
    menggantung selamanya, dan keterlambatan itu dicatat.
    """
    if not tasks:
        return True
    for t in tasks:
        t.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=timeout
        )
        return True
    except asyncio.TimeoutError:
        if log is not None:
            still = [t for t in tasks if not t.done()]
            log.warning(
                "shutdown: %d task latar tidak selesai dalam %.0f detik, "
                "dilanjutkan tanpa menunggu",
                len(still), timeout,
            )
        return False


class _DriveRetentionSchedule:
    """Jadwal retensi Drive per akun (Area 5, 5.7).

    Dulu `last_drive_retention` dicatat SEBELUM retensi jalan, jadi
    retensi yang gagal diam-diam tertunda 24 jam. Kini timestamp hanya
    dicatat setelah sukses per akun; bila gagal, percobaan berikut
    dijadwalkan dengan backoff (5 menit, 10 menit, ..., maks 1 jam).
    """

    def __init__(self):
        self._next: dict[str, float] = {}
        self._failures: dict[str, int] = {}

    def due(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return now >= self._next.get(key, 0.0)

    def mark_success(self, key: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._next[key] = now + _DRIVE_RETENTION_INTERVAL_SEC
        self._failures[key] = 0

    def mark_failure(self, key: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        delay = min(
            300 * (2 ** (failures - 1)), _DRIVE_RETENTION_RETRY_MAX_SEC
        )
        self._next[key] = now + delay


async def _status_broadcaster() -> None:
    """Tiap 10 detik: poll status kamera, broadcast perubahan ke klien /ws."""
    from app.services.camera_status import poll_once
    from app.services.mediamtx import get_mediamtx

    log = logging.getLogger("netravision.ws")
    mediamtx = get_mediamtx()
    try:
        while True:
            await asyncio.sleep(10)
            record_tick("status_broadcaster")
            try:
                async with get_session_factory()() as db:
                    changes = await poll_once(db, mediamtx)
                if changes:
                    await ws.manager.broadcast({"type": "status", "changes": changes})
                record_success("status_broadcaster")
            except Exception as e:  # satu poll gagal tidak boleh mematikan loop
                log.warning("broadcaster gagal: %s", e)
                record_failure("status_broadcaster", e)
    except asyncio.CancelledError:
        pass
    finally:
        await mediamtx.aclose()


async def _sync_mediamtx_once() -> None:
    """Satu iterasi sinkronisasi path kamera ke MediaMTX.

    Area 5, 5.3: registrasi per kamera dijalankan PARALEL (semaphore 8,
    dulu sekuensial 2-4 HTTP call per kamera x 68 kamera) dan satu
    iterasi dibatasi deadline total. Area 5, 5.4: client httpx selalu
    ditutup lewat `finally` (dulu jalur `get_paths` gagal `continue`
    tanpa `aclose()`, membocorkan client tiap 60 detik saat MediaMTX
    down). Baris kamera dimuat ulang sesaat sebelum patch (5.3),
    supaya perubahan admin di tengah iterasi tidak ditimpa snapshot lama.
    """
    from sqlalchemy import select

    from app.db import get_session_factory
    from app.models.streams import Stream
    from app.services.mediamtx import get_mediamtx

    log = logging.getLogger("netravision.mediamtx_sync")
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            _sync_mediamtx_once_inner(), timeout=_SYNC_DEADLINE_SEC
        )
    except asyncio.TimeoutError:
        log.warning(
            "mediamtx sync: iterasi melebihi %ds, dilewati",
            _SYNC_DEADLINE_SEC,
        )
        record_failure("mediamtx_sync", "iteration deadline exceeded")
        return
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("mediamtx sync loop error: %s", e)
        record_failure("mediamtx_sync", e)
        return
    record_success("mediamtx_sync", (time.monotonic() - started) * 1000)


async def _sync_mediamtx_once_inner() -> None:
    from sqlalchemy import select

    from app.db import get_session_factory
    from app.models.streams import Stream
    from app.services.mediamtx import get_mediamtx

    log = logging.getLogger("netravision.mediamtx_sync")
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(Stream).where(Stream.is_active.is_(True)))
        streams = list(result.scalars().all())
    mediamtx = get_mediamtx()
    try:
        try:
            paths = await mediamtx.get_paths()
        except Exception:  # noqa: BLE001 - MediaMTX down, coba lagi nanti
            log.warning("mediamtx sync: get_paths gagal, coba lagi nanti")
            return
        existing = {p.get("name") for p in paths if isinstance(p, dict)}
        from app.services.disks import record_path_for
        from app.services.stream_paths import register_stream

        wanted: set[str] = set()
        for s in streams:
            # Sub hanya diinginkan bila kamera punya sub_url asli;
            # tanpa sub_url, path sub tidak dibuat (transcoder mati
            # total) dan path sub lama ikut terhapus sebagai yatim.
            wanted.add(f"stream_{s.id}")
            if s.sub_url:
                wanted.add(f"stream_{s.id}_sub")

        sem = asyncio.Semaphore(_SYNC_MAX_CONCURRENCY)

        async def _register_one(s) -> None:
            # Muat ulang baris kamera sesaat sebelum patch: snapshot
            # iterasi bisa basi bila admin mengubah kamera di tengah
            # iterasi; jangan timpa perubahan itu dengan data lama.
            async with factory() as db:
                fresh = await db.get(Stream, s.id)
                if fresh is None or not fresh.is_active:
                    return
                # Tangkap semua nilai DI DALAM sesi (instance ter-detach
                # setelah sesi ditutup).
                sid = fresh.id
                args = (
                    fresh.main_url or fresh.rtsp_url or "",
                    bool(fresh.recording_enabled),
                    fresh.retention_days or 7,
                    record_path_for(fresh, get_settings().recordings_dir),
                    fresh.sub_url,
                )
            async with sem:
                try:
                    await register_stream(
                        mediamtx, sid, args[0], args[1],
                        retention_days=args[2], record_path=args[3],
                        sub_source=args[4],
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("sync path stream_%s gagal: %s", sid, e)

        await asyncio.gather(*[_register_one(s) for s in streams])
        # Hapus path yatim (kamera dihapus/dinonaktifkan).
        for name in existing - wanted:
            if name.startswith("stream_"):
                try:
                    await mediamtx.delete_path(name)
                except Exception:  # noqa: BLE001
                    pass
    finally:
        # Area 5, 5.4: selalu tutup client, termasuk jalur gagal dan
        # saat iterasi dibatalkan (deadline/shutdown).
        await mediamtx.aclose()


async def _mediamtx_sync_loop() -> None:
    """Sinkronisasi path kamera ke MediaMTX: saat start + tiap 60 detik.

    Path MediaMTX bersifat dinamis (tidak tersimpan), bila MediaMTX restart,
    semua path hilang. Loop ini mendaftarkan ulang semua kamera aktif dan
    menghapus path milik kamera yang sudah dihapus/dinonaktifkan.

    Area 5, 5.3: bila iterasi sebelumnya belum selesai saat tick
    berikutnya tiba, tick itu DILEWATI (bukan menumpuk), supaya sync
    tidak berjalan ganda dengan snapshot yang makin basi.
    """
    log = logging.getLogger("netravision.mediamtx_sync")
    current: asyncio.Task | None = None
    first = True
    try:
        while True:
            if not first:
                await asyncio.sleep(60)
            first = False
            record_tick("mediamtx_sync")
            if current is not None and not current.done():
                log.warning(
                    "mediamtx sync: iterasi sebelumnya belum selesai, "
                    "tick ini dilewati"
                )
                continue
            if current is not None:
                # Ambil hasil iterasi lalu supaya exception tidak
                # "never retrieved" (errornya sudah dicatat di
                # _sync_mediamtx_once, jadi di sini cukup ditelan).
                try:
                    current.result()
                except (asyncio.CancelledError, Exception):
                    pass
                current = None
            current = asyncio.create_task(_sync_mediamtx_once())
    except asyncio.CancelledError:
        if current is not None and not current.done():
            await _cancel_and_wait([current], log=log)
        raise


async def lifespan(app: FastAPI):
    settings = get_settings()
    log = logging.getLogger("netravision")
    # Password MediaMTX di database: dibuat sekali bila belum ada,
    # di-cache untuk get_mediamtx(). Harus jalan sebelum loop sync
    # MediaMTX pertama (yang memakai client ber-auth). Bila gagal
    # (mis. migrasi 0028 belum jalan), fallback ke env
    # MEDIAMTX_API_PASSWORD dan sync akan retry tiap 60 detik.
    try:
        from app.services.system_settings import ensure_mediamtx_password  # noqa: PLC0415

        async with get_session_factory()() as _db:
            await ensure_mediamtx_password(_db)
    except Exception:  # noqa: BLE001 - jangan matikan API karena ini
        log.warning(
            "mediamtx_api_password belum bisa dibaca dari DB", exc_info=True
        )
    # Area 5, 5.11: loop tidak start bersamaan; retensi dan disk cleanup
    # yang berat menunda putaran pertamanya beberapa menit supaya tidak
    # membanjiri DB/disk/MediaMTX/Drive tepat saat API baru naik.
    # (Sync MediaMTX dan broadcaster tetap langsung jalan karena
    # dibutuhkan segera; interval semua loop TIDAK berubah.)
    tasks: list[asyncio.Task] = [asyncio.create_task(_status_broadcaster())]

    if settings.posters_enabled:
        if shutil.which("ffmpeg"):
            tasks.append(asyncio.create_task(_poster_loop(initial_delay=10)))
        else:
            log.warning("posters_enabled tapi ffmpeg tak ditemukan, poster mati")

    if settings.retention_enabled:
        tasks.append(asyncio.create_task(_retention_loop(initial_delay=300)))

    if settings.disk_cleanup_enabled:
        tasks.append(asyncio.create_task(_disk_cleanup_loop(initial_delay=180)))

    if settings.drive_enabled:
        tasks.append(asyncio.create_task(_drive_loop(initial_delay=60)))
    else:
        log.info("Google Drive nonaktif (modul opsional)")

    # Mirror folder-link + rclone (multi-tautan): salin segmen stabil ke
    # staging lokal tiap folder yang di-mount rclone. Loop-nya sendiri
    # yang memeriksa ada/tidaknya folder terkonfigurasi.
    from app.services.drive_mirror import mirror_loop

    tasks.append(asyncio.create_task(mirror_loop(initial_delay=20)))

    # Uploader Drive via rclone copyto (tanpa mount): aktif bila koneksi
    # "Hubungkan Google Drive" sudah dipasang. Loop-nya sendiri yang
    # memeriksa status koneksi tiap putaran.
    from app.services.drive_uploader import upload_loop

    tasks.append(asyncio.create_task(upload_loop(initial_delay=45)))

    # Sinkronisasi path kamera ke MediaMTX (hilang saat MediaMTX restart).
    tasks.append(asyncio.create_task(_mediamtx_sync_loop()))

    # Penerus TCP port 53682 untuk `rclone authorize` di Docker: rclone
    # hanya listen di 127.0.0.1, docker-proxy meneruskan ke IP container.
    # Tanpa proxy ini, SSH forward ke host:53682 tidak sampai ke rclone.
    from app.services.gdrive_rclone import authorize_proxy_loop

    tasks.append(asyncio.create_task(authorize_proxy_loop()))

    # Pulihkan token rclone dari DB bila .rclone.conf hilang (mis. container
    # dibuat ulang tanpa volume): akun pulih otomatis tanpa hubungkan ulang.
    try:
        from app.services.gdrive_rclone import restore_remotes_from_db

        async with get_session_factory()() as db:
            restored = await restore_remotes_from_db(db)
        if restored:
            log.info("token rclone dipulihkan dari DB: %s", ", ".join(restored))
    except Exception as e:  # noqa: BLE001 - pulih gagal, lanjut tanpa conf
        log.warning("pulih token rclone dari DB gagal: %s", e)

    try:
        yield
    finally:
        # Area 5, 5.1: TUNGGU semua task latar selesai (batas 30 detik)
        # sebelum dispose engine, supaya upload/commit/hapus yang sedang
        # berjalan tidak terpotong di tengah jalan saat deploy/restart.
        await _cancel_and_wait(tasks, log=log)
        await dispose_engine()


async def _poster_loop(initial_delay: float = 0) -> None:
    from app.services.posters import run_poster_loop

    await run_poster_loop(
        get_settings().poster_interval_sec, initial_delay=initial_delay
    )


async def _retention_loop(initial_delay: float = 0) -> None:
    """Jalankan retensi saat start lalu tiap 24 jam."""
    from app.core.audit import prune_audit_logs
    from app.services.api_access_log_retention import prune_api_access_logs
    from app.services.drive_uploader import prune_drive_upload_traces
    from app.services.recording import apply_retention

    log = logging.getLogger("netravision.retention")
    try:
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            started = time.monotonic()
            record_tick("retention")
            try:
                async with get_session_factory()() as db:
                    n = await apply_retention(db)
                if n:
                    log.info("retensi: %d segmen dihapus", n)
                # 2.2 + 2.12: retensi harian jejak upload dan log audit
                # (keduanya tumbuh tanpa batas bila tidak di-prune).
                # Kegagalan satu tahap tidak menggagalkan tahap lain.
                for _prune, _label in (
                    (prune_drive_upload_traces, "jejak upload"),
                    (prune_audit_logs, "audit"),
                    (prune_api_access_logs, "log akses embed"),
                ):
                    try:
                        async with get_session_factory()() as db:
                            await _prune(db)
                    except Exception as e:  # noqa: BLE001
                        log.warning("retensi %s gagal: %s", _label, e)
                record_success("retention", (time.monotonic() - started) * 1000)
            except Exception as e:  # noqa: BLE001
                log.warning("retensi gagal: %s", e)
                record_failure("retention", e)
            await asyncio.sleep(86400)
    except asyncio.CancelledError:
        pass


async def _disk_cleanup_loop(initial_delay: float = 0) -> None:
    """Bersihkan disk rekaman yang hampir penuh, tiap interval terkonfigurasi.

    Satu putaran gagal tidak boleh mematikan loop. Tiap putaran juga
    membersihkan remote rclone yang penuh (cleanup_rclone_remote per
    remote) dan menjalankan retensi per folder Drive
    (cleanup_folder_retention).

    Area 5, 5.6: tiap TAHAP memakai sesi DB sendiri (dulu satu sesi
    membungkus tiga tahap yang bisa berjalan berjam-jam sambil menahan
    satu koneksi pool), tiap tahap dibatasi jumlah file per putaran, dan
    penghapusan file Drive dikoordinasikan dengan retensi OAuth lewat
    satu lock proses supaya dua loop tidak menghapus file yang sama.
    """
    from app.services.disks import (
        cleanup_folder_retention,
        cleanup_full_disks,
        cleanup_rclone_remote,
    )
    from app.services.gdrive_rclone import list_remote_names

    log = logging.getLogger("netravision.disk_cleanup")
    try:
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            settings = get_settings()
            started = time.monotonic()
            record_tick("disk_cleanup")
            try:
                # Tahap 1: disk lokal, sesi sendiri.
                async with get_session_factory()() as db:
                    n = await cleanup_full_disks(
                        db,
                        settings.recordings_dir,
                        settings.disk_cleanup_threshold_pct,
                        settings.disk_cleanup_target_pct,
                    )
                    if n:
                        log.info("disk cleanup: %d segmen dihapus", n)
                # Tahap 2+3: hapus file DI DRIVE (rclone + retensi
                # folder), di bawah satu lock dengan retensi OAuth di
                # _drive_loop supaya tidak balapan (5.6).
                async with drive_retention_lock():
                    for remote in list_remote_names():
                        try:
                            async with get_session_factory()() as db:
                                rn = await cleanup_rclone_remote(
                                    db,
                                    remote,
                                    settings.disk_cleanup_threshold_pct,
                                    settings.disk_cleanup_target_pct,
                                    max_files=_CLEANUP_MAX_FILES_PER_ROUND,
                                )
                        except Exception as e:  # noqa: BLE001
                            log.warning(
                                "disk cleanup rclone %s gagal: %s", remote, e
                            )
                            continue
                        if rn:
                            log.info(
                                "disk cleanup rclone %s: %d file dihapus",
                                remote,
                                rn,
                            )
                    try:
                        async with get_session_factory()() as db:
                            rfn = await cleanup_folder_retention(
                                db, max_files=_CLEANUP_MAX_FILES_PER_ROUND
                            )
                    except Exception as e:  # noqa: BLE001
                        log.warning("retensi folder gagal: %s", e)
                    else:
                        if rfn:
                            log.info("retensi folder: %d file dihapus", rfn)
                record_success(
                    "disk_cleanup", (time.monotonic() - started) * 1000
                )
            except Exception as e:  # noqa: BLE001
                log.warning("disk cleanup gagal: %s", e)
                record_failure("disk_cleanup", e)
            await asyncio.sleep(max(settings.disk_cleanup_interval_sec, 1))
    except asyncio.CancelledError:
        pass


async def _drive_loop(initial_delay: float = 0) -> None:
    """Upload Drive multi-akun: tiap akun (atau legacy) punya loop sendiri.

    Rescan tiap 5 menit agar segmen yang gagal ikut tercoba lagi dan
    akun yang baru ditambah/dihapus otomatis ter-rekonsiliasi.

    B-S4: retensi Drive (apply_drive_retention, drive_retention_days) juga
    jalan dari loop ini, sekali sehari per akun, bukan tiap putaran scan
    (listing seluruh folder Drive tiap 5 menit terlalu mahal).

    Area 5, 5.7: jadwal retensi dicatat per akun dan hanya setelah
    sukses; gagal = retry dengan backoff, bukan tertunda 24 jam.
    Area 5, 5.1: child loop akun yang dihapus DITUNGGU (bukan hanya
    di-cancel), begitu juga semua child saat loop ini dibatalkan.
    """
    from app.services import drive_accounts as da

    log = logging.getLogger("netravision.drive")
    tasks: dict[str, asyncio.Task] = {}
    retention = _DriveRetentionSchedule()
    try:
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            started = time.monotonic()
            record_tick("drive_loop")
            try:
                async with get_session_factory()() as db:
                    ups = await da.active_uploaders(db)
                removed = [
                    tasks.pop(key) for key in list(tasks) if key not in ups
                ]
                if removed:
                    # Akun dihapus: tunggu loop upload-nya berhenti
                    # dengan aman (batas 10 dtk) sebelum lanjut.
                    await _cancel_and_wait(removed, timeout=10.0, log=log)
                for key, up in ups.items():
                    if key not in tasks:
                        tasks[key] = asyncio.create_task(up.run_upload_loop())
                async with get_session_factory()() as db:
                    for key, up in ups.items():
                        try:
                            n = await up.scan_and_enqueue(db)
                            if n:
                                log.info("drive[%s]: %d segmen diantrekan", key, n)
                        except Exception as e:  # noqa: BLE001
                            log.warning("drive[%s] scan gagal: %s", key, e)
                # Retensi Drive sekali sehari per akun (B-S4), di bawah
                # lock yang sama dengan cleanup Drive di
                # _disk_cleanup_loop supaya tidak balapan (5.6).
                settings = get_settings()
                for key, up in ups.items():
                    if not retention.due(key):
                        continue
                    try:
                        async with drive_retention_lock():
                            n = await asyncio.wait_for(
                                up.apply_drive_retention(
                                    settings.drive_retention_days
                                ),
                                timeout=_DRIVE_RETENTION_TIMEOUT_SEC,
                            )
                        retention.mark_success(key)
                        if n:
                            log.info(
                                "drive[%s]: retensi menghapus %d file",
                                key, n,
                            )
                    except Exception as e:  # noqa: BLE001
                        # Termasuk TimeoutError: jadwalkan ulang dengan
                        # backoff, jangan tunggu 24 jam (5.7).
                        log.warning("drive[%s] retensi gagal: %s", key, e)
                        retention.mark_failure(key)
                record_success("drive_loop", (time.monotonic() - started) * 1000)
            except Exception as e:  # noqa: BLE001
                log.warning("drive loop gagal: %s", e)
                record_failure("drive_loop", e)
            await asyncio.sleep(300)
    except asyncio.CancelledError:
        pass
    finally:
        await _cancel_and_wait(list(tasks.values()), log=log)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    log = logging.getLogger("netravision")

    if settings.app_env == "prod" and settings.jwt_secret == "CHANGE-ME-IN-PROD":
        log.warning("JWT_SECRET masih default, wajib diganti sebelum produksi!")

    # 4.18: dokumentasi API (/docs, /redoc, /openapi.json) mati secara
    # default; hanya nyala bila API_DOCS_ENABLED=true. Dampak publik
    # terbatas (Apache hanya mem-proxy /api/, /ws, /whep/, /hls/), tapi
    # siapa pun dengan akses lokal/SSH sebelumnya bisa membaca seluruh
    # skema endpoint dari 127.0.0.1:8100/docs.
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Hardening Fase 4: security_headers -> metrics -> audit (urutan eksekusi).
    # add_middleware yang dipanggil terakhir = paling luar = jalan duluan,
    # jadi urutan tambah di bawah ini dibalik dari urutan eksekusi.
    app.add_middleware(audit.AuditMiddleware)
    app.add_middleware(metrics.MetricsMiddleware)
    app.add_middleware(security_headers.SecurityHeadersMiddleware)
    # Path /api/* dipertahankan persis seperti v2.0 (kontrak embed tidak rusak).
    app.include_router(system.router, prefix="/api")
    app.include_router(metrics.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(streams.router, prefix="/api")
    # /admin/disks (admin_disks) dan /admin/disk-summary (admin_streams)
    # adalah dua endpoint berbeda; tidak ada rute yang saling membayangi.
    app.include_router(admin_disks.router, prefix="/api")
    app.include_router(admin_streams.router, prefix="/api")
    app.include_router(admin_scan.router, prefix="/api")
    app.include_router(admin_users.router, prefix="/api")
    app.include_router(admin_keys.router, prefix="/api")
    app.include_router(admin_audit.router, prefix="/api")
    app.include_router(admin_ads.router, prefix="/api")
    app.include_router(admin_ads.admin_router, prefix="/api")
    # Akun Google Drive multi-akun (callback OAuth publik, sisanya admin).
    app.include_router(admin_drive.router, prefix="/api")
    app.include_router(admin_drive.admin_router, prefix="/api")
    # Embed pihak ketiga, kontrak FROZEN, tanpa login user (auth via API key).
    app.include_router(external.router, prefix="/api")
    # Rekaman: 8 endpoint persis kontrak v2.0.
    app.include_router(recordings.router, prefix="/api")
    # Penyelesaian lokasi multi-format (kolom "Lokasi").
    app.include_router(maps.router, prefix="/api")
    # Proxy media ber-auth (K-1): WHEP/HLS hanya lewat API.
    app.include_router(media.router, prefix="/api")
    # /ws TANPA prefix /api (kontrak).
    app.include_router(ws.router)
    # File statis untuk gambar iklan yang diunggah.
    # Prefix /api agar lewat reverse-proxy Apache yang sama seperti /api/* (v2: /api/static/ads/...).
    from fastapi.staticfiles import StaticFiles

    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    app.mount("/api/uploads", StaticFiles(directory="data/uploads"), name="uploads")
    return app


app = create_app()
