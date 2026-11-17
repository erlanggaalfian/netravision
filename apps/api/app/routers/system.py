"""GET /api/health — status komponen (DB + MediaMTX)."""

import logging
import time

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.db.session import get_session_factory
from app.services.loop_health import snapshot as loop_snapshot

router = APIRouter(tags=["system"])

# A-1.5: cache hasil beberapa detik supaya flood health tidak membuka
# sesi DB + HTTP MediaMTX baru di tiap panggilan.
_HEALTH_CACHE_TTL = 5.0
_health_cache: dict = {"at": 0.0, "body": None, "status_code": 200}


def reset_health_cache() -> None:
    """Kosongkan cache health (dipakai test agar antar-test terisolasi)."""
    _health_cache["at"] = 0.0
    _health_cache["body"] = None
    _health_cache["status_code"] = 200


async def check_database() -> dict:
    started = time.perf_counter()
    try:
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        ms = round((time.perf_counter() - started) * 1000, 1)
        return {"name": "database", "status": "ok", "latency_ms": ms}
    except Exception as e:  # noqa: BLE001 — health tidak boleh raise
        # Detail internal (pesan koneksi DB) hanya ke log server;
        # respons publik hanya kode generik (S-6).
        log = logging.getLogger("netravision.health")
        log.warning("health database gagal: %s", e)
        return {"name": "database", "status": "error", "detail": "database_error"}


async def check_mediamtx() -> dict:
    started = time.perf_counter()
    settings = get_settings()
    url = f"{settings.mediamtx_api_url.rstrip('/')}/v3/config/global/get"
    try:
        # 4.11: kirim kredensial control API bila dikonfigurasi
        # (MEDIAMTX_API_USER/PASSWORD); tanpa ini health selalu
        # "degraded" begitu MediaMTX diproteksi.
        auth = (
            (settings.mediamtx_api_user, settings.mediamtx_api_password)
            if settings.mediamtx_api_user and settings.mediamtx_api_password
            else None
        )
        async with httpx.AsyncClient(
            timeout=3.0, trust_env=False, auth=auth
        ) as client:
            resp = await client.get(url)
        ms = round((time.perf_counter() - started) * 1000, 1)
        # A-S11: hanya 2xx yang sehat; 4xx/5xx (salah konfigurasi,
        # path tidak ada) harus dilaporkan tidak sehat.
        if 200 <= resp.status_code < 300:
            return {"name": "mediamtx", "status": "ok", "latency_ms": ms}
        return {"name": "mediamtx", "status": "error", "detail": f"http {resp.status_code}"}
    except Exception as e:  # noqa: BLE001
        log = logging.getLogger("netravision.health")
        log.warning("health mediamtx gagal: %s", e)
        return {"name": "mediamtx", "status": "error", "detail": "mediamtx_error"}


@router.get("/health", dependencies=[Depends(rate_limited(30, 60))])
async def health() -> JSONResponse:
    """Kesehatan API + dependensinya. Dipakai update.sh dan monitoring.

    A-1.5: sebelumnya tanpa auth/rate limit, selalu 200 walau komponen
    error, dan tiap panggilan membuka sesi DB + HTTP MediaMTX baru.
    Kini: rate limit 30/menit per IP, hasil di-cache 5 detik, dan
    komponen yang gagal dijawab 503 supaya load balancer/monitoring
    melihat kegagalan lewat status HTTP, bukan hanya field body.
    """
    now = time.monotonic()
    if _health_cache["body"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
        return JSONResponse(
            content=_health_cache["body"],
            status_code=_health_cache["status_code"],
        )
    settings = get_settings()
    database = await check_database()
    mediamtx = await check_mediamtx()
    components = {"database": database, "mediamtx": mediamtx}
    overall = "ok" if all(c["status"] == "ok" for c in components.values()) else "degraded"
    body = {
        "status": overall,
        "service": settings.app_name,
        "version": settings.app_version,
        "components": components,
        # Area 5, 5.8: denyut loop latar (last_tick_at, last_success_at,
        # consecutive_failures) supaya loop yang macet/mati diam-diam
        # terlihat operator. Aditif: tidak mengubah status/kontrak.
        "loops": loop_snapshot(),
    }
    status_code = 200 if overall == "ok" else 503
    _health_cache["at"] = now
    _health_cache["body"] = body
    _health_cache["status_code"] = status_code
    return JSONResponse(content=body, status_code=status_code)
