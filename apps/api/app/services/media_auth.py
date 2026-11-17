"""Token media per-stream (K-1): live stream tanpa auth.

Latar: Apache mem-proxy /whep/ dan /hls/ langsung ke MediaMTX, jadi siapa
pun bisa membuka URL live stream tanpa login. Penutupnya adalah proxy API
(app/routers/media.py): Apache dialihkan ke API, API memvalidasi kredensial
dulu baru meneruskan request ke MediaMTX.

Modul ini berisi logika tokennya (tanpa dependensi FastAPI/DB supaya mudah
dites):
- token media: JWT singkat (default 60 menit, sama seperti TTL sesi embed)
  yang TERIKAT ke satu path MediaMTX (stream_{id} atau stream_{id}_sub).
  Token kamera A tidak bisa dipakai untuk kamera B, dan tidak bisa dipakai
  sebagai token login (type "media", bukan "access").
- token sesi embed (?session=) tetap dipakai apa adanya oleh halaman
  embed: validatornya sudah ada di app/routers/external.py.
- penulisan ulang playlist HLS: hls.js mengambil segmen lewat URL relatif
  dari playlist, jadi kredensial harus ditempel ke tiap URI di playlist
  (.m3u8) oleh proxy, kalau tidak segmennya ditolak 401.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit, urlunsplit

import jwt

from app.core.config import Settings
from app.core.security import decode_token

# Umur token media: 60 menit, sama seperti TTL sesi embed default
# (app/routers/external.py _DEFAULT_TTL_MNT). Cukup untuk satu sesi
# menonton; frontend meminta token baru tiap mulai/retry playback.
MEDIA_TOKEN_TTL_SECONDS = 3600

# Path MediaMTX yang sah: stream_{id} (main) atau stream_{id}_sub (sub).
# Pola ini sekaligus menolak path traversal (.., /, dst.) ke proxy.
MEDIA_PATH_RE = re.compile(r"^stream_(\d+)(_sub)?$")

# Segmen HLS tidak boleh lebih besar dari ini; pelindung supaya proxy
# tidak memuat blob raksasa ke RAM bila upstream menjawab aneh.
MAX_PROXY_BODY_BYTES = 64 * 1024 * 1024


def parse_media_path(path: str) -> tuple[int, bool]:
    """Validasi nama path MediaMTX. Return (stream_id, is_sub).

    Raise ValueError bila bukan stream_{id} atau stream_{id}_sub.
    """
    m = MEDIA_PATH_RE.match(path or "")
    if not m:
        raise ValueError("path media tidak valid")
    stream_id = int(m.group(1))
    if stream_id <= 0:
        raise ValueError("path media tidak valid")
    return stream_id, m.group(2) == "_sub"


def media_path_for(stream_id: int, sub: bool) -> str:
    """Nama path MediaMTX untuk satu kamera (main atau sub)."""
    return f"stream_{stream_id}_sub" if sub else f"stream_{stream_id}"


def create_media_token(
    settings: Settings,
    *,
    subject: str,
    stream_id: int,
    path: str,
    ttl_seconds: int = MEDIA_TOKEN_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Terbitkan token media untuk satu path. Return (token, expires_at).

    subject: id user sebagai string (str(user.id)). Token embed tidak
    memakai fungsi ini: embed memakai token sesi dari external.py.
    """
    path_stream_id, _ = parse_media_path(path)
    if path_stream_id != stream_id:
        raise ValueError("stream_id tidak cocok dengan path")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
    payload = {
        "sub": str(subject),
        "type": "media",
        "kind": "media",
        "stream_id": int(stream_id),
        "path": path,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_at


def validate_media_token(token: str, settings: Settings) -> dict:
    """Validasi token media. Return payload bila sah.

    Raise ValueError bila signature/kedaluwarsa salah, bukan token
    media, stream_id bukan angka, atau path tidak cocok dengan
    stream_id. decode_token sudah menolak token tanpa exp/iat/sub.
    """
    payload = decode_token(token, settings)
    if payload.get("type") != "media" or payload.get("kind") != "media":
        raise ValueError("bukan token media")
    stream_id = payload.get("stream_id")
    if not isinstance(stream_id, int) or isinstance(stream_id, bool):
        raise ValueError("token media tidak valid")
    path = payload.get("path")
    if not isinstance(path, str):
        raise ValueError("token media tidak valid")
    path_stream_id, _ = parse_media_path(path)
    if path_stream_id != stream_id:
        raise ValueError("token media bukan untuk path ini")
    return payload


def credential_query(token: str | None, session: str | None) -> str | None:
    """Bentuk query kredensial (?token= / ?session=) untuk ditempel ke URL.

    Dipakai penulisan ulang playlist: segmen HLS harus membawa kredensial
    yang sama dengan playlist-nya. Return None bila tidak ada kredensial.
    """
    if token:
        return f"token={quote(token, safe='')}"
    if session:
        return f"session={quote(session, safe='')}"
    return None


def append_credential_to_url(url: str, credential: str) -> str:
    """Tempel `credential` (bentuk "token=...") ke satu URL relatif.

    URL absolut (http/https) dan URL yang sudah membawa query tidak
    diubah polanya secara merusak: kredensial ditambah dengan & bila
    query sudah ada, ? bila belum. Dipakai penulisan ulang playlist.
    """
    parts = urlsplit(url)
    query = f"{parts.query}&{credential}" if parts.query else credential
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


_URI_ATTR_RE = re.compile(r"(URI=\")([^\"]+)(\")")


def rewrite_playlist(text: str, credential: str) -> str:
    """Tempel kredensial ke tiap URI relatif di playlist HLS (.m3u8).

    - Baris biasa yang bukan komentar (#...) adalah URI segmen/playlist.
    - Atribut URI="..." di baris #EXT-X-MAP / #EXT-X-KEY ikut ditulis
      ulang (init segment fmp4 MediaMTX ada di sini; tanpa token,
      hls.js gagal memuat init segment dan playback mati).
    - URI absolut (http/https) dibiarkan apa adanya: itu bukan jalur
      MediaMTX lokal.
    """
    out: list[str] = []
    for line in text.splitlines():
        if not line:
            out.append(line)
            continue
        if line.startswith("#"):
            def _sub(m: "re.Match[str]") -> str:
                uri = m.group(2)
                if urlsplit(uri).scheme in ("http", "https"):
                    return m.group(0)
                return f"{m.group(1)}{append_credential_to_url(uri, credential)}{m.group(3)}"

            out.append(_URI_ATTR_RE.sub(_sub, line))
            continue
        if urlsplit(line).scheme in ("http", "https"):
            out.append(line)
            continue
        out.append(append_credential_to_url(line, credential))
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")
