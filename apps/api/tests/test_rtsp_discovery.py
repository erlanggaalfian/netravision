"""Test rtsp_discovery: klasifikasi status, pemilihan main/sub, mode tambah
kamera otomatis. Semua di-mock — tanpa jaringan & tanpa ffprobe asli."""

import time

from httpx import ASGITransport, AsyncClient

from app.services import rtsp_discovery
from app.services.rtsp_discovery import (
    PathResult,
    VideoProbe,
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
    assert by_path["/live"].status == "auth_failed"
    assert by_path["/live.sdp"].status == "not_found"
    assert "video" in disc.ringkasan()


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
