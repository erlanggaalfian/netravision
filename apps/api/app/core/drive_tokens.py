"""Enkripsi Fernet untuk token OAuth Google Drive di DB.

Token akun Drive disimpan di kolom drive_accounts.token_encrypted dalam
bentuk terenkripsi — tidak pernah plaintext. Kunci diambil dari
DRIVE_TOKEN_KEY (lihat docs/GOOGLE-DRIVE.md §5 cara generate & rotasi).
"""

import json
import logging

log = logging.getLogger("netravision.drive_tokens")


def _get_fernet():
    """Bangun Fernet dari DRIVE_TOKEN_KEY. Error jelas bila belum diset."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError(
            "paket 'cryptography' belum terinstal "
            "(pip install netravision-api — dependensi inti)"
        ) from e
    from app.core.config import get_settings

    key = (get_settings().drive_token_key or "").strip()
    if not key:
        raise RuntimeError(
            "DRIVE_TOKEN_KEY belum diset — generate dengan:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            "lalu isi di .env (lihat deploy/.env.example)"
        )
    try:
        return Fernet(key.encode())
    except Exception as e:
        raise RuntimeError(
            "DRIVE_TOKEN_KEY tidak valid (harus base64 32-byte dari "
            "Fernet.generate_key())"
        ) from e


def encrypt_token(token: dict) -> str:
    """Enkripsi dict token OAuth -> str untuk kolom token_encrypted."""
    return _get_fernet().encrypt(
        json.dumps(token, separators=(",", ":")).encode()
    ).decode()


def decrypt_token(blob: str) -> dict:
    """Dekripsi str token_encrypted -> dict token OAuth."""
    try:
        data = json.loads(_get_fernet().decrypt(blob.encode()).decode())
    except Exception as e:
        raise RuntimeError(
            "gagal mendekripsi token Drive — DRIVE_TOKEN_KEY mungkin "
            "berbeda dari saat enkripsi (lihat rotasi key di docs)"
        ) from e
    if not isinstance(data, dict):
        raise RuntimeError("token Drive terdekripsi bukan JSON object")
    return data
