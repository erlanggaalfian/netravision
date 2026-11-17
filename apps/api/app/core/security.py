"""Keamanan: hash password (bcrypt via pwdlib) dan JWT.

- Access token: umur pendek (default 15 menit), dipakai di header Authorization.
- Refresh token: umur panjang (default 7 hari), hash-nya disimpan di DB dan
  dirotasi setiap dipakai (refresh rotation).
- decode_token menolak token tanpa exp/iat/sub (token abadi atau tanpa
  pemilik tidak pernah sah) dan hanya menerima algoritma yang dikonfigurasi.
- redact_url_credentials: satu-satunya tempat menyembunyikan kredensial
  dari URL RTSP sebelum URL itu masuk log, pesan error, atau respons API.
  Semua tempat lain WAJIB memakai helper ini, bukan masking ad hoc.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import Settings

# Eksplisit bcrypt (kompatibel dengan hash v2.0); bukan recommended() karena
# itu butuh argon2 bila terinstal dan perilakunya bisa berubah antar env.
_hasher = PasswordHash((BcryptHasher(),))

# Batas umur access token yang boleh diminta pemanggil (menit). Guest memakai
# 60 menit; tidak ada pemanggil sah yang butuh lebih dari sehari.
_MAX_ACCESS_MINUTES = 1440


def hash_password(password: str) -> str:
    # A-1.6: bcrypt menolak password > 72 byte (melempar ValueError dari
    # passlib). Tolak eksplisit di sini sebagai pertahanan lapis kedua;
    # skema API sudah membatasi max_length=72.
    if len(password.encode()) > 72:
        raise ValueError("password maksimal 72 byte (batas bcrypt)")
    return _hasher.hash(password)


# 4.12: kebijakan password minimal. Panjang minimum 12 untuk
# admin/super_admin, 8 untuk user/guest; password dari daftar umum
# yang paling sering dipakai ditolak. Daftar ini sengaja pendek
# (bukan kamus lengkap): tujuannya memblokir password trivial, bukan
# menjadi penilai kekuatan. Pemeriksaan hanya saat password BARU
# dibuat/diubah; password lama yang sudah tersimpan tidak dipaksa
# ganti (hash-nya tidak bisa dinilai tanpa plaintext).
_COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "password1234",
    "12345678", "123456789", "1234567890", "12345678910",
    "qwerty123", "qwertyuiop", "admin123", "admin1234",
    "administrator", "letmein", "welcome1", "welcome123",
    "iloveyou", "monkey123", "dragon123", "football1",
    "00000000", "11111111", "123123123", "abc123456",
    "admin", "administrator1", "netravision", "netravision123",
})


def validate_password(password: str, role: str) -> str | None:
    """Periksa password baru. Kembalikan pesan error, atau None bila sah.

    Aturan: panjang minimum menurut peran + tolak password umum.
    Dipakai create/update user; kunci API embed tidak memakai ini
    (password kunci boleh kosong dan bukan kredensial login akun).
    """
    min_len = 12 if role in ("admin", "super_admin") else 8
    if len(password) < min_len:
        return f"password minimal {min_len} karakter"
    if password.strip() != password:
        return "password tidak boleh diawali/diakhiri spasi"
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or lowered == role:
        return "password terlalu umum, pilih password lain"
    return None


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password, password_hash)
    except ValueError:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    user_id: int | str,
    username: str,
    role: str,
    settings: Settings,
    expires_minutes: int | None = None,
) -> str:
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_access_minutes
    # Jangan pernah menerbitkan token abadi atau berumur sangat panjang
    # karena satu pemanggil lupa membatasi expires_minutes.
    minutes = max(1, min(int(minutes), _MAX_ACCESS_MINUTES))
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int, settings: Settings) -> tuple[str, str]:
    """Return (token, jti). Simpan hash(token) di DB, bukan token aslinya."""
    jti = secrets.token_hex(16)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": jti,
        "iat": _now(),
        "exp": _now() + timedelta(days=settings.jwt_refresh_days),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


def decode_token(token: str, settings: Settings) -> dict:
    """Decode + verifikasi JWT. Raise ValueError bila tidak valid/kedaluwarsa.

    Menolak token tanpa exp/iat/sub: token yang tidak kedaluwarsa atau
    tidak punya pemilik tidak pernah diterbitkan pemanggil sah, jadi
    menerimanya hanya membuka pintu bagi token hasil kerajinan tangan.
    """
    if not token or not isinstance(token, str):
        raise ValueError("token tidak valid")
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise ValueError("token kedaluwarsa") from e
    except jwt.InvalidTokenError as e:
        raise ValueError("token tidak valid") from e
    if not isinstance(payload, dict) or not payload.get("sub"):
        raise ValueError("token tidak valid")
    return payload


def hash_token(token: str) -> str:
    """Hash SHA-256 untuk menyimpan refresh token di DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def redact_url_credentials(url: str | None) -> str:
    """Sembunyikan password dari URL (mis. rtsp://user:pass@host/...).

    Dipakai SEBELUM url masuk log, pesan error, atau respons API di
    semua endpoint, bukan cuma di satu tempat. Username dipertahankan
    (berguna untuk diagnosis), password diganti ****. URL tanpa
    kredensial atau yang tidak bisa diparse dikembalikan apa adanya
    bila tidak mengandung password, dan di-mask sebagian bila parse gagal.
    """
    if not url:
        return ""
    try:
        parts = urlparse(url)
    except ValueError:
        return "****"
    if not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    userinfo = parts.username or ""
    netloc = f"{userinfo}:****@{host}" if userinfo else f"****@{host}"
    return urlunparse(parts._replace(netloc=netloc))


def strip_url_credentials(url: str | None) -> str:
    """Hapus userinfo dari URL sepenuhnya (untuk log yang sangat sensitif)."""
    if not url:
        return ""
    try:
        parts = urlparse(url)
    except ValueError:
        return ""
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunparse(parts._replace(netloc=host))
