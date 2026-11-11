"""Koneksi Google Drive via rclone, alur sederhana tanpa Cloud Console.

User menempel token JSON dari `rclone authorize "drive"` (dijalankan di
komputer mereka yang ada browser) ke tombol "Hubungkan" di aplikasi.
Server menyimpan token sebagai remote rclone [gdrive], lalu meng-upload
segmen rekaman langsung via `rclone copyto`, tanpa FUSE mount, tanpa SSH.

Token berisi refresh_token sehingga rclone memperbarui access_token
secara otomatis; koneksi tidak kedaluwarsa.
"""

import asyncio
import json
import logging
import os
import shutil
import stat
from pathlib import Path

log = logging.getLogger("netravision.gdrive_rclone")

REMOTE_NAME = "gdrive"


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


def _write_conf(token_json: str) -> None:
    """Tulis [gdrive] remote ke file config (0600)."""
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
    # Simpan ulang sebagai JSON ringkas di dalam config rclone
    compact = json.dumps(token, separators=(",", ":"))
    content = (
        f"[{REMOTE_NAME}]\n"
        f"type = drive\n"
        f"scope = drive\n"
        f"token = {compact}\n"
    )
    path = conf_path()
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


async def save_token(token_json: str) -> dict:
    """Simpan token + verifikasi koneksi. Return {email}."""
    token_json = (token_json or "").strip()
    if not token_json:
        raise ValueError("Token kosong.")
    _write_conf(token_json)
    # Verifikasi: baca info akun
    rc, out, err = await _run_rclone("about", f"{REMOTE_NAME}:", "--json", timeout=30)
    if rc != 0:
        os.path.exists(conf_path()) and os.remove(conf_path())
        detail = (err or out).strip().split("\n")[-1][:200]
        raise RuntimeError(f"Token ditolak Google: {detail}")
    email = ""
    try:
        # rclone about tidak mengembalikan email; coba via backend info
        rc2, out2, _ = await _run_rclone(
            "backend", "drives", f"{REMOTE_NAME}:", timeout=30
        )
        if rc2 == 0:
            email = "terhubung"
    except Exception:  # noqa: BLE001
        pass
    return {"email": email or "terhubung"}


async def connection_status() -> dict:
    """{connected: bool, email: str}."""
    if not os.path.isfile(conf_path()):
        return {"connected": False, "email": ""}
    rc, out, err = await _run_rclone("about", f"{REMOTE_NAME}:", "--json", timeout=20)
    if rc != 0:
        return {"connected": False, "email": "", "error": (err or out).strip()[:200]}
    return {"connected": True, "email": "terhubung"}


async def disconnect() -> None:
    if os.path.isfile(conf_path()):
        os.remove(conf_path())


async def check_folder_access(folder_id: str) -> dict:
    """Pastikan folder bisa dibaca/ditulis akun terhubung. Return {name}."""
    rc, out, err = await _run_rclone(
        "lsd", f"{REMOTE_NAME}:{folder_id}", "--max-depth", "0", timeout=30
    )
    if rc != 0:
        detail = (err or out).strip().split("\n")[-1][:200]
        raise RuntimeError(
            f"Folder tidak dapat diakses akun Google yang terhubung: {detail}. "
            "Pastikan folder dibagikan ke akun tersebut."
        )
    # Ambil nama folder via lsf
    rc2, out2, _ = await _run_rclone(
        "lsf", f"{REMOTE_NAME}:{folder_id}", "--max-depth", "0", "--format", "p",
        timeout=30,
    )
    return {"name": out2.strip() if rc2 == 0 and out2.strip() else ""}


async def upload_segment(local_path: str, folder_id: str, remote_name: str) -> None:
    """Upload satu file segmen ke folder Drive. Raise RuntimeError bila gagal."""
    rc, out, err = await _run_rclone(
        "copyto", local_path, f"{REMOTE_NAME}:{folder_id}/{remote_name}",
        "--transfers", "1",
        timeout=300,
    )
    if rc != 0:
        detail = (err or out).strip().split("\n")[-1][:200]
        raise RuntimeError(f"upload gagal: {detail}")
