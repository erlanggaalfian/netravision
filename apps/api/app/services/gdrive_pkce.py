"""Koneksi Google Drive via OAuth PKCE langsung (tanpa pexpect, tanpa rclone config).

Alur:
1. POST /connect/start -> generate code_verifier/challenge (PKCE),
   return {session_id, auth_url}. Memakai client_id publik rclone
   (praktis untuk demo; produksi disarankan client_id sendiri).
2. User buka auth_url di browser, izinkan, salin kode.
3. POST /connect/finish {session_id, code} -> tukar kode via HTTP
   (PKCE, tanpa client_secret), tulis rclone.conf, verifikasi.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
import uuid

import httpx

log = logging.getLogger("netravision.gdrive_pkce")

# Client ID publik rclone (dari biner rclone). Untuk demo; produksi
# disarankan membuat client_id sendiri (shared ID dipensiunkan 2026).
RCLONE_CLIENT_ID = "202264815644.apps.googleusercontent.com"
SCOPE = "https://www.googleapis.com/auth/drive"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

_SESSIONS: dict[str, dict] = {}
_SESSION_TTL = 600


def _cleanup() -> None:
    now = time.time()
    for sid in [s for s, v in _SESSIONS.items() if now - v["created"] > _SESSION_TTL]:
        del _SESSIONS[sid]


async def start_session() -> dict:
    """Return {session_id, auth_url}."""
    _cleanup()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    params = {
        "client_id": RCLONE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)
    sid = uuid.uuid4().hex[:12]
    _SESSIONS[sid] = {"verifier": verifier, "created": time.time()}
    log.info("gdrive_pkce: sesi %s dimulai", sid)
    return {"session_id": sid, "auth_url": url}


async def finish_session(session_id: str, code: str) -> dict:
    """Tukar kode -> token, tulis rclone.conf, verifikasi."""
    _cleanup()
    sess = _SESSIONS.pop(session_id, None)
    if not sess:
        raise RuntimeError("Sesi kedaluwarsa/tidak ditemukan. Ulangi dari awal.")
    code = (code or "").strip()
    if not code:
        raise RuntimeError("Kode verifikasi kosong.")

    # Tukar kode dengan token (PKCE: tanpa client_secret)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": RCLONE_CLIENT_ID,
                "code_verifier": sess["verifier"],
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        try:
            err = resp.json().get("error_description") or resp.json().get("error")
        except Exception:  # noqa: BLE001
            err = resp.text[:200]
        raise RuntimeError(f"Google menolak kode: {err}")

    token = resp.json()
    if not token.get("refresh_token"):
        # Google kadang tidak mengirim refresh_token bila sudah pernah consent;
        # paksa dengan prompt=consent (sudah), atau minta user cabut akses dulu.
        raise RuntimeError(
            "Google tidak mengirim refresh_token. Cabut akses 'rclone' di "
            "myaccount.google.com/permissions lalu ulangi."
        )

    # Tulis rclone.conf (temuan 3.3): JANGAN hapus conf utuh dan JANGAN
    # tulis ke lokasi lain. Alur lama memakai `os.getcwd()/data` (bisa
    # berbeda dari `gdrive_rclone._data_dir()`, mis. `apps/api/data`)
    # dan `os.remove(conf)` sehingga semua remote lain (gdrive-2, dst.)
    # ikut hilang. Kini memakai `_write_conf` yang sama seperti
    # `save_token()`: hanya section `[gdrive]` yang di-upsert, remote
    # lain dipertahankan byte per byte. Bila verifikasi gagal, conf lama
    # dikembalikan utuh (bukan dihapus).
    from app.services import gdrive_rclone as gr  # noqa: PLC0415

    old_content = gr._read_conf()
    try:
        gr._write_conf(json.dumps(token), "gdrive")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Gagal menyimpan token: {e}") from e

    # Verifikasi
    st = await gr.connection_status()
    if not st.get("connected"):
        if old_content is None:
            try:
                os.remove(gr.conf_path())
            except OSError:
                pass
        else:
            gr._write_conf_text(old_content)
        raise RuntimeError(f"Verifikasi gagal: {st.get('error', 'unknown')}")
    log.info("gdrive_pkce: sesi %s terhubung", session_id)
    return {"ok": True}
