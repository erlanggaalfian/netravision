"""Test subnet scan (CIDR) — tanpa network asli (mock rtsp_discovery)."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.routers import admin_scan
from app.services import rtsp_discovery
from app.services.rtsp_discovery import VideoProbe
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
    """Hanya .10 hidup dengan video di /H.264; host lain tak terjangkau."""
    app = await _login_admin(scan_client)

    async def fake_alive(host: str, port: int) -> bool:
        return host == "192.168.1.10"

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        return "open" if url.endswith("/H.264") else "not_found"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        return VideoProbe(status="video", codec="h264",
                          width=800, height=448, fps=25.0, gop_seconds=2.0)

    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={
                "ip_range": "192.168.1.8/29",  # 6 host (.9-.14), termasuk .10
                "port": 554,
                "username": "admin",
                "password": "pw",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        hosts = body["hosts"]
        assert len(hosts) == 1
        h = hosts[0]
        assert h["host"] == "192.168.1.10"
        assert h["port"] == 554
        assert h["status"] == "video"
        assert h["best_main"].endswith("/H.264")
        assert h["best_sub"] is None
        # Kompatibilitas lama: candidates berisi best_main per host.
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["main_url"] == h["best_main"]


async def test_scan_subnet_host_gagal_tetap_dikembalikan(scan_client, monkeypatch):
    """Host hidup tapi semua path gagal -> tetap dilaporkan beserta alasannya."""
    app = await _login_admin(scan_client)

    async def fake_alive(host: str, port: int) -> bool:
        return True

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        return "auth_failed"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        raise AssertionError("tidak boleh ffprobe saat auth gagal")

    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={"ip_range": "192.168.7.0/30"},  # 2 host
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["hosts"]) == 2
        assert all(h["status"] == "auth_failed" for h in body["hosts"])
        assert all(h["best_main"] is None for h in body["hosts"])
        assert body["candidates"] == []


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
