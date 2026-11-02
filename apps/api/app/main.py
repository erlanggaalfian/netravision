"""App factory: create_app(). JSON logging, CORS, mount router /api."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import dispose_engine, get_session_factory
from app.routers import admin_streams, auth, streams, system, ws


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
    broadcaster = asyncio.create_task(_status_broadcaster())
    try:
        yield
    finally:
        broadcaster.cancel()
        await dispose_engine()


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
    # /ws TANPA prefix /api (kontrak).
    app.include_router(ws.router)
    return app


app = create_app()
