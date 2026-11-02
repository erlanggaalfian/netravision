"""GET /api/health — status komponen (DB + MediaMTX)."""

import time

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_session_factory

router = APIRouter(tags=["system"])


async def check_database() -> dict:
    started = time.perf_counter()
    try:
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        ms = round((time.perf_counter() - started) * 1000, 1)
        return {"name": "database", "status": "ok", "latency_ms": ms}
    except Exception as e:  # noqa: BLE001 — health tidak boleh raise
        return {"name": "database", "status": "error", "detail": str(e)[:200]}


async def check_mediamtx() -> dict:
    started = time.perf_counter()
    url = f"{get_settings().mediamtx_api_url.rstrip('/')}/v3/config/global/get"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
        ms = round((time.perf_counter() - started) * 1000, 1)
        if resp.status_code < 500:
            return {"name": "mediamtx", "status": "ok", "latency_ms": ms}
        return {"name": "mediamtx", "status": "error", "detail": f"http {resp.status_code}"}
    except Exception as e:  # noqa: BLE001
        return {"name": "mediamtx", "status": "error", "detail": str(e)[:200]}


@router.get("/health")
async def health() -> dict:
    """Kesehatan API + dependensinya. Dipakai update.sh dan monitoring."""
    settings = get_settings()
    database = await check_database()
    mediamtx = await check_mediamtx()
    components = {"database": database, "mediamtx": mediamtx}
    overall = "ok" if all(c["status"] == "ok" for c in components.values()) else "degraded"
    return {
        "status": overall,
        "service": settings.app_name,
        "version": settings.app_version,
        "components": components,
    }
