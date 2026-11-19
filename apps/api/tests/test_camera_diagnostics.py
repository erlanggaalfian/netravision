"""Test diagnostik tambah kamera: klasifikasi, endpoint, halaman data.

Semua copy dicek bebas em dash dan en dash (aturan 2026-11-03).
Simulasi kegagalan: MediaMTX 401 dan 307 lewat FakeMediaMTX, probe
auth gagal lewat monkeypatch verify_url. Tidak ada yang boleh
mengembalikan HTTP 500.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models.diagnostics import CameraAddFailure, CameraProbeResult
from app.models.streams import Stream
from app.services import rtsp_discovery
from app.services.camera_diagnostics import (
    classify_discovery,
    classify_mediamtx_error,
    classify_probe,
    classify_resolver,
)
from app.services.mediamtx import MediaMTXError
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_super(db):
    su = make_user(id=9, username="super", role="super_admin")
    db.add(su)
    await db.commit()
    return su


def _assert_no_dash(envelope):
    """Satu envelope bebas em dash dan en dash di semua string."""
    texts = [envelope["judul"], envelope["penyebab"], *envelope["langkah"]]
    for text in texts:
        assert "—" not in text, text
        assert "–" not in text, text


# ---------- Klasifikasi (unit) ----------


def test_classify_mediamtx_redirect_307():
    failure = classify_mediamtx_error(
        MediaMTXError("redirect", status_code=307, kind="redirect")
    )
    assert failure["code"] == "mediamtx_redirect"
    assert "Alamat control API" in failure["judul"]
    assert "9997" in failure["penyebab"]
    assert len(failure["langkah"]) >= 3
    _assert_no_dash(failure)


def test_classify_mediamtx_auth_401():
    failure = classify_mediamtx_error(
        MediaMTXError("unauthorized", status_code=401, kind="auth")
    )
    assert failure["code"] == "mediamtx_auth"
    assert "401" in failure["penyebab"]
    assert "localhost" in failure["penyebab"]
    assert len(failure["langkah"]) >= 3
    _assert_no_dash(failure)


def test_classify_mediamtx_unreachable():
    failure = classify_mediamtx_error(
        MediaMTXError("boom", kind="unreachable")
    )
    assert failure["code"] == "mediamtx_unreachable"
    _assert_no_dash(failure)


def test_classify_probe_video_returns_none():
    assert classify_probe("video", "main") is None
    assert classify_probe("video", "sub") is None


@pytest.mark.parametrize(
    "status,code",
    [
        ("auth_failed", "rtsp_auth"),
        ("not_found", "rtsp_not_found"),
        ("timeout", "rtsp_timeout"),
        ("no_video", "rtsp_no_video"),
        ("error", "rtsp_error"),
    ],
)
def test_classify_probe_statuses(status, code):
    failure = classify_probe(status, "main")
    assert failure["code"] == code
    assert failure["langkah"]
    _assert_no_dash(failure)


def test_classify_discovery_and_resolver():
    failure = classify_discovery("tidak ada path")
    assert failure["code"] == "rtsp_discovery"
    _assert_no_dash(failure)
    failure = classify_resolver("brand tidak dikenal")
    assert failure["code"] == "resolve_error"
    _assert_no_dash(failure)


# ---------- Tambah kamera: simulasi kegagalan ----------


async def test_create_stream_mediamtx_401_returns_201_with_failure(app_client, monkeypatch):
    """Control API 401: kamera tersimpan (201), envelope terbaca,
    bukan 500 dan bukan pesan mentah."""
    app, fake, db = app_client
    su = await _seed_super(db)
    auth_as(app, su)

    async def _ensure_path_401(name, conf):
        raise MediaMTXError("unauthorized", status_code=401, kind="auth")

    monkeypatch.setattr(fake, "ensure_path", _ensure_path_401)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={
            "name": "Cam 401", "rtsp_url": "rtsp://h:554/h264Preview_01_main",
        })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mediamtx_registered"] is False
    failure = body["mediamtx_failure"]
    assert failure["code"] == "mediamtx_auth"
    assert "401" in failure["penyebab"]
    assert len(failure["langkah"]) >= 3
    _assert_no_dash(failure)
    # Riwayat kegagalan tercatat.
    rows = (await db.execute(select(CameraAddFailure))).scalars().all()
    assert len(rows) == 1
    assert rows[0].stream_id == body["id"]
    assert rows[0].code == "mediamtx_auth"


async def test_create_stream_mediamtx_307_returns_201_with_failure(app_client, monkeypatch):
    """Endpoint salah (redirect 307): kamera tersimpan, envelope
    menunjuk ke alamat control API yang salah."""
    app, fake, db = app_client
    su = await _seed_super(db)
    auth_as(app, su)

    async def _ensure_path_307(name, conf):
        raise MediaMTXError("redirect", status_code=307, kind="redirect")

    monkeypatch.setattr(fake, "ensure_path", _ensure_path_307)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={
            "name": "Cam 307", "rtsp_url": "rtsp://h:554/h264Preview_01_main",
        })
    assert r.status_code == 201, r.text
    failure = r.json()["mediamtx_failure"]
    assert failure["code"] == "mediamtx_redirect"
    assert "9997" in failure["penyebab"]
    _assert_no_dash(failure)


async def test_create_stream_probe_auth_failed_returns_400_with_steps(app_client, monkeypatch):
    """Probe RTSP auth gagal: 400 dengan envelope (judul + penyebab
    + langkah), bukan 500."""
    app, fake, db = app_client
    su = await _seed_super(db)
    auth_as(app, su)

    async def _verify_auth_failed(url, timeout=10.0):
        return rtsp_discovery.VideoProbe(status="auth_failed")

    monkeypatch.setattr(rtsp_discovery, "verify_url", _verify_auth_failed)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={
            "name": "Cam Auth", "rtsp_url": "rtsp://h:554/h264Preview_01_main",
        })
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "rtsp_auth"
    assert "password" in detail["penyebab"].lower()
    assert len(detail["langkah"]) >= 3
    _assert_no_dash(detail)
    # Kamera tidak tersimpan, tapi kegagalan tercatat di riwayat.
    rows = (await db.execute(select(CameraAddFailure))).scalars().all()
    assert len(rows) == 1
    assert rows[0].stream_id is None
    assert rows[0].code == "rtsp_auth"
    assert (await db.execute(select(Stream))).scalars().all() == []


# ---------- Endpoint diagnostik ----------


async def test_diagnostics_get_sections(app_client):
    """GET diagnostik: tiga seksi + riwayat, tanpa 500 walau MediaMTX
    belum menyediakan get_config/get_paths (fake lama)."""
    app, fake, db = app_client
    su = await _seed_super(db)
    auth_as(app, su)
    s = Stream(
        id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
        main_url="rtsp://cam/1", sub_url="rtsp://cam/1/sub",
        is_active=True,
    )
    db.add(s)
    await db.commit()

    async def _get_paths():
        return {"stream_1"}

    async def _get_config():
        return {"version": "1.9.0"}

    fake.get_paths = _get_paths
    fake.get_config = _get_config
    async with _client(app) as c:
        r = await c.get("/api/admin/diagnostics/camera-add")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mediamtx"]["reachable"] is True
    assert body["mediamtx"]["status"] == "ok"
    assert body["mediamtx"]["version"] == "1.9.0"
    # main terdaftar, sub hilang.
    assert body["paths_total"] == 2
    assert body["paths_terdaftar"] == 1
    assert len(body["paths_hilang"]) == 1
    assert body["paths_hilang"][0]["path"] == "stream_1_sub"
    # RTSP: belum pernah diprobe.
    assert len(body["rtsp"]) == 1
    assert body["rtsp"][0]["main_status"] is None
    assert body["riwayat"] == []


async def test_diagnostics_get_mediamtx_unreachable_still_200(app_client):
    """MediaMTX tidak bisa dihubungi: halaman tetap 200 dengan seksi
    control API berstatus unreachable + envelope, bukan 500."""
    app, fake, db = app_client
    su = await _seed_super(db)
    auth_as(app, su)

    async def _get_config_down():
        raise MediaMTXError("down", kind="unreachable")

    async def _get_paths_down():
        raise MediaMTXError("down", kind="unreachable")

    fake.get_config = _get_config_down
    fake.get_paths = _get_paths_down
    async with _client(app) as c:
        r = await c.get("/api/admin/diagnostics/camera-add")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mediamtx"]["reachable"] is False
    assert body["mediamtx"]["status"] == "unreachable"
    assert body["mediamtx"]["failure"]["code"] == "mediamtx_unreachable"


async def test_diagnostics_probe_endpoint(app_client):
    """POST probe: hasil probe tersimpan dan dikembalikan."""
    app, fake, db = app_client
    su = await _seed_super(db)
    auth_as(app, su)
    s = Stream(
        id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
        main_url="rtsp://cam/1", sub_url="rtsp://cam/1/sub",
        is_active=True,
    )
    db.add(s)
    await db.commit()
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/diagnostics/camera-add/probe", json={"stream_id": 1}
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["main"]["status"] == "video"
    assert body["main"]["failure"] is None
    assert body["sub"]["status"] == "video"
    row = await db.get(CameraProbeResult, 1)
    assert row is not None
    assert row.main_status == "video"
    assert row.sub_status == "video"


async def test_diagnostics_probe_unknown_camera_404(app_client):
    app, fake, db = app_client
    su = await _seed_super(db)
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/diagnostics/camera-add/probe", json={"stream_id": 99}
        )
    assert r.status_code == 404


async def test_diagnostics_requires_super_admin(app_client):
    """Admin biasa (bukan super_admin) ditolak 403."""
    app, fake, db = app_client
    admin = make_user(id=2, username="op", role="admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/admin/diagnostics/camera-add")
    assert r.status_code == 403, r.text
