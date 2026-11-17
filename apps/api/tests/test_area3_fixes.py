"""Tes perbaikan temuan audit Area 3 (Service layer), 2026-11-17.

Nomor temuan mengacu pada BACKEND_DB_AUDIT_2026-11-17.md bagian Area 3.
"""

import asyncio
import os
import time

import httpx
import pytest


# ---------------------------------------------------------------------------
# 3.2: klaim per-segmen antar tiga jalur upload
# ---------------------------------------------------------------------------

def test_claims_satu_pemilik():
    from app.services import upload_claims as uc

    uc._reset_for_tests()
    try:
        assert uc.try_claim(7, "a.mp4", "uploader") is True
        assert uc.try_claim(7, "a.mp4", "mirror") is False
        assert uc.try_claim(7, "a.mp4", "oauth") is False
        assert uc.is_claimed(7, "a.mp4") is True
        # Hanya pemilik yang boleh melepas.
        uc.release_claim(7, "a.mp4", "mirror")
        assert uc.is_claimed(7, "a.mp4") is True
        uc.release_claim(7, "a.mp4", "uploader")
        assert uc.is_claimed(7, "a.mp4") is False
        assert uc.try_claim(7, "a.mp4", "mirror") is True
        # Klaim kedaluwarsa (TTL) tidak memblokir selamanya.
        uc._claims[(7, "b.mp4")] = ("uploader", time.monotonic() - 2000)
        assert uc.is_claimed(7, "b.mp4") is False
        assert uc.try_claim(7, "b.mp4", "mirror") is True
    finally:
        uc._reset_for_tests()


def test_mirror_lewati_yang_sudah_terupload(monkeypatch, tmp_path):
    """3.2: mirror memeriksa drive_uploads sebelum menyalin."""
    import time as _t

    from app.core.config import get_settings
    from app.services.drive_mirror import _mirror_tick

    rec = tmp_path / "recordings" / "stream_7"
    rec.mkdir(parents=True)
    f = rec / "2026-11-02_10-00-00.mp4"
    f.write_bytes(b"x" * 100)
    old = _t.time() - 60
    os.utime(f, (old, old))
    s = get_settings()
    monkeypatch.setattr(s, "recordings_dir", str(tmp_path / "recordings"))
    monkeypatch.setattr(s, "drive_mirror_require_mount", False)
    folders = [(1, "CCTV-1", str(tmp_path / "staging1"))]
    from app.services import drive_mirror as dm
    from app.services.drive_uploader import _SEEN_STABLE as _US
    from app.services.upload_claims import _reset_for_tests as _rc

    try:
        uploaded = {7: {"2026-11-02_10-00-00.mp4"}}
        _mirror_tick([(7, "Gudang", None)], folders, uploaded)
        _mirror_tick([(7, "Gudang", None)], folders, uploaded)
        assert not (tmp_path / "staging1" / "stream_7").exists()
        assert f.exists()
    finally:
        get_settings.cache_clear()
        dm._PENDING_DELETE.clear()
        _US.clear()
        _rc()


# ---------------------------------------------------------------------------
# 3.16: stabilitas segmen dari (mtime, size) dua pengecekan
# ---------------------------------------------------------------------------

def test_is_stable_dua_cek(tmp_path):
    from app.services.drive_uploader import _SEEN_STABLE, _is_stable

    _SEEN_STABLE.clear()
    try:
        p = tmp_path / "2026-11-02_10-00-00-000000.mp4"
        p.write_bytes(b"x" * 10)
        old = time.time() - 60
        os.utime(p, (old, old))
        now = time.time()
        assert _is_stable(str(p), now) is False  # pandangan pertama
        assert _is_stable(str(p), now) is True  # tidak berubah
        p.write_bytes(b"x" * 20)  # ukuran berubah, mtime dikembalikan tua
        os.utime(p, (old, old))
        assert _is_stable(str(p), now) is False
        assert _is_stable(str(p), now) is True
    finally:
        _SEEN_STABLE.clear()


# ---------------------------------------------------------------------------
# 3.7: backoff uploader/mirror hidup dari hitungan gagal
# ---------------------------------------------------------------------------

async def test_upload_once_tidak_terhubung_dihitung_gagal(monkeypatch):
    from app.services import drive_uploader as du
    from app.services import gdrive_rclone as gr

    async def _fake_status():
        return {"connected": False}

    monkeypatch.setattr(gr, "connection_status", _fake_status)
    assert await du._upload_once() == 1


def test_mirror_tick_hitung_gagal(monkeypatch, tmp_path):
    """3.7: salinan yang gagal dihitung (bukan ditelan) supaya backoff jalan."""
    import time as _t

    from app.services.drive_mirror import _mirror_tick
    from app.services import drive_mirror as dm
    from app.services.drive_uploader import _SEEN_STABLE as _US
    from app.services.upload_claims import _reset_for_tests as _rc
    from app.core.config import get_settings

    rec = tmp_path / "recordings" / "stream_7"
    rec.mkdir(parents=True)
    f = rec / "2026-11-02_10-00-00.mp4"
    f.write_bytes(b"x" * 100)
    old = _t.time() - 60
    os.utime(f, (old, old))
    s = get_settings()
    monkeypatch.setattr(s, "recordings_dir", str(tmp_path / "recordings"))
    monkeypatch.setattr(s, "drive_mirror_require_mount", False)
    # staging base adalah FILE, bukan direktori -> makedirs/copy gagal.
    staging_file = tmp_path / "staging-sebagai-file"
    staging_file.write_bytes(b"x")
    folders = [(1, "CCTV-1", str(staging_file))]
    try:
        assert _mirror_tick([(7, "Gudang", None)], folders) == 0  # baru mencatat
        assert _mirror_tick([(7, "Gudang", None)], folders) >= 1  # salin gagal
    finally:
        get_settings.cache_clear()
        dm._PENDING_DELETE.clear()
        _US.clear()
        _rc()


# ---------------------------------------------------------------------------
# 3.5: unduh rclone langsung ke file, tanpa lewat RAM
# ---------------------------------------------------------------------------

async def test_download_rclone_file_to(tmp_path, monkeypatch):
    from app.services import gdrive_rclone as gr

    script = tmp_path / "rclone"
    script.write_text("#!/bin/sh\nprintf 'SEGMENTDATA'\n")
    script.chmod(0o755)
    monkeypatch.setattr(gr, "find_rclone", lambda: str(script))
    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    dest = tmp_path / "seg.mp4"
    n = await gr.download_rclone_file_to("gdrive", "Cam/seg.mp4", str(dest))
    assert n == 11
    assert dest.read_bytes() == b"SEGMENTDATA"


# ---------------------------------------------------------------------------
# 3.6: timeout subprocess kill + wait (tidak zombie)
# ---------------------------------------------------------------------------

async def test_run_rclone_timeout_tunggu_proses(tmp_path, monkeypatch):
    from app.services import gdrive_rclone as gr

    script = tmp_path / "rclone"
    script.write_text("#!/bin/sh\nexec sleep 30\n")
    script.chmod(0o755)
    monkeypatch.setattr(gr, "find_rclone", lambda: str(script))
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="rclone timeout"):
        await gr._run_rclone("about", "gdrive:", "--json", timeout=1)
    assert time.monotonic() - start < 10


# ---------------------------------------------------------------------------
# 3.12: tulis conf atomik + 3.19: disconnect per-remote
# ---------------------------------------------------------------------------

def test_write_conf_pertahankan_remote_lain(tmp_path, monkeypatch):
    from app.services import gdrive_rclone as gr

    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    gr._write_conf('{"refresh_token": "r1", "access_token": "a"}', "gdrive")
    gr._write_conf('{"refresh_token": "r2", "access_token": "a"}', "gdrive-2")
    assert gr.list_remote_names() == ["gdrive", "gdrive-2"]
    assert os.stat(gr.conf_path()).st_mode & 0o777 == 0o600


async def test_disconnect_hanya_satu_remote(tmp_path, monkeypatch):
    from app.services import gdrive_rclone as gr

    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    gr._write_conf_text(
        "[gdrive]\ntype = drive\ntoken = {}\n\n[gdrive-2]\ntype = drive\ntoken = {}\n"
    )
    await gr.disconnect("gdrive-2")
    assert gr.list_remote_names() == ["gdrive"]
    await gr.disconnect_all()
    assert not os.path.exists(gr.conf_path())


# ---------------------------------------------------------------------------
# 3.13: authorize deadline total + prune job
# ---------------------------------------------------------------------------

def test_prune_authorize_jobs():
    from app.services import gdrive_rclone as gr

    gr._AUTHORIZE_JOBS.clear()
    try:
        gr._AUTHORIZE_JOBS["old"] = {
            "status": "done", "finished_at": time.time() - 1000,
        }
        gr._AUTHORIZE_JOBS["new"] = {
            "status": "done", "finished_at": time.time(),
        }
        assert gr.authorize_job("old") is None
        assert gr.authorize_job("new") is not None
    finally:
        gr._AUTHORIZE_JOBS.clear()


async def test_run_authorize_deadline_total(tmp_path, monkeypatch):
    """3.13: timeout 10 menit adalah deadline TOTAL, bukan per baris."""
    from app.services import gdrive_rclone as gr

    script = tmp_path / "rclone"
    script.write_text("#!/bin/sh\nexec sleep 30\n")
    script.chmod(0o755)
    monkeypatch.setattr(gr, "_AUTHORIZE_TIMEOUT_SEC", 1)
    job = {"job_id": "t1", "status": "waiting", "auth_url": None, "proc": None}
    start = time.monotonic()
    await gr._run_authorize(job, str(script))
    assert time.monotonic() - start < 10
    assert job["status"] == "error"
    assert "Waktu habis" in job["error"]
    assert job["proc"].returncode is not None  # sudah di-wait, bukan zombie


# ---------------------------------------------------------------------------
# 3.3: PKCE finish_session tidak menghapus remote lain
# ---------------------------------------------------------------------------

async def test_pkce_finish_pertahankan_remote_lain(tmp_path, monkeypatch):
    import app.services.gdrive_pkce as pk
    from app.services import gdrive_rclone as gr

    monkeypatch.setenv("RCLONE_DATA_DIR", str(tmp_path))
    gr._write_conf_text(
        '[gdrive-2]\ntype = drive\nscope = drive\ntoken = {"refresh_token": "lama"}\n'
    )
    sid = "test123"
    pk._SESSIONS[sid] = {"verifier": "v", "created": time.time()}
    token = {"access_token": "a", "refresh_token": "baru", "token_type": "Bearer"}

    class _Resp:
        status_code = 200

        def json(self):
            return token

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(pk.httpx, "AsyncClient", _FakeClient)

    async def _ok():
        return {"connected": True}

    monkeypatch.setattr(gr, "connection_status", _ok)
    out = await pk.finish_session(sid, "kode-abc")
    assert out == {"ok": True}
    assert set(gr.list_remote_names()) == {"gdrive", "gdrive-2"}
    assert "lama" in open(gr.conf_path()).read()


# ---------------------------------------------------------------------------
# 3.4 sudah diuji di test_drive.py; 3.11 di bawah
# ---------------------------------------------------------------------------

async def test_drive_call_timeout():
    from app.services import drive as d

    # Timeout diteruskan per panggilan (default modul 120 dtk).
    with pytest.raises(asyncio.TimeoutError):
        await d._drive_call(time.sleep, 5, timeout=0.1)


async def test_upload_retry_cek_lagi_sebelum_retry(tmp_path):
    """3.11: sebelum retry, cek lagi apakah file sudah ada di Drive
    (respons upload bisa hilang padahal file sampai)."""
    from tests.test_drive import FakeDrive, _settings
    from app.services.drive import DriveUploader

    svc = FakeDrive()
    svc.fail_create = 99  # create selalu gagal
    up = DriveUploader(settings=_settings(), service=svc)
    p = tmp_path / "seg.mp4"
    p.write_bytes(b"v")
    calls = {"n": 0}
    orig_find = up.find_file

    async def _find(folder_id, name):
        calls["n"] += 1
        if calls["n"] >= 2:
            return "f-lost"  # ternyata sudah sampai di Drive
        return await orig_find(folder_id, name)

    up.find_file = _find
    fid = await up.upload_file(str(p), "Cam A", retries=3)
    assert fid == "f-lost"
    assert not p.exists()  # lokal dihapus, tidak upload duplikat


async def test_ensure_folder_tidak_duplikat_saat_bersamaan():
    """3.12: find-or-create folder diserialkan dengan lock."""
    from tests.test_drive import FakeDrive, _settings
    from app.services.drive import DriveUploader

    svc = FakeDrive()
    up = DriveUploader(settings=_settings(), service=svc)
    results = await asyncio.gather(*[up.ensure_folder("Cam A") for _ in range(5)])
    assert len(set(results)) == 1
    assert len(svc._folders) == 2  # root + Cam A


# ---------------------------------------------------------------------------
# 3.8: dependency MediaMTX ditutup
# ---------------------------------------------------------------------------

async def test_get_mediamtx_dep_menutup_client():
    from app.services.mediamtx import get_mediamtx_dep

    seen = []
    async for c in get_mediamtx_dep():
        seen.append(c)
        assert not c._client.is_closed
    assert seen[0]._client.is_closed


# ---------------------------------------------------------------------------
# 3.14: URL RTSP dengan newline ditolak sebelum ditulis ke file concat
# ---------------------------------------------------------------------------

async def test_ffprobe_tolak_newline():
    import importlib

    import app.services.rtsp_discovery as rd

    # Fixture autouse men-stub _run_ffprobe; muat ulang modul supaya
    # fungsi aslinya yang diuji.
    importlib.reload(rd)
    r = await rd._run_ffprobe("rtsp://admin:pw@127.0.0.1:554/x\nfile '/etc/passwd'")
    assert r.status == "error"


def test_poster_tolak_newline(monkeypatch, tmp_path):
    from app.services.posters import capture_poster

    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/ffmpeg")
    assert (
        capture_poster(1, "rtsp://x/y\nfile '/etc/passwd'", str(tmp_path / "s.jpg"))
        is False
    )


# ---------------------------------------------------------------------------
# 3.15: Digest cnonce acak
# ---------------------------------------------------------------------------

def test_digest_cnonce_acak():
    from app.services.stream_resolver import _digest_auth_value

    params = {"realm": "r", "nonce": "n123", "qop": "auth"}
    a = _digest_auth_value("admin", "pw", "DESCRIBE", "rtsp://h:554/x", params)
    b = _digest_auth_value("admin", "pw", "DESCRIBE", "rtsp://h:554/x", params)
    assert a != b  # cnonce acak per tantangan
    c = _digest_auth_value(
        "admin", "pw", "DESCRIBE", "rtsp://h:554/x", params, cnonce="tetap123"
    )
    d = _digest_auth_value(
        "admin", "pw", "DESCRIBE", "rtsp://h:554/x", params, cnonce="tetap123"
    )
    assert c == d


# ---------------------------------------------------------------------------
# 3.17: username brand di-quote, host divalidasi
# ---------------------------------------------------------------------------

def test_brand_user_diquote_dan_host_divalidasi():
    from app.services.brands import resolve_brand_urls

    main, _ = resolve_brand_urls("hikvision", "ad:min@x", "p@ss", "192.168.1.10")
    assert "ad%3Amin%40x" in main
    assert "p%40ss" in main
    with pytest.raises(ValueError):
        resolve_brand_urls("hikvision", "admin", "x", "192.168.1.10/evil")
    with pytest.raises(ValueError):
        resolve_brand_urls("hikvision", "admin", "x", "")


# ---------------------------------------------------------------------------
# 3.18: body HTML tautan pendek dibaca dengan batas
# ---------------------------------------------------------------------------

def _short_url_client(html: bytes, content_length: bool):
    import httpx

    class _Resp:
        url = "https://www.google.com/maps/place/x"
        status_code = 200
        headers = (
            {"content-length": str(len(html))} if content_length else {}
        )

        async def aiter_bytes(self, chunk_size=65536):
            for i in range(0, len(html), chunk_size):
                yield html[i : i + chunk_size]

    class _Ctx:
        def __init__(self, r):
            self._r = r

        async def __aenter__(self):
            return self._r

        async def __aexit__(self, *a):
            return False

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            return _Ctx(_Resp())

    return _FakeClient


async def test_resolve_short_url_batasi_html(monkeypatch):
    """3.18: koordinat yang baru muncul setelah batas 512 KB tidak dibaca."""
    import httpx

    import app.services.location as loc

    html = b"x" * (600 * 1024) + b"@-7.87,111.25"
    monkeypatch.setattr(httpx, "AsyncClient", _short_url_client(html, True))
    monkeypatch.setattr(loc, "_ip_is_public", lambda host: True)
    assert await loc.resolve_short_url("https://maps.app.goo.gl/abc123") is None


async def test_resolve_short_url_html_awal_dibaca(monkeypatch):
    """3.18: koordinat di awal body tetap ditemukan walau body besar."""
    import httpx

    import app.services.location as loc

    html = b"bla @-7.87,111.25 bla" + b"x" * (600 * 1024)
    monkeypatch.setattr(httpx, "AsyncClient", _short_url_client(html, False))
    monkeypatch.setattr(loc, "_ip_is_public", lambda host: True)
    assert await loc.resolve_short_url("https://maps.app.goo.gl/abc123") == (
        -7.87,
        111.25,
    )


# ---------------------------------------------------------------------------
# 3.20: get_paths validasi bentuk respons; ensure_path tahan balapan add
# ---------------------------------------------------------------------------

async def test_get_paths_tolak_dict_tanpa_items():
    from app.services.mediamtx import MediaMTXClient

    def h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    c = MediaMTXClient("http://127.0.0.1:9997", transport=httpx.MockTransport(h))
    assert await c.get_paths() == []


async def test_ensure_path_balapan_add():
    from app.services.mediamtx import MediaMTXClient

    calls = {"n": 0}

    def h(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if request.method == "GET" and p == "/v3/config/paths/get/stream_9":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(404, json={})
            return httpx.Response(
                200, json={"name": "stream_9", "source": "rtsp://lama"}
            )
        if request.method == "POST" and p.startswith("/v3/config/paths/add/"):
            return httpx.Response(409, json={"status": "error"})
        if request.method == "PATCH" and p.startswith("/v3/config/paths/patch/"):
            return httpx.Response(200, json={})
        return httpx.Response(500, json={})

    c = MediaMTXClient("http://127.0.0.1:9997", transport=httpx.MockTransport(h))
    # Add gagal 409 karena pemanggil lain sudah membuat path: lanjut ke
    # patch, bukan raise.
    await c.ensure_path("stream_9", {"source": "rtsp://baru"})
