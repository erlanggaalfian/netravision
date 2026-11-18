"""Pengaturan sistem di database (kredensial internal).

MEDIAMTX_API_PASSWORD dibuat sekali saat deploy / install pertama
dan disimpan di tabel system_settings (bukan .env). Backend membaca
password ini saat startup (lifespan) dan memakainya untuk auth ke
control API MediaMTX. Deploy (service migrate, lewat
app/db/setup_mediamtx.py) memakai fungsi yang sama untuk
menghasilkan deploy/mediamtx.yml dari template.

ENKRIPSI (0030): nilai di kolom system_settings.value disimpan
TERENKRIPSI dengan Fernet memakai kunci DRIVE_TOKEN_KEY yang sama
dengan token OAuth Drive (app/core/drive_tokens.py), bukan
plaintext seperti sebelum migrasi 0030. Siapa pun yang membaca DB
(backup, dump, akses baca) tidak lagi langsung mendapat password
control-API MediaMTX. Migrasi 0030 mengenkripsi nilai lama;
ensure_mediamtx_password() di bawah tetap membaca nilai lama
(plaintext) dan meningkatkannya ke terenkripsi di tempat, supaya
deploy yang sudah berjalan tidak rusak saat upgrade.
"""

import base64
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.drive_tokens import _get_fernet
from app.models.misc import SystemSetting

log = logging.getLogger("netravision")

MEDIAMTX_PASSWORD_KEY = "mediamtx_api_password"
MEDIAMTX_YML_PLACEHOLDER = "__MEDIAMTX_API_PASSWORD__"

# Cache in-memory, diisi saat startup (lifespan) supaya get_mediamtx()
# yang sinkron bisa memakai password DB tanpa session.
_cached_mediamtx_password: str | None = None


def get_mediamtx_password() -> str | None:
    """Password MediaMTX yang sudah di-cache saat startup (atau None)."""
    return _cached_mediamtx_password


def set_mediamtx_password_cache(value: str | None) -> None:
    """Isi/bersihkan cache (dipakai lifespan dan tes)."""
    global _cached_mediamtx_password
    _cached_mediamtx_password = value


def generate_mediamtx_password() -> str:
    """Password acak 48 karakter hex (aman untuk mediamtx.yml dan .env)."""
    return secrets.token_hex(24)


def _looks_like_fernet_token(stored: str) -> bool:
    """Apakah `stored` berbentuk token Fernet (bukan plaintext lama)?

    Token Fernet selalu diawali byte versi 0x80 dan panjang total
    >= 57 byte (versi + timestamp + IV + ciphertext + HMAC). Nilai
    lama (mis. 48 hex) terlalu pendek / tidak berawalan 0x80 sehingga
    tidak pernah lolos heuristik ini. Heuristik ini hanya dipakai
    untuk membedakan "sudah terenkripsi" dari "plaintext lama" -
    dekripsi yang sesungguhnya tetap memverifikasi HMAC Fernet.
    """
    if not stored or len(stored) < 76:  # token Fernet terpendek ~100 char base64
        return False
    try:
        raw = base64.urlsafe_b64decode(stored.encode() + b"=" * (-len(stored) % 4))
    except Exception:
        return False
    return len(raw) >= 57 and raw[0] == 0x80


def encrypt_system_setting_value(plaintext: str) -> str:
    """Enkripsi nilai system_settings -> str untuk kolom value.

    Gagal keras (RuntimeError dari _get_fernet) bila DRIVE_TOKEN_KEY
    belum diset / tidak valid, jangan pernah menyimpan rahasia
    sebagai plaintext karena kunci belum ada.
    """
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_system_setting_value(stored: str) -> str:
    """Dekripsi nilai system_settings -> plaintext.

    Nilai lama (plaintext, ditulis sebelum migrasi 0030) dikembalikan
    apa adanya supaya pembaca lama / upgrade bertahap tidak rusak;
    pemanggil (ensure_mediamtx_password) yang meningkatkannya ke
    terenkripsi. Nilai yang berbentuk token Fernet tapi gagal
    didekripsi (kunci salah / rusak) TIDAK diperlakukan sebagai
    plaintext, gagal keras, karena mengembalikannya berarti
    membocorkan ciphertext sebagai password.
    """
    if not _looks_like_fernet_token(stored):
        return stored
    try:
        return _get_fernet().decrypt(stored.encode()).decode()
    except Exception as e:
        raise RuntimeError(
            "gagal mendekripsi system_settings, DRIVE_TOKEN_KEY mungkin "
            "berbeda dari saat enkripsi (lihat rotasi key di docs)"
        ) from e


async def ensure_mediamtx_password(db: AsyncSession) -> str:
    """Baca password MediaMTX dari DB; bila belum ada, buat dan simpan.

    Idempotent dan aman dari race: INSERT ... ON CONFLICT DO NOTHING
    lalu SELECT. Mengisi cache in-memory. Nilai disimpan TERENKRIPSI
    (0030); baris lama yang masih plaintext dibaca, lalu
    ditingkatkan ke terenkripsi di tempat (UPDATE) sebelum
    dikembalikan.
    """
    res = await db.execute(
        select(SystemSetting.value).where(
            SystemSetting.key == MEDIAMTX_PASSWORD_KEY
        )
    )
    row = res.first()
    if row is not None:
        stored = row[0]
        password = decrypt_system_setting_value(stored)
        if not _looks_like_fernet_token(stored):
            # Baris warisan plaintext: tingkatkan ke terenkripsi.
            from sqlalchemy import update as _update  # noqa: PLC0415

            await db.execute(
                _update(SystemSetting)
                .where(SystemSetting.key == MEDIAMTX_PASSWORD_KEY)
                .values(value=encrypt_system_setting_value(password))
            )
            await db.commit()
            log.info("mediamtx_api_password lama (plaintext) dienkripsi ulang")
        set_mediamtx_password_cache(password)
        return password
    # Belum ada: buat dan simpan (terenkripsi). Konstruktor insert
    # dipilih dari dialek engine (postgresql di produksi, sqlite di
    # tes), pola yang sama seperti _mark_uploaded di drive_uploader.py.
    from sqlalchemy.dialects import postgresql as _pg  # noqa: PLC0415
    from sqlalchemy.dialects import sqlite as _lite  # noqa: PLC0415

    dialect = db.bind.dialect.name if db.bind is not None else "postgresql"
    _insert = _pg.insert if dialect == "postgresql" else _lite.insert
    password = generate_mediamtx_password()
    await db.execute(
        _insert(SystemSetting)
        .values(key=MEDIAMTX_PASSWORD_KEY, value=encrypt_system_setting_value(password))
        .on_conflict_do_nothing(index_elements=["key"])
    )
    await db.commit()
    res = await db.execute(
        select(SystemSetting.value).where(
            SystemSetting.key == MEDIAMTX_PASSWORD_KEY
        )
    )
    row = res.first()
    if row is None:  # pragma: no cover - tidak mungkin setelah insert
        raise RuntimeError("gagal menyimpan mediamtx_api_password")
    # Baris bisa berasal dari race (insert pihak lain menang):
    # dekripsi apa pun yang tersimpan, jangan asumsi itu password baru.
    password = decrypt_system_setting_value(row[0])
    set_mediamtx_password_cache(password)
    log.info("mediamtx_api_password dibuat dan disimpan di database")
    return password


def render_mediamtx_yml(template_text: str, password: str) -> str:
    """Substitusi placeholder password di template mediamtx.yml."""
    if MEDIAMTX_YML_PLACEHOLDER not in template_text:
        raise ValueError(
            "template mediamtx.yml tidak mengandung placeholder "
            f"{MEDIAMTX_YML_PLACEHOLDER}"
        )
    return template_text.replace(MEDIAMTX_YML_PLACEHOLDER, password)
