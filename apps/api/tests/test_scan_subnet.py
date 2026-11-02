"""Test subnet scan (CIDR) — tanpa network asli (mock)."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.routers import admin_scan
from app.services.stream_resolver import StreamResolution
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def scan_client(app_client):
    """app_client + router scan-subnet (main.py belum me-mount-nya)."""
    app, mtmx, db = app_client
    app.include_router(admin_scan.router, prefix="/api")
    return app, mtmx, db


async def _login_admin(scan_client):
    app, _, db = scan_client
    admin = make_user()
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    return app


async def test_scan_subnet_cidr_invalid(scan_client):
    app = await _login_admin(scan_client)
    async with _client(app) as c:
        r = await c.post("/api/admin/scan-subnet", json={"ip_range": "bukan-cidr"})
        assert r.status_code == 400, r.text
        assert "CIDR" in r.json()["detail"]


async def test_scan_subnet_lebih_dari_256_ditolak(scan_client):
    app = await _login_admin(scan_client)
    async with _client(app) as c:
        r = await c.post("/api/admin/scan-subnet", json={"ip_range": "10.0.0.0/16"})
        assert r.status_code == 400, r.text
        assert "256" in r.json()["detail"]


async def test_scan_subnet_mock_tanpa_network(scan_client, monkeypatch):
    app = await _login_admin(scan_client)

    async def fake_tcp_alive(host: str, port: int) -> bool:
        return host == "192.168.1.10"

    async def fake_resolve_stream(**kw):
        return StreamResolution(
            main_url=f"rtsp://{kw['user']}:x@{kw['host']}:{kw['port']}/h264",
            sub_url=None,
            brand=kw["brand"],
            method="brand",
        )

    monkeypatch.setattr(admin_scan, "_tcp_alive", fake_tcp_alive)
    monkeypatch.setattr(admin_scan, "resolve_stream", fake_resolve_stream)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={
                "ip_range": "192.168.1.8/29",  # 6 host (.9-.14), termasuk .10
                "port": 554,
                "username": "admin",
                "password": "pw",
                "brand": "hikvision",
            },
        )
        assert r.status_code == 200, r.text
        cands = r.json()["candidates"]
        assert len(cands) == 1
        assert cands[0]["host"] == "192.168.1.10"
        assert cands[0]["port"] == 554
        assert cands[0]["brand"] == "hikvision"
        assert "192.168.1.10" in cands[0]["main_url"]


async def test_scan_subnet_auto_coba_multi_brand(scan_client, monkeypatch):
    app = await _login_admin(scan_client)

    async def fake_tcp_alive(host: str, port: int) -> bool:
        return True

    async def fake_resolve_stream(**kw):
        return StreamResolution(
            main_url=f"rtsp://{kw['host']}/ch",
            sub_url=None,
            brand=kw["brand"],
            method="brand",
        )

    monkeypatch.setattr(admin_scan, "_tcp_alive", fake_tcp_alive)
    monkeypatch.setattr(admin_scan, "resolve_stream", fake_resolve_stream)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={"ip_range": "192.168.7.0/30", "brand": "auto"},  # 2 host
        )
        assert r.status_code == 200, r.text
        cands = r.json()["candidates"]
        # 2 host x 5 brand auto = 10 kandidat
        assert len(cands) == 10
        assert {c["brand"] for c in cands} == set(admin_scan._AUTO_BRANDS)


async def test_scan_subnet_butuh_admin(scan_client):
    app, _, db = scan_client
    user = make_user(id=2, username="biasa", role="user")
    db.add(user)
    await db.commit()
    auth_as(app, user)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet", json={"ip_range": "192.168.1.0/30"}
        )
        assert r.status_code == 403, r.text
