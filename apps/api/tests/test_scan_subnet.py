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
                            user=None, password=None, channel: int = 1,
                            known_paths=None):
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
                            user=None, password=None, channel: int = 1,
                            known_paths=None):
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


async def test_discover_host_ffprobe_paralel_dan_dibatasi(monkeypatch):
    """ffprobe paralel (2/host) + dibatasi 8 path open pertama.

    12 path open, tiap ffprobe tidur 0,5 dtk: serial butuh 8 x 0,5 =
    4,0 dtk (dan tanpa batas 12 x 0,5 = 6,0 dtk); paralel 2 butuh
    ~2,0 dtk dan hanya 8 panggilan. Main = resolusi terbesar, sub =
    yang terkecil."""
    from app.services.rtsp_discovery import candidate_paths

    first12 = set(candidate_paths()[:12])
    calls: list[str] = []

    async def fake_alive(host: str, port: int) -> bool:
        return True

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        return "open" if path in first12 else "not_found"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        calls.append(url)
        await asyncio.sleep(0.5)
        # Path pertama paling besar (main), kedua paling kecil (sub).
        if url.endswith("/Streaming/Channels/101"):
            w, h = 1920, 1080
        elif url.endswith("/Streaming/Channels/102"):
            w, h = 640, 360
        else:
            w, h = 1280, 720
        return VideoProbe(status="video", codec="h264",
                          width=w, height=h, fps=25.0, gop_seconds=2.0)

    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)

    t0 = time.monotonic()
    disc = await rtsp_discovery.discover_host("192.168.1.10", 554,
                                              "admin", "pw")
    elapsed = time.monotonic() - t0
    # Paralel 2: 8 panggilan x 0,5 dtk / 2 = ~2,0 dtk (batas longgar
    # 3,2 dtk supaya stabil saat mesin sibuk; serial butuh 4,0 dtk).
    assert elapsed < 3.2, f"ffprobe masih serial? {elapsed:.2f} dtk"
    assert len(calls) == 8, f"tanpa batas 8, ffprobe dipanggil {len(calls)}x"
    assert disc.best_main is not None
    assert disc.best_main.endswith("/Streaming/Channels/101")
    assert disc.best_sub is not None
    assert disc.best_sub.endswith("/Streaming/Channels/102")


async def test_discover_host_jalur_cepat_kamera_dikenal(monkeypatch):
    """Kamera dikenal (path main terdaftar terbuka di DESCRIBE) ->
    video tanpa ffprobe sama sekali; bila path dikenal tidak terbuka,
    discovery penuh seperti biasa."""
    calls: list[str] = []

    async def fake_alive(host: str, port: int) -> bool:
        return True

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        return "open" if url.endswith("/H.264") else "not_found"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        calls.append(url)
        return VideoProbe(status="video", codec="h264",
                          width=1920, height=1080, fps=25.0)

    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)

    # Jalur cepat: /H.264 dikenal + terbuka -> tanpa ffprobe.
    disc = await rtsp_discovery.discover_host(
        "192.168.1.10", 554, "admin", "pw",
        known_paths=("/H.264", None))
    assert disc.best_main is not None
    assert disc.best_main.endswith("/H.264")
    assert disc.best_sub is None
    assert calls == [], "jalur cepat tidak boleh memanggil ffprobe"

    # Path dikenal tidak terbuka -> discovery penuh (ffprobe jalan).
    disc2 = await rtsp_discovery.discover_host(
        "192.168.1.10", 554, "admin", "pw",
        known_paths=("/tidak-ada", None))
    assert disc2.best_main is not None
    assert disc2.best_main.endswith("/H.264")
    assert len(calls) == 1, "fallback harus memverifikasi via ffprobe"


async def test_discover_host_tandai_role_main_sub_resolusi_sama(monkeypatch):
    """Resolusi seri -> nama path yang membedakan: /stream1 = main,
    /stream2 = sub, role ditandai di PathResult dan best_* terisi."""
    async def fake_alive(host: str, port: int) -> bool:
        return True

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        return "open" if url.endswith(("/stream1", "/stream2")) else "not_found"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        # Kamera menjawab kedua path dengan stream yang SAMA.
        return VideoProbe(status="video", codec="h264",
                          width=1920, height=1080, fps=25.0, gop_seconds=2.0)

    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)

    disc = await rtsp_discovery.discover_host("192.168.1.10", 554, "admin", "pw")
    assert disc.best_main is not None
    assert disc.best_main.endswith("/stream1")
    assert disc.best_sub is not None
    assert disc.best_sub.endswith("/stream2")
    by_path = {p.path: p for p in disc.paths}
    assert by_path["/stream1"].role == "main"
    assert by_path["/stream2"].role == "sub"
    assert by_path["/stream1"].width == 1920
    assert by_path["/stream2"].width == 1920


async def test_scan_subnet_api_kembalikan_role_main_sub(
    scan_client, monkeypatch,
):
    """HTTP: hasil scan kamera membawa role main/sub di paths dan
    best_main/best_sub terisi, supaya UI bisa menampilkan keduanya."""
    app = await _login_admin(scan_client)

    async def fake_reachable(host: str, port: int) -> bool:
        return host == "192.168.1.10"

    async def fake_port_open(host: str, port: int) -> bool:
        return host == "192.168.1.10"

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        return "open" if url.endswith(("/stream1", "/stream2")) else "not_found"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        if url.endswith("/stream1"):
            return VideoProbe(status="video", codec="h264",
                              width=1920, height=1080, fps=25.0)
        return VideoProbe(status="video", codec="h264",
                          width=640, height=360, fps=15.0)

    monkeypatch.setattr(admin_scan, "_host_reachable", fake_reachable)
    monkeypatch.setattr(admin_scan, "_port_open", fake_port_open)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={"ip_range": "192.168.1.8/30", "port": 554},  # .9, .10
        )
        assert r.status_code == 202, r.text
        body = await _poll_done(c, r.json()["job_id"])
        assert body["status"] == "done"
        by_host = {h["host"]: h for h in body["hosts"]}
        h = by_host["192.168.1.10"]
        assert h["status"] == "video"
        assert h["best_main"].endswith("/stream1")
        assert h["best_sub"].endswith("/stream2")
        roles = {p["path"]: p["role"] for p in h["paths"] if p["status"] == "video"}
        assert roles["/stream1"] == "main"
        assert roles["/stream2"] == "sub"
        main_row = next(p for p in h["paths"] if p["role"] == "main")
        assert (main_row["width"], main_row["height"]) == (1920, 1080)
        sub_row = next(p for p in h["paths"] if p["role"] == "sub")
        assert (sub_row["width"], sub_row["height"]) == (640, 360)
        # API tetap mengembalikan host unreachable (frontend yang
        # menyembunyikannya dari tampilan).
        assert by_host["192.168.1.9"]["status"] == "unreachable"


async def test_scan_subnet_kamera_dikenal_ditandai_dan_jalur_cepat(
    scan_client, monkeypatch,
):
    """HTTP: kamera terdaftar + online di DB ditandai known=true,
    ditemukan lewat jalur cepat (tanpa ffprobe), dan host lain
    known=false."""
    from app.models.streams import Stream

    app, _, db = scan_client
    admin = make_user(role="super_admin")
    db.add(admin)
    db.add(Stream(
        name="Cam 10", rtsp_url="rtsp://admin:pw@192.168.1.10:554/H.264",
        main_url="rtsp://admin:pw@192.168.1.10:554/H.264",
        sub_url=None, is_active=True, is_online=True,
    ))
    await db.commit()
    auth_as(app, admin)

    async def fake_reachable(host: str, port: int) -> bool:
        return host == "192.168.1.10"

    async def fake_port_open(host: str, port: int) -> bool:
        return host == "192.168.1.10"

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        return "open" if url.endswith("/H.264") else "not_found"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        raise AssertionError("jalur cepat tidak boleh memanggil ffprobe")

    monkeypatch.setattr(admin_scan, "_host_reachable", fake_reachable)
    monkeypatch.setattr(admin_scan, "_port_open", fake_port_open)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)

    async with _client(app) as c:
        r = await c.post(
            "/api/admin/scan-subnet",
            json={"ip_range": "192.168.1.8/29", "port": 554},
        )
        assert r.status_code == 202, r.text
        body = await _poll_done(c, r.json()["job_id"])
        assert body["status"] == "done"
        by_host = {h["host"]: h for h in body["hosts"]}
        h = by_host["192.168.1.10"]
        assert h["known"] is True
        assert h["status"] == "video"
        assert h["best_main"].endswith("/H.264")
        assert all(
            by_host[f"192.168.1.{n}"]["known"] is False
            for n in (9, 11, 12, 13, 14)
        )
        assert len(body["candidates"]) == 1


# --- Pola RTSP riset 2026-11-13 (report.md, ~55 merek) ---

import pytest


@pytest.mark.parametrize(
    "path, peran",
    [
        # Bosch (query inst).
        ("/?h26x=4&line=1&inst=1", "main"),
        ("/?h26x=4&line=1&inst=2", "sub"),
        ("/video?inst=1", "main"),
        # Avigilon.
        ("/defaultPrimary?streamType=u", "main"),
        ("/defaultSecondary?streamType=u", "sub"),
        # Hanwha / Provision-ISR (profile).
        ("/profile1/media.smp", "main"),
        ("/profile2/media.smp", "sub"),
        ("/profile3/media.smp", "sub"),
        ("/profile1", "main"),
        ("/profile2", "sub"),
        ("/onvif/profile2/media.smp", "sub"),
        # Canon (profile1=u main, profile1=r sub — r dicek dulu).
        ("/stream/profile1=u", "main"),
        ("/stream/profile1=r", "sub"),
        # LG Master/Slave, Huawei Media1/Media2.
        ("/Master-0", "main"),
        ("/Slave-0", "sub"),
        ("/LiveMedia/ch1/Media1", "main"),
        ("/LiveMedia/ch1/Media2", "sub"),
        # Infinova / Hanbang.
        ("/1/h264major", "main"),
        ("/1/h264minor", "sub"),
        ("/1/1080p", "main"),
        ("/1/D1", "sub"),
        # Tiandy /{channel}/{stream} (angka murni).
        ("/1/1", "main"),
        ("/1/2", "sub"),
        # Digital Watchdog (path persis, bukan segmen '1' generik).
        ("/Streaming/Channels/1", "main"),
        # Swann (ch01/0 main, ch01/1 sub — segmen pertama bukan angka).
        ("/ch01/0", "main"),
        ("/ch01/1", "sub"),
        # Hiseeu / V380 / Xiaomi (ch0_0 main, ch0_1 sub).
        ("/ch0_0.264", "main"),
        ("/ch0_1.264", "sub"),
        ("/ch0_0.h264", "main"),
        ("/ch0_1.h264", "sub"),
        # Eufy / Zosi / JVS (live0 main, live1 sub).
        ("/live0", "main"),
        ("/live1", "sub"),
        ("/live0.264", "main"),
        ("/live1.264", "sub"),
        ("/live1s.sdp", "sub"),
        # Ezviz / Tiandy bentuk h264/ch01.
        ("/h264/ch01/main/av_stream", "main"),
        ("/h264/ch01/sub/av_stream", "sub"),
        ("/h264/ch1/main/av_stream", "main"),
        ("/ch1/main", "main"),
        ("/ch1/sub", "sub"),
        # Kedacom / TVT (kata main/sub di query).
        ("/session0?streamid=main", "main"),
        ("/session0?streamid=sub", "sub"),
        ("/?chID=1&streamType=main&linkType=tcp", "main"),
        ("/?chID=1&streamType=sub&linkType=tcp", "sub"),
        # Panasonic bentuk underscore.
        ("/MediaInput/h264/stream_1", "main"),
        ("/MediaInput/h264/stream_2", "sub"),
        # Pelco h264_2 sub (h264_3 = stream ketiga, tanpa peran).
        ("/h264_2", "sub"),
        ("/h264_3", None),
        # Zmodo tcp/av0_0, /third dan /media/video3 tanpa peran.
        ("/tcp/av0_0", "main"),
        ("/tcp/av0_1", "sub"),
        ("/third", None),
        ("/media/video3", None),
        # Generik tanpa petunjuk tetap None (resolusi yang memutuskan).
        ("/live", None),
        ("/H.264", None),
        ("/media/video1", None),
        ("/onvif1", None),
        ("/CH001.sdp", None),
        ("/ch0", None),
        ("/vis", None),
        ("/", None),
        ("/rtsp_tunnel", None),
        ("/h264_stream", None),
        ("/stream0", None),
        ("/stream6", None),
    ],
)
def test_classify_path_name_pola_baru_riset(path, peran):
    """classify_path_name mengenali semua pola baru dari riset."""
    assert rtsp_discovery.classify_path_name(path) == peran


def test_candidate_paths_memuat_semua_pola_riset():
    """Semua path riset jadi kandidat; 12 pertama tidak berubah
    (Hikvision, Dahua, Uniview, stream1/2, Reolink, H.264)."""
    from app.services.rtsp_discovery import candidate_paths

    cands = candidate_paths()
    assert len(cands) == len(set(cands)), "kandidat tidak boleh duplikat"
    assert len(cands) >= 120, f"hanya {len(cands)} kandidat"
    assert cands[:12] == [
        "/Streaming/Channels/101",
        "/Streaming/Channels/102",
        "/cam/realmonitor?channel=1&subtype=0",
        "/cam/realmonitor?channel=1&subtype=1",
        "/unicast/c1/s0/live",
        "/unicast/c1/s1/live",
        "/stream1",
        "/stream2",
        "/h264Preview_01_main",
        "/h264Preview_01_sub",
        "/H.264",
        "/H.264_sub",
    ]
    wajib = [
        # Merek baru (template brand).
        "/?h26x=4&line=1&inst=1", "/?h26x=4&line=1&inst=2",
        "/defaultPrimary?streamType=u", "/defaultSecondary?streamType=u",
        "/live2.sdp", "/h264_2", "/h264.sdp",
        "/profile1", "/profile2",
        "/?chID=1&streamType=main&linkType=tcp",
        "/ch0_0.264", "/ch0_1.264", "/onvif2",
        "/ch01/0", "/ch01/1", "/CH001.sdp",
        "/LiveMedia/ch1/Media1", "/LiveMedia/ch1/Media2",
        "/play1.sdp", "/live1.sdp", "/Streaming/Channels/1",
        "/tcp/av0_0", "/tcp/av0_1",
        "/session0?streamid=main", "/session0?streamid=sub",
        "/1/h264major", "/1/h264minor",
        "/stream0", "/stream/profile1=u", "/stream/profile1=r",
        "/Master-0", "/Slave-0", "/live0.264", "/live1.264",
        "/ch0_0.h264", "/ch0_1.h264", "/live0", "/live1",
        "/h264/ch01/main/av_stream", "/h264/ch01/sub/av_stream",
        "/axis-media/media.amp?camera=1",
        # Varian konflik / generik (_COMMON_PATHS).
        "/onvif2", "/media/video3", "/live1s.sdp",
        "/h264/ch1/main/av_stream", "/H264/ch1/main/av_stream",
        "/ch1/main", "/ch1/sub", "/h264_stream",
        "/Preview_01_main", "/Preview_01_sub",
        "/profile3/media.smp", "/onvif/profile2/media.smp",
        "/LiveChannel/0/media.smp",
        "/MediaInput/h264", "/MediaInput/mpeg4",
        "/1/1", "/1/2", "/1/1080p", "/1/D1",
        "/stream6", "/stream7", "/third",
        "/channel1/main", "/channel1/sub",
        "/sensor1/main", "/sensor1/sub",
        "/ch0", "/vis", "/rtsp_tunnel",
        "/rtsp_tunnel?p=0&h26x=4", "/video?inst=1",
        "/axis-media/media.amp", "/mpeg4/media.amp",
        "/onvif-media/media.amp?profile=profile_1_h264",
        "/rtsp/streaming?channel=1&subtype=0",
        "/rtsp/streaming?channel=1&subtype=1",
        "/channel=1_stream=0.sdp?real_stream",
        "/onvif-stream1", "/onvif&event&video1",
        "/live/ch0", "/live/h264", "/h264_3",
        "/",
    ]
    hilang = [p for p in wajib if p not in cands]
    assert not hilang, f"path riset belum jadi kandidat: {hilang}"


def test_select_main_sub_stream_ketiga_bukan_sub():
    """Stream ketiga (lebih kecil, tanpa nama sub) tidak boleh jadi
    sub bila ada path yang namanya memang sub — mis. Milesight
    /main 1080p, /sub 720p, /third 360p -> sub harus /sub."""
    paths = [
        PathResult(path="/main", url="rtsp://h/main", status="video",
                   codec="h264", width=1920, height=1080, fps=25.0),
        PathResult(path="/sub", url="rtsp://h/sub", status="video",
                   codec="h264", width=1280, height=720, fps=25.0),
        PathResult(path="/third", url="rtsp://h/third", status="video",
                   codec="h264", width=640, height=360, fps=25.0),
    ]
    main, sub = rtsp_discovery.select_main_sub(paths)
    assert main == "rtsp://h/main"
    assert sub == "rtsp://h/sub"
    assert paths[1].role == "sub"
    assert paths[2].role is None


async def test_discover_host_merek_baru_bosch_avigilon(monkeypatch):
    """End-to-end: Bosch (inst=1/inst=2, resolusi sama -> nama yang
    membedakan) dan Avigilon (defaultPrimary/Secondary) terdeteksi
    sebagai main/sub dengan role benar."""
    async def fake_alive(host: str, port: int) -> bool:
        return True

    async def fake_probe(url: str, timeout: float = 3.0) -> str:
        # Cocok PERSIS (bukan endswith): endswith('inst=1') akan ikut
        # membuka '/video?inst=1' dari _COMMON_PATHS yang urutannya
        # lebih dulu dan akan menang jadi main.
        from urllib.parse import urlparse

        parts = urlparse(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        return "open" if path in {
            "/?h26x=4&line=1&inst=1", "/?h26x=4&line=1&inst=2",
            "/defaultPrimary?streamType=u",
            "/defaultSecondary?streamType=u",
        } else "not_found"

    async def fake_ffprobe(url: str, timeout: float = 10.0) -> VideoProbe:
        # Kamera menjawab semua path dengan stream yang SAMA.
        return VideoProbe(status="video", codec="h264",
                          width=1920, height=1080, fps=25.0, gop_seconds=2.0)

    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)

    disc = await rtsp_discovery.discover_host("192.168.1.10", 554,
                                              "admin", "pw")
    assert disc.best_main is not None
    assert disc.best_sub is not None
    by_path = {p.path: p for p in disc.paths if p.status == "video"}
    # Bosch: inst=1 main, inst=2 sub (keduanya video, resolusi sama).
    assert by_path["/?h26x=4&line=1&inst=1"].role == "main"
    assert by_path["/?h26x=4&line=1&inst=2"].role == "sub"
    assert disc.best_main.endswith("inst=1")
    assert disc.best_sub.endswith("inst=2")
    # Avigilon: kedua path ditemukan sebagai video (klasifikasi
    # namanya sudah dibuktikan tes classify di atas); hanya satu
    # pasang main/sub yang terpilih, dan Bosch menang tiebreak
    # karena urutan kandidatnya lebih dulu, jadi role Avigilon None.
    assert by_path["/defaultPrimary?streamType=u"].status == "video"
    assert by_path["/defaultSecondary?streamType=u"].status == "video"
    assert by_path["/defaultPrimary?streamType=u"].role is None
    assert by_path["/defaultSecondary?streamType=u"].role is None
    # Main dan sub harus berbeda path.
    assert disc.best_main != disc.best_sub
