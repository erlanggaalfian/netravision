"""Fixture bersama test Fase 1: DB sqlite file + override dependency."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 (registrasi metadata Alembic)
from app.core.rbac import get_current_user, get_current_user_flexible
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.users import User
from app.services.mediamtx import get_mediamtx_dep


class FakeMediaMTX:
    """Pengganti MediaMTXClient: catat pemanggilan, tanpa jaringan."""

    def __init__(self):
        self.paths: dict[str, str] = {}
        self.records: dict[str, bool] = {}
        self.patches: dict[str, dict] = {}
        self.deleted: list[str] = []

    async def create_path(self, name: str, source: str, record: bool = False) -> None:
        self.paths[name] = source
        self.records[name] = record

    async def patch_path(self, name: str, patch: dict) -> None:
        self.patches.setdefault(name, {}).update(patch)

    async def delete_path(self, name: str) -> None:
        self.deleted.append(name)
        self.paths.pop(name, None)
        if hasattr(self, "confs"):
            self.confs.pop(name, None)

    async def ensure_path(self, name: str, conf: dict) -> None:
        self.paths[name] = conf.get("source", "")
        self.records[name] = bool(conf.get("record"))
        self.confs = getattr(self, "confs", {})
        self.confs[name] = conf

    async def path_ready(self, name: str) -> bool:
        return name in self.paths

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
    # Router memakai get_mediamtx_dep (dependency yield, temuan 3.8);
    # override di sini supaya tes tetap memakai FakeMediaMTX.
    app.dependency_overrides[get_mediamtx_dep] = lambda: fake_mtmx
    return app, fake_mtmx, db_session


def auth_as(app, user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_flexible] = lambda: user


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Rate limiter in-memory harus bersih antar-test."""
    from app.core.rate_limit import reset_rate_limits

    reset_rate_limits()
    # Kunci brute-force password API key (external._KEY_FAILURES)
    # juga harus bersih antar-test, seperti rate limiter.
    from app.routers import external as _external

    _external._KEY_FAILURES.clear()
    # Cache in-process (A-1.5 health, A-1.10 disk-summary) juga
    # harus bersih antar-test supaya hasil satu test tidak bocor
    # ke test berikutnya.
    from app.routers import admin_streams as _admin_streams
    from app.routers import system as _system

    _system.reset_health_cache()
    _admin_streams.reset_disk_cache()
    # Cache in-process Area 6 (config iklan TTL 60 dtk, daftar folder
    # Drive TTL 60 dtk, geocoding 24 jam) juga harus bersih antar-test,
    # supaya baris DB yang ditulis langsung oleh satu test tidak
    # terbaca basi oleh test berikutnya.
    from app.routers import recordings as _recordings
    from app.services import location as _location

    _external.invalidate_ad_config_cache()
    _recordings.invalidate_drive_folders_cache()
    _location.clear_geocode_cache()
    # State in-process Area 4 (kunci login, grace + jejak rotasi
    # refresh, brankas URL scan) juga harus bersih antar-test.
    from app.routers import auth as _auth
    from app.services import scan_vault as _scan_vault

    _auth.reset_login_attempts()
    _auth.reset_refresh_state()
    _scan_vault.reset()
    yield
    reset_rate_limits()
    _external._KEY_FAILURES.clear()
    _system.reset_health_cache()
    _admin_streams.reset_disk_cache()
    _external.invalidate_ad_config_cache()
    _recordings.invalidate_drive_folders_cache()
    _location.clear_geocode_cache()
    _auth.reset_login_attempts()
    _auth.reset_refresh_state()
    _scan_vault.reset()


@pytest.fixture(autouse=True)
def _stub_rtsp_network(monkeypatch):
    """Tanpa jaringan: semua URL RTSP dianggap mengirim video.

    Skenario lain (auth gagal, no_video, host mati) override fixture ini
    per test dengan monkeypatch.setattr pada rtsp_discovery.
    """
    from app.services import rtsp_discovery

    async def fake_probe(url, timeout=3.0):
        return "open"

    async def fake_ffprobe(url, timeout=10.0):
        return rtsp_discovery.VideoProbe(
            status="video", codec="h264", width=640, height=480,
            fps=25.0, gop_seconds=2.0,
        )

    async def fake_alive(host, port):
        return True

    monkeypatch.setattr(rtsp_discovery, "probe_path", fake_probe)
    monkeypatch.setattr(rtsp_discovery, "_run_ffprobe", fake_ffprobe)
    monkeypatch.setattr(rtsp_discovery, "_tcp_alive", fake_alive)
