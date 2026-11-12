"""Koneksi Google Drive via rclone, multi-remote.

User menempel token JSON dari `rclone authorize "drive"` (dijalankan di
komputer mereka yang ada browser) ke tombol "Hubungkan" di aplikasi.
Server menyimpan token sebagai satu section remote di .rclone.conf
(mis. [gdrive], [gdrive-2]), lalu meng-upload segmen rekaman langsung
via `rclone copyto`, tanpa FUSE mount, tanpa SSH.

Satu file conf boleh memuat BANYAK remote; save_token() hanya menambah
atau memperbarui section remote yang diminta, remote lain tidak disentuh.
Bila verifikasi remote baru gagal, conf lama dikembalikan utuh.

Token berisi refresh_token sehingga rclone memperbarui access_token
secara otomatis; koneksi tidak kedaluwarsa.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import stat
import time
import uuid
from pathlib import Path

log = logging.getLogger("netravision.gdrive_rclone")

REMOTE_NAME = "gdrive"

_REMOTE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SECTION_HDR = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def validate_remote_name(remote_name: str) -> str:
    """Validasi nama remote rclone; raise ValueError bila tidak valid."""
    name = (remote_name or "").strip()
    if not _REMOTE_RE.match(name):
        raise ValueError(
            "remote_name hanya boleh huruf, angka, '-' dan '_', maks 64 karakter."
        )
    return name


def _data_dir() -> str:
    """Direktori data API tempat .rclone.conf disimpan.

    B-T4: jangan bergantung pada CWD proses (berubah-ubah di container).
    Urutan: env RCLONE_DATA_DIR (atau NETRAVISION_DATA_DIR) -> data/ di bawah
    root package API (apps/api/data, stabil di native maupun container).
    Di deploy Docker, direktori ini di-mount ke volume `apidata` sehingga
    token tidak hilang saat container dibuat ulang.
    """
    override = os.environ.get("RCLONE_DATA_DIR") or os.environ.get(
        "NETRAVISION_DATA_DIR"
    )
    base = override or str(Path(__file__).resolve().parents[2] / "data")
    os.makedirs(base, exist_ok=True)
    return base


def conf_path() -> str:
    return os.path.join(_data_dir(), ".rclone.conf")


def find_rclone() -> str | None:
    """Lokasi biner rclone (PATH, ~/bin, /usr/bin)."""
    for candidate in (
        shutil.which("rclone"),
        os.path.expanduser("~/bin/rclone"),
        "/usr/bin/rclone",
        "/usr/local/bin/rclone",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


async def _run_rclone(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    """Jalankan rclone dengan config milik aplikasi. Return (rc, stdout, stderr)."""
    binary = find_rclone()
    if not binary:
        raise RuntimeError(
            "rclone tidak ditemukan di server. Minta admin menginstal rclone."
        )
    cmd = [binary, "--config", conf_path(), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("rclone timeout")
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


def _validate_token(token_json: str) -> dict:
    """Parse token JSON dari `rclone authorize "drive"`; raise ValueError
    bila bukan JSON valid atau tidak berisi refresh_token."""
    try:
        token = json.loads(token_json)
    except json.JSONDecodeError:
        raise ValueError(
            "Token bukan JSON valid. Salin seluruh output dari `rclone authorize \"drive\"`."
        )
    if not isinstance(token, dict) or not token.get("refresh_token"):
        raise ValueError(
            "Token tidak berisi refresh_token. Jalankan ulang `rclone authorize \"drive\"` "
            "dan salin seluruh outputnya."
        )
    return token


def _section_text(remote_name: str, token: dict) -> str:
    """Satu section conf untuk remote ini (token disimpan ringkas)."""
    compact = json.dumps(token, separators=(",", ":"))
    return (
        f"[{remote_name}]\n"
        f"type = drive\n"
        f"scope = drive\n"
        f"token = {compact}\n"
    )


def _upsert_section(content: str, remote_name: str, section: str) -> str:
    """Ganti section remote_name bila ada, tambah di akhir bila belum ada.

    Manipulasi baris per baris (bukan configparser) supaya section remote
    lain dipertahankan byte per byte, termasuk urutan dan komentarnya.
    """
    lines = content.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _SECTION_HDR.match(line)
        if m and m.group(1).strip() == remote_name:
            start = i
            break
    section_lines = section.rstrip("\n").splitlines()
    if start is None:
        if not content.strip():
            return section
        return content.rstrip("\n") + "\n\n" + section
    end = start + 1
    while end < len(lines):
        if _SECTION_HDR.match(lines[end]):
            break
        end += 1
    return "\n".join(lines[:start] + section_lines + lines[end:]) + "\n"


def _remove_section(content: str, remote_name: str) -> tuple[str, bool]:
    """Hapus section remote_name; return (conf_baru, ada_yang_dihapus)."""
    lines = content.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _SECTION_HDR.match(line)
        if m and m.group(1).strip() == remote_name:
            start = i
            break
    if start is None:
        return content, False
    end = start + 1
    while end < len(lines):
        if _SECTION_HDR.match(lines[end]):
            break
        end += 1
    rest = lines[:start] + lines[end:]
    return ("\n".join(rest) + "\n") if rest else "", True


def _read_conf() -> str | None:
    """Isi .rclone.conf, atau None bila file belum ada."""
    try:
        with open(conf_path()) as f:
            return f.read()
    except OSError:
        return None


def _write_conf_text(content: str) -> None:
    """Tulis isi conf apa adanya (0600)."""
    path = conf_path()
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _write_conf(token_json: str, remote_name: str = REMOTE_NAME) -> None:
    """Tulis section remote ke file config (0600), tanpa verifikasi.

    Dipakai internal; alur publik sebaiknya memakai save_token() yang
    memverifikasi dulu. Remote lain di conf dipertahankan.
    """
    token = _validate_token(token_json)
    remote_name = validate_remote_name(remote_name)
    content = _read_conf() or ""
    _write_conf_text(_upsert_section(content, remote_name, _section_text(remote_name, token)))


def list_remote_names() -> list[str]:
    """Nama semua remote (section) di .rclone.conf; [] bila conf tidak ada."""
    content = _read_conf()
    if not content:
        return []
    names: list[str] = []
    for line in content.splitlines():
        m = _SECTION_HDR.match(line)
        if m:
            names.append(m.group(1).strip())
    return names


def delete_remote(remote_name: str) -> bool:
    """Hapus section remote dari conf. Return True bila ada yang dihapus."""
    try:
        remote_name = validate_remote_name(remote_name)
    except ValueError:
        return False
    content = _read_conf()
    if not content:
        return False
    new_content, removed = _remove_section(content, remote_name)
    if not removed:
        return False
    if new_content.strip():
        _write_conf_text(new_content)
    else:
        try:
            os.remove(conf_path())
        except OSError:
            pass
    return True


async def save_token(token_json: str, remote_name: str = REMOTE_NAME) -> dict:
    """Simpan token sebagai section remote + verifikasi koneksi.

    Remote lain di conf dipertahankan. Bila verifikasi gagal, conf lama
    dikembalikan utuh (atau file dihapus bila sebelumnya tidak ada) dan
    RuntimeError dilempar. Return {email}.
    """
    token_json = (token_json or "").strip()
    if not token_json:
        raise ValueError("Token kosong.")
    remote_name = validate_remote_name(remote_name)
    token = _validate_token(token_json)
    old_content = _read_conf()
    _write_conf_text(
        _upsert_section(old_content or "", remote_name, _section_text(remote_name, token))
    )

    def _restore() -> None:
        if old_content is None:
            try:
                os.remove(conf_path())
            except OSError:
                pass
        else:
            _write_conf_text(old_content)

    try:
        rc, out, err = await _run_rclone("about", f"{remote_name}:", "--json", timeout=30)
    except RuntimeError:
        _restore()
        raise
    if rc != 0:
        _restore()
        detail = (err or out).strip().split("\n")[-1][:200]
        raise RuntimeError(f"Token ditolak Google: {detail}")
    email = ""
    try:
        # rclone about tidak mengembalikan email; coba via backend info
        rc2, out2, _ = await _run_rclone(
            "backend", "drives", f"{remote_name}:", timeout=30
        )
        if rc2 == 0:
            email = "terhubung"
    except Exception:  # noqa: BLE001
        pass
    return {"email": email or "terhubung"}


async def remote_status(remote_name: str) -> dict:
    """Status satu remote: {connected, email, remote_name, total/used/free_bytes}.

    Tidak pernah raise untuk rclone yang hilang atau remote yang tidak ada:
    kembalikan connected False dengan pesan error yang jelas, supaya
    endpoint status tidak crash bila rclone belum terinstal.
    """
    try:
        remote_name = validate_remote_name(remote_name)
    except ValueError as e:
        return {"connected": False, "email": "", "remote_name": remote_name, "error": str(e)}
    if remote_name not in list_remote_names():
        return {
            "connected": False,
            "email": "",
            "remote_name": remote_name,
            "error": f"remote '{remote_name}' tidak ada di .rclone.conf",
        }
    try:
        rc, out, err = await _run_rclone("about", f"{remote_name}:", "--json", timeout=20)
    except RuntimeError as e:
        return {"connected": False, "email": "", "remote_name": remote_name, "error": str(e)}
    if rc != 0:
        return {
            "connected": False,
            "email": "",
            "remote_name": remote_name,
            "error": (err or out).strip()[:200],
        }
    info: dict = {"connected": True, "email": "terhubung", "remote_name": remote_name}
    try:
        data = json.loads(out)
        for key in ("total", "used", "free"):
            if isinstance(data.get(key), int):
                info[f"{key}_bytes"] = data[key]
    except (ValueError, TypeError):
        pass
    return info


async def connection_status() -> dict:
    """{connected: bool, email: str} untuk remote default (gdrive)."""
    return await remote_status(REMOTE_NAME)


async def disconnect() -> None:
    if os.path.isfile(conf_path()):
        os.remove(conf_path())


async def check_folder_access(folder_id: str, remote_name: str = REMOTE_NAME) -> dict:
    """Pastikan folder bisa dibaca/ditulis akun terhubung. Return {name}."""
    rc, out, err = await _run_rclone(
        "lsd", f"{remote_name}:{folder_id}", "--max-depth", "0", timeout=30
    )
    if rc != 0:
        detail = (err or out).strip().split("\n")[-1][:200]
        raise RuntimeError(
            f"Folder tidak dapat diakses akun Google yang terhubung: {detail}. "
            "Pastikan folder dibagikan ke akun tersebut."
        )
    # Ambil nama folder via lsf
    rc2, out2, _ = await _run_rclone(
        "lsf", f"{remote_name}:{folder_id}", "--max-depth", "0", "--format", "p",
        timeout=30,
    )
    return {"name": out2.strip() if rc2 == 0 and out2.strip() else ""}


async def upload_segment(
    local_path: str,
    folder_id: str,
    remote_name: str = REMOTE_NAME,
    dest_name: str | None = None,
) -> None:
    """Upload satu file segmen ke folder Drive di remote yang diminta.

    remote_name adalah nama remote rclone (mis. gdrive, gdrive-2), BUKAN
    nama file. Bila dest_name diisi, file disimpan sebagai
    {folder_id}/{dest_name} di remote itu; bila tidak diisi, namanya
    basename(local_path).

    Kompatibilitas lama: drive_uploader.py memanggil dengan argumen ketiga
    berupa jalur tujuan "NamaKamera/nama-segmen.mp4" (mengandung "/").
    Bila argumen ketiga mengandung "/", anggap itu jalur tujuan lama dan
    pakai remote default. Raise RuntimeError bila gagal.
    """
    if dest_name is not None:
        remote = validate_remote_name(remote_name)
        dest = dest_name
    elif "/" in (remote_name or ""):
        remote = REMOTE_NAME
        dest = remote_name
    else:
        remote = validate_remote_name(remote_name)
        dest = os.path.basename(local_path)
    rc, out, err = await _run_rclone(
        "copyto", local_path, f"{remote}:{folder_id}/{dest}",
        "--transfers", "1",
        timeout=300,
    )
    if rc != 0:
        detail = (err or out).strip().split("\n")[-1][:200]
        raise RuntimeError(f"upload gagal: {detail}")


# ---------------------------------------------------------------------------
# Alur hubungkan akun via `rclone authorize` yang dijalankan server.
#
# Server menjalankan `rclone authorize "drive" --auth-no-open-browser`,
# lalu mencetak link http://127.0.0.1:53682/auth?state=... Pengguna
# membuka link itu di browser (butuh akses ke port 53682 server, mis.
# lewat SSH forward `ssh -L 53682:127.0.0.1:53682`), login Google,
# izinkan, lalu rclone menerima kode dan mencetak token JSON.
#
# Token TIDAK langsung disimpan di sini; job hanya menangkapnya. Frontend
# yang memanggil POST /admin/drive-remotes (yang sudah ada) untuk
# menyimpan token + membuat baris DB. Satu authorize dalam satu waktu
# karena port 53682 dipakai bersama. Job kedaluwarsa 10 menit.
# ---------------------------------------------------------------------------

_AUTHORIZE_JOBS: dict[str, dict] = {}
_AUTHORIZE_TIMEOUT_SEC = 600
_AUTH_URL_RE = re.compile(r"https?://127\.0\.0\.1:53682/auth\?state=\S+")


def authorize_job(job_id: str) -> dict | None:
    """Satu job authorize (atau None bila tidak ada)."""
    return _AUTHORIZE_JOBS.get(job_id)


async def cancel_authorize(job_id: str) -> dict | None:
    """Batalkan satu job authorize yang masih menunggu: matikan proses
    rclone authorize-nya lalu tandai dibatalkan. Return job atau None."""
    job = _AUTHORIZE_JOBS.get(job_id)
    if job is None:
        return None
    proc = job.get("proc")
    if proc is not None and proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    if job["status"] == "waiting":
        job["status"] = "cancelled"
        job["error"] = "Dibatalkan."
    return job


def _find_authorize_pids() -> list[int]:
    """PID semua proses `rclone authorize` yang sedang berjalan."""
    pids: list[int] = []
    try:
        names = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return pids
    for pid in names:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                parts = fh.read().split(b"\0")
        except OSError:
            continue
        args = [p.decode(errors="replace") for p in parts if p]
        if len(args) >= 2 and "rclone" in os.path.basename(args[0]) and "authorize" in args:
            pids.append(int(pid))
    return pids


def _kill_stale_authorize() -> int:
    """Matikan proses `rclone authorize` yang tertinggal (yatim, mis.
    dari API yang sudah restart) supaya port 53682 bebas dan authorize
    baru tidak langsung gagal. Return jumlah proses yang dimatikan."""
    import signal

    pids = _find_authorize_pids()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
    for _ in range(4):
        if not _find_authorize_pids():
            break
        time.sleep(0.5)
    else:
        for pid in _find_authorize_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                continue
        time.sleep(0.5)
    return len(pids)


async def start_authorize(remote_name: str, label: str = "") -> dict:
    """Mulai `rclone authorize "drive"` di background. Return {job_id}.

    Job lama yang masih menunggu dibatalkan dulu, dan proses `rclone
    authorize` yatim yang menahan port 53682 dimatikan dulu, supaya
    tidak ada yang tertahan: pengguna selalu bisa memulai lagi."""
    remote_name = validate_remote_name(remote_name)
    binary = find_rclone()
    if not binary:
        raise RuntimeError("rclone belum terinstal di server.")
    _kill_stale_authorize()
    for old in list(_AUTHORIZE_JOBS.values()):
        if old["status"] == "waiting":
            await cancel_authorize(old["job_id"])
    job_id = uuid.uuid4().hex[:12]
    job: dict = {
        "job_id": job_id,
        "remote_name": remote_name,
        "label": label,
        "status": "waiting",
        "auth_url": None,
        "token": None,
        "error": None,
        "proc": None,
        "started_at": time.time(),
    }
    _AUTHORIZE_JOBS[job_id] = job
    asyncio.create_task(_run_authorize(job, binary))
    return {"job_id": job_id}


async def _run_authorize(job: dict, binary: str) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "authorize",
            "drive",
            "--auth-no-open-browser",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        job["proc"] = proc
    except Exception as e:  # noqa: BLE001 - proses gagal start
        if job["status"] == "waiting":
            job["status"] = "error"
            job["error"] = f"Gagal menjalankan rclone authorize: {e}"
        return
    output_lines: list[str] = []
    try:
        while True:
            line = await asyncio.wait_for(
                proc.stdout.readline(), timeout=_AUTHORIZE_TIMEOUT_SEC
            )
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            output_lines.append(text)
            if job["auth_url"] is None:
                m = _AUTH_URL_RE.search(text)
                if m:
                    job["auth_url"] = m.group(0)
            if proc.returncode is not None:
                break
    except asyncio.TimeoutError:
        if job["status"] == "waiting":
            job["status"] = "error"
            job["error"] = "Waktu habis (10 menit). Klik lagi untuk mengulang."
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return
    await proc.wait()
    # Bila job sudah dibatalkan selagi task berjalan, jangan timpa statusnya.
    if job["status"] != "waiting":
        return
    if proc.returncode != 0:
        job["status"] = "error"
        job["error"] = "rclone authorize gagal. Coba lagi."
        return
    token_json = None
    for line in reversed(output_lines):
        line = line.strip()
        if line.startswith("{") and '"access_token"' in line:
            try:
                json.loads(line)
            except json.JSONDecodeError:
                continue
            token_json = line
            break
    if not token_json:
        job["status"] = "error"
        job["error"] = "Token tidak ditemukan di output rclone."
        return
    job["token"] = token_json
    job["status"] = "done"


_AUTHORIZE_PORT = 53682


def _in_docker() -> bool:
    """True bila proses jalan di dalam container Docker."""
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def _external_ip() -> str | None:
    """IP non-loopback utama (IP container di Docker). Dipakai proxy
    authorize supaya bisa di-bind tanpa bentrok dengan rclone yang
    sudah memakai 127.0.0.1:53682."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return None


async def _proxy_relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Teruskan satu arah stream ke writer; tutup bila selesai."""
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (asyncio.CancelledError, ConnectionError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _proxy_handle(
    client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
) -> None:
    """Satu koneksi masuk di IP container:53682 -> teruskan ke rclone
    di 127.0.0.1:53682, lalu relay dua arah sampai salah satu menutup."""
    try:
        rclone_reader, rclone_writer = await asyncio.open_connection(
            "127.0.0.1", _AUTHORIZE_PORT
        )
    except (OSError, asyncio.TimeoutError):
        try:
            client_writer.close()
        except Exception:
            pass
        return
    await asyncio.gather(
        _proxy_relay(client_reader, rclone_writer),
        _proxy_relay(rclone_reader, client_writer),
        return_exceptions=True,
    )
    try:
        client_writer.close()
    except Exception:
        pass
    try:
        rclone_writer.close()
    except Exception:
        pass


async def authorize_proxy_loop() -> None:
    """Penerus TCP permanen untuk `rclone authorize` di Docker.

    `rclone authorize` hanya listen di 127.0.0.1:53682, jadi docker-proxy
    (yang meneruskan ke IP container) tidak sampai. Proxy ini listen di
    IP container:53682 dan meneruskan tiap koneksi ke 127.0.0.1:53682.
    Hanya jalan di Docker; di deploy native SSH forward langsung sampai
    ke rclone tanpa proxy. Gagal bind hanya dicatat, API tetap jalan."""
    if not _in_docker():
        log.info("proxy authorize 53682 nonaktif (bukan Docker)")
        return
    ip = _external_ip()
    if not ip:
        log.warning("proxy authorize 53682 nonaktif (IP container tak ditemukan)")
        return
    try:
        server = await asyncio.start_server(
            _proxy_handle, ip, _AUTHORIZE_PORT
        )
    except OSError as e:
        log.warning("proxy authorize 53682 gagal bind %s: %s", ip, e)
        return
    log.info("proxy authorize 53682 listen di %s:%d", ip, _AUTHORIZE_PORT)
    async with server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            pass
