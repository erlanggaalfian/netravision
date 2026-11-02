"""Keamanan: hash password (bcrypt via pwdlib) dan JWT.

- Access token: umur pendek (default 15 menit), dipakai di header Authorization.
- Refresh token: umur panjang (default 7 hari), hash-nya disimpan di DB dan
  dirotasi setiap dipakai (refresh rotation).
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import Settings

# Eksplisit bcrypt (kompatibel dengan hash v2.0); bukan recommended() karena
# itu butuh argon2 bila terinstal dan perilakunya bisa berubah antar env.
_hasher = PasswordHash((BcryptHasher(),))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


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
    """Decode + verifikasi JWT. Raise ValueError bila tidak valid/kedaluwarsa."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as e:
        raise ValueError("token kedaluwarsa") from e
    except jwt.InvalidTokenError as e:
        raise ValueError("token tidak valid") from e


def hash_token(token: str) -> str:
    """Hash SHA-256 untuk menyimpan refresh token di DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
