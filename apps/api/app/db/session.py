"""Async engine + session factory + dependency get_db."""

from collections.abc import AsyncIterator, Callable

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# 2.19: batas default statement_timeout (detik) untuk SEMUA query.
# Diterapkan sebagai server_settings saat koneksi asyncpg dibuka, dan
# dipakai sebagai nilai kembalian oleh get_db_with_timeout. Query
# normal (milis/detik) tidak terpengaruh; hanya query yang menggantung
# lebih dari 30 detik yang dibatalkan Postgres, bukan dibiarkan
# mengunci koneksi pool tanpa batas.
DEFAULT_STATEMENT_TIMEOUT_SECONDS = 30

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url
        connect_args: dict = {}
        # server_settings hanya dimengerti asyncpg; SQLite (tes) dan
        # driver lain tidak boleh menerima kwarg ini.
        if url.startswith("postgresql+asyncpg"):
            connect_args = {
                "server_settings": {
                    "statement_timeout": str(DEFAULT_STATEMENT_TIMEOUT_SECONDS * 1000),
                },
            }
        _engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            # 2.19: tanpa batas tunggu dan tanpa recycle, lonjakan
            # request bersamaan dengan loop background bisa mengantre
            # atau kehabisan koneksi tanpa batas waktu yang jelas, dan
            # koneksi basi tidak pernah diganti.
            pool_timeout=30,
            pool_recycle=1800,
            connect_args=connect_args,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


def get_db_with_timeout(timeout_seconds: int) -> Callable:
    """Dependency factory: sesi DB dengan statement_timeout per endpoint.

    2.19: dipakai endpoint baca berat (mis. daftar log/audit yang
    memindai banyak baris) supaya satu request lambat tidak menahan
    koneksi pool selamanya. Delegasi ke get_db, jadi override
    dependency di tes tetap berlaku. Di PostgreSQL, SET berlaku
    per sesi dan dikembalikan ke default saat request selesai (blok
    finally, dengan rollback dulu supaya SET tidak gagal bila
    transaksi endpoint sudah abort). Di dialek lain (SQLite tes)
    dependency ini no-op: SET statement_timeout tidak ada di sana.

    Contoh pakai di router:
        db: AsyncSession = Depends(get_db_with_timeout(60))
    """

    async def _get_with_timeout(
        db: AsyncSession = Depends(get_db),
    ) -> AsyncIterator[AsyncSession]:
        is_pg = _is_postgres_session(db)
        if is_pg:
            await db.execute(
                text(f"SET statement_timeout = '{int(timeout_seconds) * 1000}'")
            )
        try:
            yield db
        finally:
            if is_pg:
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001, reset best-effort
                    pass
                try:
                    await db.execute(
                        text(
                            "SET statement_timeout = "
                            f"'{DEFAULT_STATEMENT_TIMEOUT_SECONDS * 1000}'"
                        )
                    )
                except Exception:  # noqa: BLE001, reset best-effort
                    pass

    return _get_with_timeout


def _is_postgres_session(db: AsyncSession) -> bool:
    """True bila sesi memakai PostgreSQL (satu-satunya dialek yang
    mendukung SET statement_timeout)."""
    bind = getattr(db, "bind", None)
    if bind is None:
        return False
    engine = getattr(bind, "sync_engine", bind)
    dialect = getattr(engine, "dialect", None)
    return getattr(dialect, "name", None) == "postgresql"


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
