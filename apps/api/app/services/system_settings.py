"""Pengaturan sistem di database (kredensial internal).

MEDIAMTX_API_PASSWORD dibuat sekali saat deploy / install pertama
dan disimpan di tabel system_settings (bukan .env). Backend membaca
password ini saat startup (lifespan) dan memakainya untuk auth ke
control API MediaMTX. Deploy (service migrate, lewat
app/db/setup_mediamtx.py) memakai fungsi yang sama untuk
menghasilkan deploy/mediamtx.yml dari template.
"""

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def ensure_mediamtx_password(db: AsyncSession) -> str:
    """Baca password MediaMTX dari DB; bila belum ada, buat dan simpan.

    Idempotent dan aman dari race: INSERT ... ON CONFLICT DO NOTHING
    lalu SELECT. Mengisi cache in-memory.
    """
    res = await db.execute(
        select(SystemSetting.value).where(
            SystemSetting.key == MEDIAMTX_PASSWORD_KEY
        )
    )
    row = res.first()
    if row is not None:
        set_mediamtx_password_cache(row[0])
        return row[0]
    # Belum ada: buat dan simpan. Konstruktor insert dipilih dari
    # dialek engine (postgresql di produksi, sqlite di tes), pola yang
    # sama seperti _mark_uploaded di drive_uploader.py.
    from sqlalchemy.dialects import postgresql as _pg  # noqa: PLC0415
    from sqlalchemy.dialects import sqlite as _lite  # noqa: PLC0415

    dialect = db.bind.dialect.name if db.bind is not None else "postgresql"
    _insert = _pg.insert if dialect == "postgresql" else _lite.insert
    password = generate_mediamtx_password()
    await db.execute(
        _insert(SystemSetting)
        .values(key=MEDIAMTX_PASSWORD_KEY, value=password)
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
    set_mediamtx_password_cache(row[0])
    log.info("mediamtx_api_password dibuat dan disimpan di database")
    return row[0]


def render_mediamtx_yml(template_text: str, password: str) -> str:
    """Substitusi placeholder password di template mediamtx.yml."""
    if MEDIAMTX_YML_PLACEHOLDER not in template_text:
        raise ValueError(
            "template mediamtx.yml tidak mengandung placeholder "
            f"{MEDIAMTX_YML_PLACEHOLDER}"
        )
    return template_text.replace(MEDIAMTX_YML_PLACEHOLDER, password)
