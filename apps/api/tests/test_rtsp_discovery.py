"""Test rtsp_discovery: klasifikasi status, pemilihan main/sub, mode tambah
kamera otomatis. Semua di-mock — tanpa jaringan & tanpa ffprobe asli."""

import time

from httpx import ASGITransport, AsyncClient

from app.services import rtsp_discovery
from app.services.rtsp_discovery import (
    PathResult,
    VideoProbe,
    classify_path_name,
    parse_ffprobe_output,
    select_main_sub,
)
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _login_admin(app_client):
    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    return app


# ---------- logika murni ----------

def test_candidate_paths_unik_dan_lengkap():
    paths = rtsp_discovery.candidate_paths(1)
    assert len(paths) == len(set(paths)), "path dobel"
    for p in (
        "/Streaming/Channels/101", "/Streaming/Channels/102",
        "/cam/realmonitor?channel=1&subtype=0",
        "/unicast/c1/s0/live", "/stream1", "/stream2",
        "/h264Preview_01_main", "/H.264", "/H.264_sub", "/live.sdp",
        "/live/0/MAIN", "/live/0/SUB",
    ):
        assert p in paths, f"hilang: {p}"


def test_parse_ffprobe_output_video():
    out = (
        '{"streams":[{"codec_name":"h264","width":800,"height":448,'
        '"avg_frame_rate":"25/1"}],'
        '"packets":[{"pts_time":"0.0","flags":"K_"},'
        '{"pts_time":"0.04","flags":"___"},'
        '{"pts_time":"2.0","flags":"K_"}]}'
    )
    vp = parse_ffprobe_output(out)
    assert vp.status == "video"
    assert (vp.codec, vp.width, vp.height, vp.fps) == ("h264", 800, 448, 25.0)
    assert vp.gop_seconds == 2.0


def test_parse_ffprobe_output_tanpa_packet_no_video():
    out = '{"streams":[{"codec_name":"h264","width":800,"height":448}],"packets":[]}'
    assert parse_ffprobe_output(out).status == "no_video"
    assert parse_ffprobe_output('{"streams":[],"packets":[]}').status == "no_video"


def test_select_main_sub():
    big = PathResult(path="/a", url="rtsp://h/a", status="video",
                     width=2560, height=1440, fps=15.0)
    small = PathResult(path="/b", url="rtsp://h/b", status="video",
                       width=704, height=576, fps=25.0)
    dead = PathResult(path="/c", url="rtsp://h/c", status="no_video")
    assert select_main_sub([small, dead, big]) == ("rtsp://h/a", "rtsp://h/b")
    assert select_main_sub([big]) == ("rtsp://h/a", None)
    assert select_main_sub([dead]) == (None, None)
    assert select_main_sub([]) == (None, None)
    # Kamera yang menjawab banyak path dengan stream sama: main = kandidat
    # pertama, tanpa sub palsu beresolusi sama.
    alias1 = PathResult(path="/x", url="rtsp://h/x", status="video", width=800, height=448)
    alias2 = PathResult(path="/y", url="rtsp://h/y", status="video", width=800, height=448)
    assert select_main_sub([alias1, alias2]) == ("rtsp://h/x", None)


def test_classify_path_name_main_sub():
    """Pola nama lintas merek: main vs sub, generik tanpa petunjuk."""
    main_paths = [
        "/Streaming/Channels/101",  # Hikvision main
        "/cam/realmonitor?channel=1&subtype=0",  # Dahua main
        "/unicast/c1/s0/live",
        "/stream1",
        "/h264Preview_01_main",
        "/live/ch00_0",
        "/live/0/MAIN",
        "/av0_0",
        "/0",
        "/11",
        "/ch1/main",
    ]
    sub_paths = [
        "/Streaming/Channels/102",  # Hikvision sub
        "/cam/realmonitor?channel=1&subtype=1",  # Dahua sub
        "/unicast/c1/s1/live",
        "/stream2",
        "/h264Preview_01_sub",
        "/H.264_sub",
        "/live/ch00_1",
        "/live/0/SUB",
        "/av0_1",
        "/1",
        "/12",
        "/ch1/sub",
    ]
    for p in main_paths:
        assert classify_path_name(p) == "main", f"harus main: {p}"
    for p in sub_paths:
        assert classify_path_name(p) == "sub", f"harus sub: {p}"
    # Generik tanpa petunjuk (bukan main maupun sub).
    for p in ("/live", "/live.sdp", "/H.264", "/H.265", "/h264",
              "/media/video1", "/onvif1", "/video1", "/ch01.264"):
        assert classify_path_name(p) is None, f"tanpa petunjuk: {p}"
    # 'subtype=0' mengandung kata 'sub' tapi tetap main (urutan cek).
    assert classify_path_name("/cam/realmonitor?channel=1&subtype=0") == "main"


def test_select_main_sub_nama_saat_resolusi_sama():
    """Resolusi seri -> nama path yang membedakan main/sub, dan role
    ditandai di PathResult yang terpilih."""
    p1 = PathResult(path="/stream1", url="rtsp://h/stream1",
                    status="video", width=1920, height=1080, fps=25.0)
    p2 = PathResult(path="/stream2", url="rtsp://h/stream2",
                    status="video", width=1920, height=1080, fps=15.0)
    p3 = PathResult(path="/live", url="rtsp://h/live",
                    status="video", width=1920, height=1080, fps=25.0)
    assert select_main_sub([p2, p3, p1]) == (
        "rtsp://h/stream1", "rtsp://h/stream2")
    assert p1.role == "main"
    assert p2.role == "sub"
    assert p3.role is None


def test_select_main_sub_resolusi_lebih_kuat_dari_nama():
    """Resolusi adalah sinyal terkuat: path bernama 'sub' yang
    resolusinya lebih besar tetap jadi main, dan sebaliknya."""
    big_sub = PathResult(path="/stream2", url="rtsp://h/stream2",
                         status="video", width=1920, height=1080, fps=25.0)
    small_main = PathResult(path="/stream1", url="rtsp://h/stream1",
                            status="video", width=640, height=360, fps=15.0)
    assert select_main_sub([small_main, big_sub]) == (
        "rtsp://h/stream2", "rtsp://h/stream1")
    assert big_sub.role == "main"
    assert small_main.role == "sub"


# ---------- verifikasi URL tunggal ----------

async def test_verify_url_auth_failed(monkeypatch):
    async def fake_probe(url, timeout=3.0):
        return "auth_failed"

    async def fake_ffprobe(url, timeout=10.0):
        raise AssertionError("tidak boleh ffprobe saat auth gagal")

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    vp = await rtsp_discovery.verify_url("rtsp://h/H.264")
    assert vp.status == "auth_failed"


async def test_verify_url_no_video(monkeypatch):
    async def fake_probe(url, timeout=3.0):
        return "open"

    async def fake_ffprobe(url, timeout=10.0):
        return VideoProbe(status="no_video")

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    assert (await rtsp_discovery.verify_url("rtsp://h/H.264")).status == "no_video"


# ---------- discovery per host ----------

async def test_discover_host_mati_berhenti_cepat(monkeypatch):
    async def fake_alive(host, port):
        return False

    async def never(url, timeout=3.0):
        raise AssertionError("host mati tidak boleh coba semua path")

    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
    monkeypatch.setattr(rtsp_discovery, "probe_path", never)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", never)
    t0 = time.monotonic()
    disc = await rtsp_discovery.discover_host("10.0.0.9", 554, "admin", "pw")
    assert time.monotonic() - t0 < 1.5
    assert disc.reachable is False
    assert disc.paths == []
    assert disc.best_main is None
    assert "tidak terjangkau" in disc.ringkasan()


async def test_discover_host_verifikasi_dan_pilih_main_sub(monkeypatch):
    """Main/sub dipilih dari resolusi ffprobe; begitu keduanya
    terverifikasi, probe berhenti dini (gelombang 1) sehingga path
    belakangan seperti /live tidak ikut dicoba — ini yang memangkas
    burst login penyebab 'Login salah' palsu."""
    async def fake_probe(url, timeout=3.0):
        if url.endswith(("/Streaming/Channels/101", "/Streaming/Channels/102")):
            return "open"
        if url.endswith("/live"):
            return "auth_failed"
        return "not_found"

    async def fake_ffprobe(url, timeout=10.0):
        if url.endswith("/Streaming/Channels/101"):
            return VideoProbe(status="video", codec="h264",
                              width=2560, height=1440, fps=15.0, gop_seconds=2.0)
        return VideoProbe(status="video", codec="h264",
                          width=704, height=576, fps=25.0, gop_seconds=1.0)

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    disc = await rtsp_discovery.discover_host("192.168.34.196", 554, "admin", "pw")
    assert disc.reachable is True
    assert disc.best_main is not None and disc.best_main.endswith("/Streaming/Channels/101")
    assert disc.best_sub is not None and disc.best_sub.endswith("/Streaming/Channels/102")
    by_path = {p.path: p for p in disc.paths}
    assert by_path["/Streaming/Channels/101"].status == "video"
    assert by_path["/Streaming/Channels/101"].width == 2560
    # Berhenti dini: hanya gelombang 1 yang dicoba, path belakangan
    # (mis. /live) tidak ikut di-DESCRIBE.
    assert len(disc.paths) == rtsp_discovery._SEM_PROBES
    assert "/live" not in by_path, "path belakangan tidak boleh dicoba"
    assert "video" in disc.ringkasan()


async def test_discover_host_auth_failed_dilaporkan_tanpa_early_exit(monkeypatch):
    """Bila sub tidak ketemu, probe TIDAK berhenti dini: semua path
    dicoba, dan path yang gagal auth tetap dilaporkan auth_failed
    (bukan hilang karena early exit)."""
    async def fake_probe(url, timeout=3.0):
        if url.endswith("/Streaming/Channels/101"):
            return "open"
        if url.endswith("/live"):
            return "auth_failed"
        return "not_found"

    async def fake_ffprobe(url, timeout=10.0):
        return VideoProbe(status="video", codec="h264",
                          width=2560, height=1440, fps=15.0, gop_seconds=2.0)

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    disc = await rtsp_discovery.discover_host("192.168.34.196", 554, "admin", "pw")
    assert disc.reachable is True
    assert disc.best_main is not None and disc.best_main.endswith("/Streaming/Channels/101")
    assert disc.best_sub is None  # hanya main, sub tidak ketemu
    by_path = {p.path: p for p in disc.paths}
    assert by_path["/live"].status == "auth_failed"
    assert by_path["/live.sdp"].status == "not_found"
    assert len(disc.paths) == len(rtsp_discovery.candidate_paths())


async def test_discover_host_coba_ulang_auth_failed(monkeypatch):
    """Semua path auth_failed di pass pertama (kamera mengunci login
    sementara akibat burst) -> coba ulang sekali setelah jeda; bila
    kunci sudah lepas, main+sub ketemu di pass kedua."""
    calls: list[str] = []
    seen: set[str] = set()

    async def fake_probe(url, timeout=3.0):
        calls.append(url)
        if url in seen:
            # Pass kedua (coba ulang): kunci lepas, 101/102 terbuka.
            return "open" if url.endswith(
                ("/Streaming/Channels/101", "/Streaming/Channels/102")
            ) else "not_found"
        seen.add(url)
        return "auth_failed"

    async def fake_ffprobe(url, timeout=10.0):
        if url.endswith("/Streaming/Channels/101"):
            return VideoProbe(status="video", codec="h264",
                              width=2560, height=1440, fps=15.0, gop_seconds=2.0)
        return VideoProbe(status="video", codec="h264",
                          width=704, height=576, fps=25.0, gop_seconds=1.0)

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    # Jeda 12 dtk dipangkas supaya tes cepat; yang diuji adalah
    # coba ulangnya, bukan lamanya jeda.
    monkeypatch.setattr(rtsp_discovery, "_AUTH_RETRY_DELAY", 0)
    disc = await rtsp_discovery.discover_host("192.168.34.198", 554, "admin", "pw")
    assert disc.reachable is True
    assert disc.best_main is not None and disc.best_main.endswith("/Streaming/Channels/101")
    assert disc.best_sub is not None and disc.best_sub.endswith("/Streaming/Channels/102")
    # Pass pertama mencoba semua 126 path, pass kedua berhenti dini
    # di gelombang 1 (8 path) begitu main+sub ketemu.
    assert len(calls) == len(rtsp_discovery.candidate_paths()) + rtsp_discovery._SEM_PROBES


async def test_discover_host_coba_ulang_auth_failed_tetap_gagal(monkeypatch):
    """Coba ulang tetap auth_failed -> barulah 'Login salah'
    (password memang salah); probe dipanggil 2x per path."""
    calls: list[str] = []

    async def fake_probe(url, timeout=3.0):
        calls.append(url)
        return "auth_failed"

    async def fake_ffprobe(url, timeout=10.0):
        raise AssertionError("tidak boleh ffprobe saat auth gagal")

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    monkeypatch.setattr(rtsp_discovery, "_AUTH_RETRY_DELAY", 0)
    disc = await rtsp_discovery.discover_host("192.168.34.199", 554, "admin", "pw")
    assert disc.reachable is True
    assert disc.best_main is None
    assert disc.best_sub is None
    assert all(p.status == "auth_failed" for p in disc.paths)
    # Dua pass penuh (126 x 2): coba ulang benar-benar dilakukan.
    assert len(calls) == 2 * len(rtsp_discovery.candidate_paths())


async def test_discover_host_live_0_main_sub(monkeypatch):
    """Pola /live/0/MAIN (main) + /live/0/SUB (sub) ikut di-scan dan
    dikenali sebagai best_main/best_sub (resolusi + nama sepakat)."""
    async def fake_probe(url, timeout=3.0):
        if url.endswith(("/live/0/MAIN", "/live/0/SUB")):
            return "open"
        return "not_found"

    async def fake_ffprobe(url, timeout=10.0):
        if url.endswith("/live/0/MAIN"):
            return VideoProbe(status="video", codec="h264",
                              width=1920, height=1080, fps=25.0, gop_seconds=2.0)
        return VideoProbe(status="video", codec="h264",
                          width=640, height=360, fps=15.0, gop_seconds=1.0)

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    disc = await rtsp_discovery.discover_host("192.168.34.197", 554, "admin", "pw")
    assert disc.reachable is True
    assert disc.best_main is not None and disc.best_main.endswith("/live/0/MAIN")
    assert disc.best_sub is not None and disc.best_sub.endswith("/live/0/SUB")
    by_path = {p.path: p for p in disc.paths}
    assert by_path["/live/0/MAIN"].status == "video"
    assert by_path["/live/0/MAIN"].width == 1920
    assert by_path["/live/0/MAIN"].role == "main"
    assert by_path["/live/0/SUB"].status == "video"
    assert by_path["/live/0/SUB"].width == 640
    assert by_path["/live/0/SUB"].role == "sub"


# ---------- endpoint /admin/scan ----------

async def test_scan_host_mode_kembalikan_paths_dan_best(app_client, monkeypatch):
    async def fake_probe(url, timeout=3.0):
        return "open" if url.endswith("/H.264") else "not_found"

    async def fake_ffprobe(url, timeout=10.0):
        return VideoProbe(status="video", codec="h264",
                          width=800, height=448, fps=25.0, gop_seconds=2.0)

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    app = await _login_admin(app_client)
    async with _client(app) as c:
        r = await c.post("/api/admin/scan", json={
            "host": "192.168.34.196", "user": "admin", "password": "pw",
            "brand": "auto", "probe": True,
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["best_main"] is not None
    assert body["best_main"].endswith("/H.264")
    assert body["best_sub"] is None
    statuses = {p["path"]: p["status"] for p in body["paths"]}
    assert statuses["/H.264"] == "video"
    assert statuses["/H.264_sub"] == "not_found"
    main_rows = [p for p in body["paths"] if p["role"] == "main"]
    assert len(main_rows) == 1 and main_rows[0]["path"] == "/H.264"
    # Kompatibilitas field lama.
    assert len(body["candidates"]) == 5
    for cand in body["candidates"]:
        assert cand["probe_status"] in ("video", "not_found")


async def test_scan_url_langsung_diverifikasi(app_client, monkeypatch):
    async def fake_probe(url, timeout=3.0):
        return "open"

    async def fake_ffprobe(url, timeout=10.0):
        return VideoProbe(status="no_video")

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    app = await _login_admin(app_client)
    async with _client(app) as c:
        r = await c.post("/api/admin/scan",
                         json={"rtsp_url": "rtsp://h:554/H.264", "probe": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["paths"][0]["status"] == "no_video"
    assert body["best_main"] is None
    assert body["candidates"][0]["main_ok"] is False


# ---------- endpoint /admin/streams (tambah kamera) ----------

async def test_create_stream_otomatis_pakai_discovery(app_client, monkeypatch):
    async def fake_probe(url, timeout=3.0):
        return "open" if url.endswith("/Streaming/Channels/101") else "not_found"

    async def fake_ffprobe(url, timeout=10.0):
        return VideoProbe(status="video", codec="h264",
                          width=2560, height=1440, fps=15.0, gop_seconds=2.0)

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={
            "name": "Gerbang", "host": "192.168.34.196",
            "user": "admin", "password": "pw",
        })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["brand"] == "generic"
    from app.models.streams import Stream
    st = await db.get(Stream, body["id"])
    assert st is not None
    assert st.rtsp_url is not None
    assert st.rtsp_url.endswith("/Streaming/Channels/101")


async def test_create_stream_tanpa_video_ditolak(app_client, monkeypatch):
    async def fake_probe(url, timeout=3.0):
        return "not_found"

    async def fake_ffprobe(url, timeout=10.0):
        raise AssertionError("tidak boleh ffprobe")

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    app = await _login_admin(app_client)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={
            "name": "Gerbang", "host": "192.168.34.196",
            "user": "admin", "password": "pw",
        })
    assert r.status_code == 400, r.text
    assert "Tidak ada path yang mengirim video" in r.json()["detail"]


async def test_create_stream_rtsp_url_verifikasi_dan_force(app_client, monkeypatch):
    async def fake_probe(url, timeout=3.0):
        return "auth_failed"

    async def fake_ffprobe(url, timeout=10.0):
        raise AssertionError("tidak boleh ffprobe saat auth gagal")

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    app = await _login_admin(app_client)
    payload = {"name": "Cam", "rtsp_url": "rtsp://u:p@h:554/H.264"}
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json=payload)
        assert r.status_code == 400, r.text
        assert "auth_failed" in r.json()["detail"]
        r = await c.post("/api/admin/streams", json={**payload, "force": True})
        assert r.status_code == 201, r.text
