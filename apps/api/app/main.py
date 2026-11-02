"""App factory: create_app(). JSON logging, CORS, mount router /api."""

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import dispose_engine, get_session_factory
from app.routers import (
    admin_ads,
    admin_keys,
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


@asynccontextmanager
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
    from app.services.drive import DriveUploader

    log = logging.getLogger("netravision.drive")
    try:
        up = DriveUploader()
        try:
            async with get_session_factory()() as db:
                n = await up.scan_and_enqueue(db)
            if n:
                log.info("drive: %d segmen diantrekan", n)
        except Exception as e:  # noqa: BLE001
            log.warning("drive scan awal gagal: %s", e)
        await up.run_upload_loop()
    except asyncio.CancelledError:
        pass


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
    # Path /api/* dipertahankan persis seperti v2.0 (kontrak embed tidak rusak).
    app.include_router(system.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(streams.router, prefix="/api")
    app.include_router(admin_streams.router, prefix="/api")
    app.include_router(admin_users.router, prefix="/api")
    app.include_router(admin_keys.router, prefix="/api")
    app.include_router(admin_ads.router, prefix="/api")
    app.include_router(admin_ads.admin_router, prefix="/api")
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
