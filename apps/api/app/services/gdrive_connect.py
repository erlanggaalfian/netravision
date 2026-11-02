"""Koneksi Google Drive via `rclone config` otomatis di server.

Alur (tanpa instal rclone lokal, tanpa SSH, tanpa Cloud Console):
1. POST /connect/start -> backend menjalankan `rclone config` via pty,
   menjawab semua prompt otomatis sampai URL auth Google muncul.
   Return {session_id, auth_url}.
2. User buka auth_url di browser HP/laptop, login Google, izinkan,
   salin kode verifikasi.
3. POST /connect/finish {session_id, code} -> backend memasukkan kode
   ke proses rclone, menyelesaikan config, verifikasi koneksi.
   Return {ok: true}.

Catatan: memakai shared client_id rclone (praktis untuk demo; rclone
menyatakan akan dipensiunkan selama 2026 — untuk produksi disarankan
client_id sendiri).
"""

import logging
import os
import re
import stat
import time
import uuid

log = logging.getLogger("netravision.gdrive_connect")

_SESSIONS: dict[str, dict] = {}
_SESSION_TTL = 600  # 10 menit


def _rclone_bin() -> str | None:
    import shutil

    for c in (
        shutil.which("rclone"),
        os.path.expanduser("~/bin/rclone"),
        "/usr/bin/rclone",
        "/usr/local/bin/rclone",
    ):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _conf_path() -> str:

    d = os.path.join(os.getcwd(), "data")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, ".rclone.conf")


def _cleanup_expired() -> None:
    now = time.time()
    for sid in [s for s, v in _SESSIONS.items() if now - v["created"] > _SESSION_TTL]:
        try:
            _SESSIONS[sid]["child"].close(force=True)
        except Exception:  # noqa: BLE001
            pass
        del _SESSIONS[sid]


async def start_session() -> dict:
    """Mulai sesi config rclone, kembalikan {session_id, auth_url}."""
    try:
        import pexpect  # noqa: PLC0415
    except ImportError:
        raise RuntimeError("pexpect belum terinstal di server")

    binary = _rclone_bin()
    if not binary:
        raise RuntimeError("rclone tidak ditemukan di server")

    _cleanup_expired()
    # Hapus config lama agar sesi baru bersih
    conf = _conf_path()
    if os.path.exists(conf):
        os.remove(conf)

    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
    child = pexpect.spawn(
        binary, ["config", "--config", conf],
        encoding="utf-8", timeout=20, env=env,
    )

    def step(patterns: list[str], send: str, desc: str) -> None:
        idx = child.expect(patterns + [pexpect.TIMEOUT], timeout=20)
        if idx >= len(patterns):
            raise RuntimeError(f"Timeout pada langkah: {desc}")
        child.sendline(send)

    try:
        # 1. New remote
        step([r"n/s/q"], "n", "new remote")
        # 2. Nama
        step([r"Enter name", r"name>"], "gdrive", "nama remote")
        # 3. Storage type — daftar panjang, tunggu prompt
        step([r"Storage>"], "drive", "storage drive")
        # 4-5. client_id/secret kosong (pakai shared rclone)
        step([r"client_id"], "", "client_id")
        # Tangani interupsi "Create your own" bila muncul
        idx = child.expect([r"client_secret", r"Create your own", pexpect.TIMEOUT], timeout=20)
        if idx == 1:
            # Jawab 'n'/Enter untuk lanjut dengan shared client_id
            child.sendline("")
            child.expect(r"client_secret", timeout=20)
        elif idx == 2:
            raise RuntimeError("Timeout pada langkah: client_secret")
        child.sendline("")
        # 6. Scope: pilih 1 (full access)
        # Tunggu prompt scope> yang sebenarnya
        child.expect(r"scope> ", timeout=20)
        child.sendline("1")
        # 7. service_account_file kosong
        step([r"service_account_file"], "", "service_account")
        # 8. root_folder_id (mungkin tidak ditanya di 1.75 — opsional)
        idx = child.expect([r"root_folder_id", r"advanced config", r"y/n"], timeout=15)
        if idx == 0:
            child.sendline("")
            child.expect([r"advanced config", r"y/n"], timeout=15)
        # 9. Edit advanced config? -> n
        # (sudah di prompt y/n)
        child.sendline("n")
        # 10. Use web browser? -> n (headless)
        child.expect(r"web browser", timeout=15)
        child.sendline("n")
        # 11. Tangkap URL auth
        child.expect(r"https://accounts\.google\.com/\S+", timeout=20)
        url = re.sub(r"\x1b\[[0-9;]*m", "", child.after).strip()

        sid = uuid.uuid4().hex[:12]
        _SESSIONS[sid] = {"child": child, "created": time.time()}
        log.info("gdrive_connect: sesi %s dimulai", sid)
        return {"session_id": sid, "auth_url": url}
    except Exception:
        try:
            child.close(force=True)
        except Exception:  # noqa: BLE001
            pass
        raise


async def finish_session(session_id: str, code: str) -> dict:
    """Selesaikan sesi dengan kode verifikasi dari user."""
    try:
        import pexpect  # noqa: PLC0415
    except ImportError:
        raise RuntimeError("pexpect belum terinstal di server")

    _cleanup_expired()
    sess = _SESSIONS.pop(session_id, None)
    if not sess:
        raise RuntimeError("Sesi kedaluwarsa/tidak ditemukan. Ulangi dari awal.")
    child = sess["child"]
    code = (code or "").strip()
    if not code:
        raise RuntimeError("Kode verifikasi kosong.")

    try:
        # Masukkan kode ke prompt "Enter verification code"
        child.expect(r"verification code", timeout=10)
        child.sendline(code)
        # Tunggu selesai: "Configure this as a team drive?" -> n
        idx = child.expect([r"team drive", pexpect.TIMEOUT], timeout=30)
        if idx == 0:
            child.sendline("n")
        # Konfirmasi simpan: "y/e/d>" -> y
        idx = child.expect([r"y/e/d", r"y/n", pexpect.TIMEOUT], timeout=15)
        if idx < 2:
            child.sendline("y")
        # Tunggu proses selesai
        child.expect(pexpect.EOF, timeout=15)

        # Amankan permission config
        conf = _conf_path()
        if os.path.exists(conf):
            os.chmod(conf, stat.S_IRUSR | stat.S_IWUSR)
        else:
            raise RuntimeError("Config rclone tidak terbentuk. Kode mungkin salah.")

        # Verifikasi koneksi
        from app.services import gdrive_rclone as gr  # noqa: PLC0415

        st = await gr.connection_status()
        if not st.get("connected"):
            raise RuntimeError(f"Verifikasi gagal: {st.get('error', 'unknown')}")
        log.info("gdrive_connect: sesi %s terhubung", session_id)
        return {"ok": True}
    except pexpect.TIMEOUT as e:
        raise RuntimeError("Timeout menunggu rclone. Coba ulangi.") from e
    finally:
        try:
            child.close(force=True)
        except Exception:  # noqa: BLE001
            pass
