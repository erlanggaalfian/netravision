"""App factory: create_app(). JSON logging, CORS, mount router /api."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import dispose_engine
from app.routers import auth, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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
    return app


app = create_app()
