"""App factory: create_app(). JSON logging, CORS, mount router /api."""

import asyncio
import logging
import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core import audit, metrics, security_headers
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import dispose_engine, get_session_factory
from app.routers import (
    admin_ads,
    admin_drive,
    admin_keys,
    admin_scan,
    admin_streams,
    admin_users,
    auth,
    external,
    recordings,
    streams,
    system,
    ws,
)


async def _status_broadcaster() -> None:
    """Tiap 10 detik: poll status kamera, broadcast perubahan ke klien /ws."""
    from app.services.camera_status import poll_once
    from app.services.mediamtx import get_mediamtx

    log = logging.getLogger("netravision.ws")
    mediamtx = get_mediamtx()
    try:
        while True:
            await asyncio.sleep(10)
            try:
                async with get_session_factory()() as db:
                    changes = await poll_once(db, mediamtx)
                if changes:
                    await ws.manager.broadcast({"type": "status", "changes": changes})
            except Exception as e:  # satu poll gagal tidak boleh mematikan loop
                log.warning("broadcaster gagal: %s", e)
    except asyncio.CancelledError:
        pass
    finally:
        await mediamtx.aclose()


async def _mediamtx_sync_loop() -> None:
    """Sinkronisasi path kamera ke MediaMTX: saat start + tiap 60 detik.

    Path MediaMTX bersifat dinamis (tidak tersimpan) — bila MediaMTX restart,
    semua path hilang. Loop ini mendaftarkan ulang semua kamera aktif dan
    menghapus path milik kamera yang sudah dihapus/dinonaktifkan.
    """
    from app.services.mediamtx import get_mediamtx

    log = logging.getLogger("netravision.mediamtx_sync")
    first = True
    while True:
        if not first:
            await asyncio.sleep(60)
        first = False
        try:
            from sqlalchemy import select

            from app.db import get_session_factory
            from app.models.streams import Stream

            factory = get_session_factory()
            async with factory() as db:
                result = await db.execute(
                    select(Stream).where(Stream.is_active.is_(True)))
                streams = list(result.scalars().all())
            mediamtx = get_mediamtx()
            try:
                paths = await mediamtx.get_paths()
                existing = {p.get("name") for p in paths if isinstance(p, dict)}
            except Exception:  # noqa: BLE001 - MediaMTX down, coba lagi nanti
                continue
            from app.services.stream_paths import register_stream

            wanted: set[str] = set()
            for s in streams:
                wanted.update({f"stream_{s.id}", f"stream_{s.id}_sub"})
                try:
                    await register_stream(
                        mediamtx, s.id, s.main_url or s.rtsp_url or "",
                        bool(s.recording_enabled))
                except Exception as e:  # noqa: BLE001
                    log.warning("sync path stream_%s gagal: %s", s.id, e)
            # Hapus path yatim (kamera dihapus/dinonaktifkan).
            for name in existing - wanted:
                if name.startswith("stream_"):
                    try:
                        await mediamtx.delete_path(name)
                    except Exception:  # noqa: BLE001
                        pass
            await mediamtx.aclose()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("mediamtx sync loop error: %s", e)


async def lifespan(app: FastAPI):
    settings = get_settings()
    log = logging.getLogger("netravision")
    tasks: list[asyncio.Task] = [asyncio.create_task(_status_broadcaster())]

    if settings.posters_enabled:
        if shutil.which("ffmpeg"):
            tasks.append(asyncio.create_task(_poster_loop()))
        else:
            log.warning("posters_enabled tapi ffmpeg tak ditemukan — poster mati")

    if settings.retention_enabled:
        tasks.append(asyncio.create_task(_retention_loop()))

    if settings.drive_enabled:
        tasks.append(asyncio.create_task(_drive_loop()))
    else:
        log.info("Google Drive nonaktif (modul opsional)")

    # Mirror folder-link + rclone (multi-tautan): salin segmen stabil ke
    # staging lokal tiap folder yang di-mount rclone. Loop-nya sendiri
    # yang memeriksa ada/tidaknya folder terkonfigurasi.
    from app.services.drive_mirror import mirror_loop

    tasks.append(asyncio.create_task(mirror_loop()))

    # Uploader Drive via rclone copyto (tanpa mount): aktif bila koneksi
    # "Hubungkan Google Drive" sudah dipasang. Loop-nya sendiri yang
    # memeriksa status koneksi tiap putaran.
    from app.services.drive_uploader import upload_loop

    tasks.append(asyncio.create_task(upload_loop()))

    # Sinkronisasi path kamera ke MediaMTX (hilang saat MediaMTX restart).
    tasks.append(asyncio.create_task(_mediamtx_sync_loop()))

    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await dispose_engine()


async def _poster_loop() -> None:
    from app.services.posters import run_poster_loop

    await run_poster_loop(get_settings().poster_interval_sec)


async def _retention_loop() -> None:
    """Jalankan retensi saat start lalu tiap 24 jam."""
    from app.services.recording import apply_retention

    log = logging.getLogger("netravision.retention")
    try:
        while True:
            try:
                async with get_session_factory()() as db:
                    n = await apply_retention(db)
                if n:
                    log.info("retensi: %d segmen dihapus", n)
            except Exception as e:  # noqa: BLE001
                log.warning("retensi gagal: %s", e)
            await asyncio.sleep(86400)
    except asyncio.CancelledError:
        pass


async def _drive_loop() -> None:
    """Upload Drive multi-akun: tiap akun (atau legacy) punya loop sendiri.

    Rescan tiap 5 menit agar segmen yang gagal ikut tercoba lagi dan
    akun yang baru ditambah/dihapus otomatis ter-rekonsiliasi.
    """
    from app.services import drive_accounts as da

    log = logging.getLogger("netravision.drive")
    tasks: dict[str, asyncio.Task] = {}
    try:
        while True:
            try:
                async with get_session_factory()() as db:
                    ups = await da.active_uploaders(db)
                for key in list(tasks):
                    if key not in ups:
                        tasks.pop(key).cancel()
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
            except Exception as e:  # noqa: BLE001
                log.warning("drive loop gagal: %s", e)
            await asyncio.sleep(300)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks.values():
            t.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    log = logging.getLogger("netravision")

    if settings.app_env == "prod" and settings.jwt_secret == "CHANGE-ME-IN-PROD":
        log.warning("JWT_SECRET masih default — wajib diganti sebelum produksi!")

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
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
    app.include_router(admin_streams.router, prefix="/api")
    app.include_router(admin_scan.router, prefix="/api")
    app.include_router(admin_users.router, prefix="/api")
    app.include_router(admin_keys.router, prefix="/api")
    app.include_router(admin_ads.router, prefix="/api")
    app.include_router(admin_ads.admin_router, prefix="/api")
    # Akun Google Drive multi-akun (callback OAuth publik, sisanya admin).
    app.include_router(admin_drive.router, prefix="/api")
    app.include_router(admin_drive.admin_router, prefix="/api")
    # Embed pihak ketiga — kontrak FROZEN, tanpa login user (auth via API key).
    app.include_router(external.router, prefix="/api")
    # Rekaman: 8 endpoint persis kontrak v2.0.
    app.include_router(recordings.router, prefix="/api")
    # /ws TANPA prefix /api (kontrak).
    app.include_router(ws.router)
    # File statis untuk gambar iklan yang diunggah.
    from fastapi.staticfiles import StaticFiles

    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="data/uploads"), name="uploads")
    return app


app = create_app()
