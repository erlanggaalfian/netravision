"""Test auth: login, refresh rotation, logout, guest (DB di-fake)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.rbac import get_current_user
from app.core.security import create_refresh_token, hash_password, hash_token
from app.db.session import get_db
from app.main import create_app
from app.models.users import User


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def first(self):
        return self._items[0] if self._items else None


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalars(self._items)


class FakeSession:
    """Pengganti AsyncSession: kembalikan user yang disuntik test."""

    def __init__(self, user=None):
        self._user = user
        self.committed = False

    async def execute(self, stmt):
        return _FakeResult([self._user] if self._user is not None else [])

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass

    def add(self, obj):
        pass


def _make_user(**kw):
    base = dict(
        id=1,
        username="admin",
        password_hash=hash_password("rahasia123"),
        role="admin",
        is_active=True,
        refresh_token_hash=None,
    )
    base.update(kw)
    return User(**base)


@pytest.fixture
def app():
    return create_app()


def _client(app, user=None, current_user=None):
    fake = FakeSession(user)

    async def _get_db():
        yield fake

    app.dependency_overrides[get_db] = _get_db
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), fake


async def test_login_ok(app):
    c, fake = _client(app, _make_user())
    async with c:
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "rahasia123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert fake.committed  # hash refresh tersimpan (rotation)


async def test_login_wrong_password(app):
    c, _ = _client(app, _make_user())
    async with c:
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "salah"})
    assert r.status_code == 401


async def test_login_unknown_user(app):
    c, _ = _client(app, None)
    async with c:
        r = await c.post("/api/auth/login", json={"username": "hantu", "password": "x"})
    assert r.status_code == 401


async def test_refresh_rotation(app):
    settings = get_settings()
    user = _make_user()
    refresh, _jti = create_refresh_token(user.id, settings)
    user.refresh_token_hash = hash_token(refresh)
    c, fake = _client(app, user)
    async with c:
        r = await c.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"] != refresh  # terrotasi
    assert user.refresh_token_hash == hash_token(body["refresh_token"])
    assert fake.committed


async def test_refresh_reused_token_rejected(app):
    """Token lama yang sudah dirotasi harus ditolak (hash tidak cocok)."""
    settings = get_settings()
    user = _make_user()
    old_refresh, _ = create_refresh_token(user.id, settings)
    user.refresh_token_hash = hash_token("token-lain-yang-sudah-rotate")
    c, _ = _client(app, user)
    async with c:
        r = await c.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 401


async def test_logout_clears_refresh(app):
    user = _make_user(refresh_token_hash="abc123")
    c, fake = _client(app, user, current_user=user)
    async with c:
        r = await c.post("/api/auth/logout", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert user.refresh_token_hash is None
    assert fake.committed


async def test_guest_disabled_by_default(app):
    c, _ = _client(app)
    async with c:
        r = await c.post("/api/auth/guest", json={})
    assert r.status_code == 403


async def test_guest_enabled_no_password(app, monkeypatch):
    """Guest login tanpa password/autentikasi apapun (2026-11-06)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "guest_enabled", True)
    c, _ = _client(app)
    async with c:
        r = await c.post("/api/auth/guest", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"] is None  # tamu tanpa refresh
