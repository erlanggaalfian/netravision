"""Test subnet scan (CIDR) async, tanpa network asli (mock rtsp_discovery).

Alur async: POST /admin/scan-subnet langsung kembalikan 202 + job_id,
pemindaian jalan di background; hasil diambil lewat polling
GET /admin/scan-subnet/{job_id} sampai status done.
"""

import asyncio
import time

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.routers import admin_scan
from app.services import rtsp_discovery
from app.services.rtsp_discovery import DiscoveryResult, PathResult, VideoProbe
from tests.conftest import auth_as, make_user

def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

@pytest_asyncio.fixture
async def scan_client(app_client):
    """app_client + router scan-subnet (main.py belum me-mount-nya)."""
    app, mtmx, db = app_client
    app.include_router(admin_scan.router, prefix="/api")
    # Isolasi antar-test: job store di memori proses bertahan lintas test.
    admin_scan._jobs.clear()
    return app, mtmx, db

async def _login_admin(scan_client):
    app, _, db = scan_client
    # Router scan-subnet hanya untuk super_admin (E-K1).
    admin = make_user(role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    return app

async def _poll_done(c, job_id, timeout=10.0):
    """Polling GET job sampai done/error, kembalikan body terakhir."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        r = await c.get(f"/api/admin/scan-subnet/{job_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("done", "error"):
            return body
        assert asyncio.get_running_loop().time() < deadline, (
            f"job scan {job_id} tak selesai dalam {timeout} detik"
        )
        await asyncio.sleep(0.05)

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
    # Funnel 3 tahap: .10 lolos tahap 1 (reachable) dan tahap 2 (port
    # RTSP terbuka); host lain tersaring di tahap 1 tanpa discovery.
    monkeypatch.setattr(admin_scan, "_host_reachable", fake_alive)
    monkeypatch.setattr(admin_scan, "_port_open", fake_alive)

    async with _client(app) as c:
        t0 = time.monotonic()
        r = await c.post(
            "/api/admin/scan-subnet",
            json={
                "ip_range": "192.168.1.8/29",  # 6 host (.9-.14), termasuk .10
                "port": 554,
                "username": "admin",
                "password": "pw",
            },
        )
        # POST async: langsung 202 + job_id, tanpa menunggu scan selesai.
        assert time.monotonic() - t0 < 2.0, "POST harus kembali cepat (<2 detik)"
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        assert job_id
        body = await _poll_done(c, job_id)
        assert body["status"] == "done"
        assert body["total"] == 6
        assert body["scanned"] == 6
        assert body["error"] is None
        # Progres funnel: 1 lolos tahap 1, 1 lolos tahap 2, selesai.
        assert body["stage"] == "done"
        assert body["reachable_count"] == 1
        assert body["port_open_count"] == 1
        hosts = body["hosts"]
        # A-R6: host unreachable tetap muncul di hasil (bukan disaring).
        assert len(hosts) == 6
        by_host = {h["host"]: h for h in hosts}
        h = by_host["192.168.1.10"]
        assert h["port"] == 554
        assert h["status"] == "video"
        assert h["best_main"].endswith("/H.264")
        assert h["best_sub"] is None
        assert all(
            by_host[f"192.168.1.{n}"]["status"] == "unreachable"
            for n in (9, 11, 12, 13, 14)
        )
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
    # Funnel: semua host lolos tahap 1 dan 2, jadi sampai discovery
    # dan gagal di sana (auth_failed), bukan tersaring di funnel.
    monkeypatch.setattr(admin_scan, "_host_reachable", fake_alive)
    monkeypatch.setattr(admin_scan, "_port_open", fake_alive)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={"ip_range": "192.168.7.0/30"},  # 2 host
        )
        assert r.status_code == 202, r.text
        body = await _poll_done(c, r.json()["job_id"])
        assert body["status"] == "done"
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


async def test_scan_subnet_job_tidak_ditemukan(scan_client):
    """GET job_id yang tidak ada (atau sudah dihapus) -> 404."""
    app = await _login_admin(scan_client)
    async with _client(app) as c:
        r = await c.get("/api/admin/scan-subnet/tidak-ada")
        assert r.status_code == 404, r.text


async def test_scan_subnet_funnel_tiga_tahap(scan_client, monkeypatch):
    """Funnel: host mati tersaring tahap 1, port tertutup tersaring
    tahap 2, hanya host lolos keduanya yang sampai discovery."""
    app = await _login_admin(scan_client)
    # Subnet 192.168.1.8/29 -> 6 host (.9-.14).
    reachable = {"192.168.1.10", "192.168.1.11", "192.168.1.12"}
    port_open = {"192.168.1.10", "192.168.1.12"}
    discovered: list[str] = []

    async def fake_reachable(host: str, port: int) -> bool:
        return host in reachable

    async def fake_port_open(host: str, port: int) -> bool:
        assert host in reachable, (
            f"tahap 2 dipanggil untuk {host} yang gagal tahap 1"
        )
        return host in port_open

    async def fake_discover(host: str, port: int = 554,
                            user=None, password=None, channel: int = 1):
        discovered.append(host)
        assert host in port_open, (
            f"discovery dipanggil untuk {host} yang gagal tahap 2"
        )
        if host == "192.168.1.10":
            path = PathResult(
                path="/H.264", url=f"rtsp://{host}:{port}/H.264",
                status="video", codec="h264",
                width=1920, height=1080, fps=25.0,
            )
            return DiscoveryResult(
                host=host, port=port, reachable=True, paths=[path],
                best_main=path.url, best_sub=None,
            )
        # .12 hidup + port terbuka, tapi auth gagal di discovery.
        path = PathResult(
            path="/H.264", url=f"rtsp://{host}:{port}/H.264",
            status="auth_failed",
        )
        return DiscoveryResult(
            host=host, port=port, reachable=True, paths=[path],
        )

    monkeypatch.setattr(admin_scan, "_host_reachable", fake_reachable)
    monkeypatch.setattr(admin_scan, "_port_open", fake_port_open)
    monkeypatch.setattr(rtsp_discovery, "discover_host", fake_discover)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={"ip_range": "192.168.1.8/29", "port": 554},
        )
        assert r.status_code == 202, r.text
        body = await _poll_done(c, r.json()["job_id"])
        assert body["status"] == "done"
        assert body["total"] == 6
        assert body["scanned"] == 6
        assert body["stage"] == "done"
        assert body["reachable_count"] == 3
        assert body["port_open_count"] == 2
        by_host = {h["host"]: h for h in body["hosts"]}
        assert len(body["hosts"]) == 6
        assert by_host["192.168.1.10"]["status"] == "video"
        assert by_host["192.168.1.12"]["status"] == "auth_failed"
        # Tahap 2 gagal -> status baru port_closed, tetap di hasil.
        assert by_host["192.168.1.11"]["status"] == "port_closed"
        assert by_host["192.168.1.11"]["paths"] == []
        # Tahap 1 gagal -> unreachable.
        assert all(
            by_host[f"192.168.1.{n}"]["status"] == "unreachable"
            for n in (9, 13, 14)
        )
        # Discovery hanya dipanggil untuk 2 host yang lolos funnel.
        assert discovered == ["192.168.1.10", "192.168.1.12"] or set(
            discovered
        ) == {"192.168.1.10", "192.168.1.12"}
        assert len(discovered) == 2
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["host"] == "192.168.1.10"


async def test_scan_subnet_tahap1_fallback_tcp_kamera_blokir_ping(
    scan_client, monkeypatch
):
    """Kamera yang memblokir ICMP (ping selalu diam) tetap lolos tahap
    1 lewat fallback TCP ke port RTSP, lalu sampai discovery."""
    app = await _login_admin(scan_client)

    async def fake_ping(host: str, timeout: float = 1.0) -> bool:
        return False  # semua host memblokir ICMP

    async def fake_tcp(host: str, port: int, timeout: float) -> bool:
        # Hanya .10:554 yang menjawab; port 80 semua host diam.
        return host == "192.168.1.10" and port == 554

    async def fake_discover(host: str, port: int = 554,
                            user=None, password=None, channel: int = 1):
        path = PathResult(
            path="/live", url=f"rtsp://{host}:{port}/live",
            status="video", codec="h264",
            width=1280, height=720, fps=25.0,
        )
        return DiscoveryResult(
            host=host, port=port, reachable=True, paths=[path],
            best_main=path.url, best_sub=None,
        )

    monkeypatch.setattr(admin_scan, "_ping_alive", fake_ping)
    monkeypatch.setattr(admin_scan, "_tcp_connect", fake_tcp)
    monkeypatch.setattr(rtsp_discovery, "discover_host", fake_discover)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={"ip_range": "192.168.1.8/30", "port": 554},  # .9, .10
        )
        assert r.status_code == 202, r.text
        body = await _poll_done(c, r.json()["job_id"])
        assert body["status"] == "done"
        assert body["reachable_count"] == 1
        assert body["port_open_count"] == 1
        by_host = {h["host"]: h for h in body["hosts"]}
        assert by_host["192.168.1.10"]["status"] == "video"
        assert by_host["192.168.1.9"]["status"] == "unreachable"
        assert len(body["candidates"]) == 1
