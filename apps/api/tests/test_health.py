"""Test GET /api/health (DB + MediaMTX di-mock)."""

import pytest
from httpx import ASGITransport, AsyncClient

import app.routers.system as system_mod
from app.main import create_app


async def _ok_db():
    return {"name": "database", "status": "ok", "latency_ms": 1.2}


async def _ok_mtx():
    return {"name": "mediamtx", "status": "ok", "latency_ms": 3.4}


async def _bad_mtx():
    return {"name": "mediamtx", "status": "error", "detail": "unreachable"}


@pytest.fixture
def app():
    return create_app()


async def test_health_ok(monkeypatch, app):
    monkeypatch.setattr(system_mod, "check_database", _ok_db)
    monkeypatch.setattr(system_mod, "check_mediamtx", _ok_mtx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["mediamtx"]["status"] == "ok"
    assert body["version"]


async def test_health_degraded_when_mediamtx_down(monkeypatch, app):
    monkeypatch.setattr(system_mod, "check_database", _ok_db)
    monkeypatch.setattr(system_mod, "check_mediamtx", _bad_mtx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["components"]["mediamtx"]["status"] == "error"
