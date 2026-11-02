"""Fixture bersama test Fase 1: DB sqlite file + override dependency."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 (registrasi metadata Alembic)
from app.core.rbac import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.users import User
from app.services.mediamtx import get_mediamtx


class FakeMediaMTX:
    """Pengganti MediaMTXClient: catat pemanggilan, tanpa jaringan."""

    def __init__(self):
        self.paths: dict[str, str] = {}
        self.deleted: list[str] = []

    async def create_path(self, name: str, source: str) -> None:
        self.paths[name] = source

    async def delete_path(self, name: str) -> None:
        self.deleted.append(name)
        self.paths.pop(name, None)

    async def get_path(self, name: str):
        return {"name": name, "ready": True} if name in self.paths else None

    async def aclose(self) -> None:
        pass


def make_user(**kw) -> User:
    base = dict(
        id=1,
        username="admin",
        password_hash="x",
        role="admin",
        is_active=True,
        refresh_token_hash=None,
    )
    base.update(kw)
    return User(**base)


@pytest_asyncio.fixture
async def db_session(tmp_path):
    """DB sqlite per-test (file, bukan :memory:) agar bisa dipakai lintas loop."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/test.db", poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def app_client(db_session):
    """(app, fake_mediamtx, db_session). Auth di-override per test."""
    app = create_app()
    fake_mtmx = FakeMediaMTX()

    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_mediamtx] = lambda: fake_mtmx
    return app, fake_mtmx, db_session


def auth_as(app, user: User):
    app.dependency_overrides[get_current_user] = lambda: user
