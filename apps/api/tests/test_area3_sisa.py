"""Tes perbaikan sisa Area 3 (Service layer), 2026-11-17.

Nomor temuan mengacu pada BACKEND_DB_AUDIT_2026-11-17.md bagian Area 3.
File ini melengkapi tests/test_area3_fixes.py untuk temuan yang dulu
hanya parsial: 3.11 (resume resumable sejati), 3.18 (pinning DNS
penuh), 3.13 (_kill_stale_authorize + pembersihan job).
"""

import asyncio
import os
import socket
import subprocess
import time

import httpx
import pytest


# ---------------------------------------------------------------------------
# 3.11: resume resumable sejati (drive.py)
# ---------------------------------------------------------------------------

class _FakeResumableRequest:
    """Meniru HttpRequest googleapiclient: next_chunk lanjut dari progres.

    Satu objek request untuk seluruh upload: resumable_uri dan
    resumable_progress dipertahankan antar percobaan, seperti
    HttpRequest asli. next_chunk yang gagal mensimulasikan chunk yang
    responsnya hilang (progres server sudah maju).
    """

    def __init__(self, fail_first: int = 1):
        self.resumable_uri = "https://upload.example/session-1"
        self.resumable_progress = 0
        self.next_chunk_calls = 0
        self._fail_left = fail_first

    def next_chunk(self):
        self.next_chunk_calls += 1
        if self._fail_left > 0:
            self._fail_left -= 1
            self.resumable_progress += 1024
            raise RuntimeError("koneksi putus (simulasi)")
        return (None, {"id": "f-resume"})


def _resumable_drive(monkeypatch, fail_first: int = 1):
    """FakeDrive yang upload filenya memakai request resumable."""
    from tests.test_drive import FOLDER_MIME, FakeDrive

    svc = FakeDrive()
    created: list[_FakeResumableRequest] = []
    orig_create = svc.create

    def _create(body=None, media_body=None, fields=None):
        if body and body.get("mimeType") == FOLDER_MIME:
            return orig_create(body=body, media_body=media_body, fields=fields)
        req = _FakeResumableRequest(fail_first=fail_first)
        created.append(req)
        return req

    svc.create = _create
    # Backoff retry 2 dtk/percobaan tidak perlu ditunggu di tes.
    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    return svc, created


async def test_upload_resume_pakai_request_yang_sama(tmp_path, monkeypatch):
    """3.11: chunk gagal dilanjutkan pada request yang sama, bukan
    request baru dari byte 0."""
    from tests.test_drive import _settings
    from app.services.drive import DriveUploader

    svc, created = _resumable_drive(monkeypatch, fail_first=1)
    up = DriveUploader(settings=_settings(), service=svc)
    p = tmp_path / "seg.mp4"
    p.write_bytes(b"v" * 2048)
    fid = await up.upload_file(str(p), "Cam A", retries=3)
    assert fid == "f-resume"
    assert len(created) == 1  # SATU request untuk seluruh percobaan
    assert created[0].next_chunk_calls == 2
    assert created[0].resumable_progress == 1024  # lanjut, bukan ulang
    assert not p.exists()  # lokal dihapus setelah sukses


async def test_upload_resume_tidak_duplikat_bila_file_muncul(tmp_path, monkeypatch):
    """3.11: bila find_file menemukan file sebelum retry, request
    resumable tidak dibuat ulang dan tidak ada duplikat."""
    from tests.test_drive import _settings
    from app.services.drive import DriveUploader

    svc, created = _resumable_drive(monkeypatch, fail_first=99)
    up = DriveUploader(settings=_settings(), service=svc)
    p = tmp_path / "seg.mp4"
    p.write_bytes(b"v")
    calls = {"n": 0}
    orig_find = up.find_file

    async def _find(folder_id, name):
        calls["n"] += 1
        if calls["n"] >= 2:
            return "f-ada"  # ternyata sudah sampai di Drive
        return await orig_find(folder_id, name)

    up.find_file = _find
    fid = await up.upload_file(str(p), "Cam A", retries=3)
    assert fid == "f-ada"
    assert len(created) == 1
    assert not p.exists()


async def test_upload_chunk_timeout_per_chunk(monkeypatch):
    """3.11: tiap chunk next_chunk punya timeout sendiri."""
    import app.services.drive as d

    monkeypatch.setattr(d, "_DRIVE_API_TIMEOUT_SEC", 0.05)

    class _SlowRequest:
        def next_chunk(self):
            time.sleep(2)
            return (None, {"id": "f-lambat"})

    from app.services.drive import DriveUploader
    from tests.test_drive import FakeDrive, _settings

    up = DriveUploader(settings=_settings(), service=FakeDrive())
    with pytest.raises(asyncio.TimeoutError):
        await up._drive_upload_request(_SlowRequest())


async def test_upload_request_tanpa_next_chunk_pakai_execute(tmp_path):
    """3.11: request tanpa next_chunk (mock/fake) tetap bisa upload
    lewat execute(), supaya FakeDrive lama tetap jalan."""
    from tests.test_drive import FakeDrive, _settings
    from app.services.drive import DriveUploader

    up = DriveUploader(settings=_settings(), service=FakeDrive())
    p = tmp_path / "seg.mp4"
    p.write_bytes(b"v")
    fid = await up.upload_file(str(p), "Cam A", retries=2)
    assert fid is not None
    assert not p.exists()


# ---------------------------------------------------------------------------
# 3.18: pinning DNS penuh (location.py)
# ---------------------------------------------------------------------------

def _fake_getaddrinfo(addrs):
    def _fake(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in addrs]

    return _fake


def test_resolve_public_ip(monkeypatch):
    import app.services.location as loc

    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"])
    )
    assert loc._resolve_public_ip("example.com") == "93.184.216.34"

    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo(["10.0.0.1"])
    )
    assert loc._resolve_public_ip("example.com") is None

    # Jawaban bercampur IP privat ditolak seluruhnya oleh gate.
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34", "10.0.0.1"])
    )
    assert loc._resolve_public_ip("example.com") is None

    def _boom(host, port, *a, **k):
        raise socket.gaierror("tidak ketemu")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    assert loc._resolve_public_ip("example.com") is None


async def test_pinned_transport_tulis_ulang_url_dan_sni(monkeypatch):
    """3.18: transport pin menulis ulang host URL ke IP pin, menjaga
    Host header dan SNI tetap nama host asli."""
    import app.services.location as loc

    seen: dict = {}

    async def _fake_super(self, request):
        seen["url"] = str(request.url)
        seen["host"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, request=request)

    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", _fake_super
    )
    t = loc._PinnedIPTransport({"maps.app.goo.gl": "93.184.216.34"})
    req = httpx.Request("GET", "https://maps.app.goo.gl/abc123")
    await t.handle_async_request(req)
    assert seen["url"] == "https://93.184.216.34/abc123"
    assert seen["host"] == "maps.app.goo.gl"
    assert seen["sni"] == "maps.app.goo.gl"

    # Host yang tidak di-pin diteruskan apa adanya.
    seen.clear()
    req2 = httpx.Request("GET", "https://example.com/x")
    await t.handle_async_request(req2)
    assert seen["url"] == "https://example.com/x"
    assert seen.get("sni") is None


def _short_url_fake_client(instances, routes):
    """Fake httpx.AsyncClient: rekam transport tiap hop, jawab per URL."""

    class _Resp:
        def __init__(self, url, status_code, headers, body=b""):
            self.url = url
            self.status_code = status_code
            self.headers = headers
            self._body = body

        async def aiter_bytes(self, chunk_size=65536):
            if self._body:
                yield self._body

    class _Ctx:
        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, *a):
            return False

    class _FakeClient:
        def __init__(self, *a, **k):
            self.kwargs = k
            instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, **k):
            return _Ctx(routes(str(url)))

    return _FakeClient


async def test_resolve_short_url_pakai_transport_pin(monkeypatch):
    """3.18: tiap hop memakai transport dengan IP pin host itu."""
    import httpx

    import app.services.location as loc

    pins = {"maps.app.goo.gl": "93.184.216.34", "www.google.com": "142.250.80.4"}
    monkeypatch.setattr(loc, "_ip_is_public", lambda host: True)
    monkeypatch.setattr(loc, "_resolve_public_ip", lambda host: pins.get(host))

    def _routes(url):
        if "maps.app.goo.gl" in url:
            return type(
                "R", (), {
                    "url": "https://maps.app.goo.gl/abc123",
                    "status_code": 302,
                    "headers": {
                        "location": "https://www.google.com/maps/@-7.87,111.25,15z"
                    },
                    "aiter_bytes": lambda self, chunk_size=65536: _empty(),
                }
            )()

        return type(
            "R", (), {
                "url": "https://www.google.com/maps/@-7.87,111.25,15z",
                "status_code": 200,
                "headers": {},
                "aiter_bytes": lambda self, chunk_size=65536: _empty(),
            }
        )()

    async def _empty():
        if False:
            yield b""

    instances: list = []
    monkeypatch.setattr(
        httpx, "AsyncClient", _short_url_fake_client(instances, _routes)
    )
    got = await loc.resolve_short_url("https://maps.app.goo.gl/abc123")
    assert got == (-7.87, 111.25)
    assert len(instances) == 2  # satu client per hop, pin per hop
    assert isinstance(instances[0].kwargs.get("transport"), loc._PinnedIPTransport)
    assert instances[0].kwargs["transport"]._pinned == {
        "maps.app.goo.gl": "93.184.216.34"
    }
    assert instances[1].kwargs["transport"]._pinned == {
        "www.google.com": "142.250.80.4"
    }


async def test_resolve_short_url_tanpa_pin_bila_dns_gagal(monkeypatch):
    """3.18: bila pin tidak bisa dibuat, fetch tetap jalan lewat gate
    _ip_is_public (fallback terdokumentasi, bukan gagal total)."""
    import httpx

    import app.services.location as loc

    monkeypatch.setattr(loc, "_ip_is_public", lambda host: True)
    monkeypatch.setattr(loc, "_resolve_public_ip", lambda host: None)

    def _routes(url):
        async def _body(chunk_size=65536):
            yield b"bla @-7.87,111.25 bla"

        return type(
            "R", (), {
                "url": "https://www.google.com/maps/@-7.87,111.25,15z",
                "status_code": 200,
                "headers": {},
                "aiter_bytes": lambda self, chunk_size=65536: _body(),
            }
        )()

    instances: list = []
    monkeypatch.setattr(
        httpx, "AsyncClient", _short_url_fake_client(instances, _routes)
    )
    got = await loc.resolve_short_url("https://maps.app.goo.gl/abc123")
    assert got == (-7.87, 111.25)
    assert instances[0].kwargs.get("transport") is None


# ---------------------------------------------------------------------------
# 3.13: _kill_stale_authorize + pembersihan job (gdrive_rclone.py)
# ---------------------------------------------------------------------------

def _fake_rclone_script(tmp_path) -> str:
    """Skrip bernama `rclone` yang cmdline-nya `rclone ... authorize`.

    Dipakai membuktikan _kill_stale_authorize lama (pindai /proc)
    akan mematikan proses ini, sementara versi baru tidak boleh.
    """
    script = tmp_path / "rclone"
    script.write_text(
        "#!/bin/bash\n"
        'exec -a rclone python3 -c "import time; time.sleep(30)" '
        "authorize drive\n"
    )
    script.chmod(0o755)
    return str(script)


def _start_fake_rclone_authorize(tmp_path):
    proc = subprocess.Popen([_fake_rclone_script(tmp_path)])
    for _ in range(50):
        if proc.poll() is not None:
            raise RuntimeError("proses rclone palsu langsung mati")
        try:
            with open(f"/proc/{proc.pid}/cmdline", "rb") as fh:
                parts = fh.read().split(b"\0")
            args = [p.decode(errors="replace") for p in parts if p]
            if args and "rclone" in os.path.basename(args[0]):
                break
        except OSError:
            pass
        time.sleep(0.1)
    return proc


def test_kill_stale_tidak_bunuh_proses_tak_tercatat(tmp_path):
    """3.13: proses `rclone authorize` yang TIDAK dicatat job ini
    tidak dimatikan (dulu pindai /proc mematikan semuanya)."""
    from app.services import gdrive_rclone as gr

    proc = _start_fake_rclone_authorize(tmp_path)
    try:
        # Sanity: cmdline proses ini cocok dengan pola yang dulu
        # dipakai _find_authorize_pids untuk membunuh.
        with open(f"/proc/{proc.pid}/cmdline", "rb") as fh:
            args = [p.decode(errors="replace") for p in fh.read().split(b"\0") if p]
        assert "rclone" in os.path.basename(args[0])
        assert "authorize" in args
        gr._AUTHORIZE_JOBS.clear()
        assert gr._kill_stale_authorize() == 0
        assert proc.poll() is None  # masih hidup
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        gr._AUTHORIZE_JOBS.clear()


def test_kill_stale_bunuh_pid_terminal_tercatat(tmp_path):
    """3.13: proses yang PID-nya dicatat job terminal tetap dimatikan."""
    from app.services import gdrive_rclone as gr

    proc = _start_fake_rclone_authorize(tmp_path)
    gr._AUTHORIZE_JOBS.clear()
    try:
        gr._AUTHORIZE_JOBS["j1"] = {
            "job_id": "j1",
            "status": "done",
            "pid": proc.pid,
            "proc": None,
            "finished_at": time.time(),
        }
        assert gr._kill_stale_authorize() == 1
        assert proc.poll() is not None  # sudah mati
        assert gr._AUTHORIZE_JOBS["j1"]["pid"] is None
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        gr._AUTHORIZE_JOBS.clear()


def test_kill_stale_lewati_job_waiting():
    """3.13: proses milik job yang masih menunggu tidak disentuh
    (pembatalannya lewat cancel_authorize, bukan stale killer)."""
    from app.services import gdrive_rclone as gr

    proc = subprocess.Popen(["sleep", "30"])
    gr._AUTHORIZE_JOBS.clear()
    try:
        gr._AUTHORIZE_JOBS["w1"] = {
            "job_id": "w1",
            "status": "waiting",
            "pid": proc.pid,
            "proc": None,
        }
        assert gr._kill_stale_authorize() == 0
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        gr._AUTHORIZE_JOBS.clear()


def test_authorize_job_hapus_setelah_dibaca():
    """3.13: job terminal dihapus dari registry begitu dibaca; job
    menunggu tetap bisa di-poll."""
    from app.services import gdrive_rclone as gr

    gr._AUTHORIZE_JOBS.clear()
    try:
        now = time.time()
        gr._AUTHORIZE_JOBS["done1"] = {
            "job_id": "done1", "status": "done", "token": "t",
            "proc": None, "finished_at": now,
        }
        gr._AUTHORIZE_JOBS["err1"] = {
            "job_id": "err1", "status": "error", "error": "e",
            "proc": None, "finished_at": now,
        }
        gr._AUTHORIZE_JOBS["can1"] = {
            "job_id": "can1", "status": "cancelled",
            "proc": None, "finished_at": now,
        }
        gr._AUTHORIZE_JOBS["wait1"] = {
            "job_id": "wait1", "status": "waiting", "proc": None,
        }
        got = gr.authorize_job("done1")
        assert got is not None and got["status"] == "done"
        assert "proc" not in got
        assert gr.authorize_job("done1") is None
        assert gr.authorize_job("err1") is not None
        assert gr.authorize_job("err1") is None
        assert gr.authorize_job("can1") is not None
        assert gr.authorize_job("can1") is None
        assert gr.authorize_job("wait1") is not None
        assert gr.authorize_job("wait1") is not None  # tetap ada
        assert set(gr._AUTHORIZE_JOBS) == {"wait1"}
    finally:
        gr._AUTHORIZE_JOBS.clear()


async def test_start_authorize_pakai_lock_dan_catat_pid(tmp_path, monkeypatch):
    """3.13: start_authorize berjalan di dalam _AUTHORIZE_LOCK dan
    job mencatat PID prosesnya; setelah selesai PID dibersihkan."""
    from app.services import gdrive_rclone as gr

    script = tmp_path / "rclone"
    script.write_text(
        "#!/bin/sh\n"
        "echo 'http://127.0.0.1:53682/auth?state=abc'\n"
        "echo '{\"access_token\": \"tok\", \"refresh_token\": \"r\"}'\n"
    )
    script.chmod(0o755)
    monkeypatch.setattr(gr, "find_rclone", lambda: str(script))
    monkeypatch.setattr(gr, "_authorize_port_busy", lambda: False)
    seen: dict = {}
    orig_kill = gr._kill_stale_authorize

    def _spy_kill():
        seen["locked"] = gr._AUTHORIZE_LOCK.locked()
        return orig_kill()

    monkeypatch.setattr(gr, "_kill_stale_authorize", _spy_kill)
    gr._AUTHORIZE_JOBS.clear()
    try:
        out = await gr.start_authorize("gdrive", "Tes")
        job_id = out["job_id"]
        assert seen.get("locked") is True
        job = None
        for _ in range(100):
            job = gr._AUTHORIZE_JOBS.get(job_id)
            if job is not None and job["status"] != "waiting":
                break
            await asyncio.sleep(0.1)
        assert job is not None
        assert job["status"] == "done"
        assert job["auth_url"] == "http://127.0.0.1:53682/auth?state=abc"
        assert job["token"] is not None and "access_token" in job["token"]
        assert job["pid"] is None  # proses sudah mati, PID dibersihkan
    finally:
        gr._AUTHORIZE_JOBS.clear()


async def test_start_authorize_gagal_bila_port_sibuk(monkeypatch):
    """3.13: bila port 53682 dipakai proses lain, start gagal dengan
    pesan jelas, bukan mematikan proses itu."""
    from app.services import gdrive_rclone as gr

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 53682))
    except OSError:
        pytest.skip("port 53682 sudah dipakai di lingkungan tes")
    listener.listen(1)
    monkeypatch.setattr(gr, "find_rclone", lambda: "/bin/true")
    gr._AUTHORIZE_JOBS.clear()
    try:
        with pytest.raises(RuntimeError, match="53682"):
            await gr.start_authorize("gdrive", "Tes")
        assert gr._AUTHORIZE_JOBS == {}
    finally:
        listener.close()
        gr._AUTHORIZE_JOBS.clear()
