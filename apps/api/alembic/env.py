"""Alembic env async. URL dari settings (DATABASE_URL).

DIALEK RESMI: PostgreSQL. SQLite hanya dipakai unit test lewat
Base.metadata.create_all (tests/conftest.py), BUKAN lewat migrasi.
Migrasi 0025+ mengandung DDL khusus PostgreSQL (CREATE INDEX
CONCURRENTLY, postgresql_where, NOT VALID / VALIDATE CONSTRAINT,
NULLS NOT DISTINCT, now()) tanpa padanan SQLite; menjalankannya di
SQLite gagal atau, lebih buruk, menghasilkan skema yang berbeda
(mis. 0025 menjadi unique-index biasa pada boolean is_default).
Migrasi 0030 menolak dialek non-PostgreSQL dengan pesan jelas
(fail-hard, pola 0029). Peringatan di bawah ini ditampilkan bila
env ini dijalankan terhadap SQLite, supaya operator tidak mengira
migrasi SQLite adalah jalur yang didukung.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import create_async_engine

# Registrasi semua model agar metadata lengkap.
import app.models  # noqa: F401
from alembic import context
from app.core.config import get_settings
from app.db.base import Base

log = logging.getLogger("alembic.env")

config = context.config
target_metadata = Base.metadata


def do_run_migrations(connection):
    if connection.dialect.name == "sqlite":
        log.warning(
            "Dialek resmi NetraVision adalah PostgreSQL; migrasi "
            "0025+ hanya PostgreSQL dan akan gagal keras di SQLite. "
            "Database SQLite untuk test dibuat via Base.metadata."
            "create_all, bukan via migrasi."
        )
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
