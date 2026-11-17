"""Test T-2: token JWT sebagai cookie HttpOnly, bukan localStorage.

Membuktikan: login/guest mengatur cookie HttpOnly, request berikutnya
terautentikasi lewat cookie saja, refresh lewat cookie merotasi token,
logout menghapus cookie, dan request tanpa cookie dan tanpa header
tetap 401. Header Authorization tetap diterima sebagai fallback
(klien API dan tes lama).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.rbac import get_current_user
from app.core.security import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    create_refresh_token,
    hash_password,
    hash_token,
)
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


def _set_cookies(response):
    """Kembalikan dict nama -> nilai dari semua header Set-Cookie."""
    out = {}
    for raw in response.headers.get_list("set-cookie"):
        pair = raw.split(";", 1)[0].strip()
        if "=" in pair:
            name, value = pair.split("=", 1)
            out[name.strip()] = value.strip().strip('"')
    return out


def _cookie_attrs(response, name):
    """Kembalikan string atribut header Set-Cookie untuk satu nama cookie."""
    for raw in response.headers.get_list("set-cookie"):
        if raw.strip().startswith(name + "="):
            return raw
    return ""


async def _login(c):
    r = await c.post(
        "/api/auth/login",
        json={"username": "admin", "password": "rahasia123"},
    )
    assert r.status_code == 200, r.text
    return r


async def test_login_sets_http_only_cookies(app):
    c, _ = _client(app, _make_user())
    async with c:
        r = await _login(c)
    cookies = _set_cookies(r)
    assert cookies.get(ACCESS_COOKIE), "login harus mengatur cookie nv_access"
    assert cookies.get(REFRESH_COOKIE), "login harus mengatur cookie nv_refresh"
    access_attrs = _cookie_attrs(r, ACCESS_COOKIE).lower()
    assert "httponly" in access_attrs
    assert "samesite=lax" in access_attrs
    assert "path=/" in access_attrs
    assert "max-age=900" in access_attrs  # 15 menit access token
    refresh_attrs = _cookie_attrs(r, REFRESH_COOKIE).lower()
    assert "httponly" in refresh_attrs
    assert "samesite=lax" in refresh_attrs
    assert "path=/api/auth" in refresh_attrs
    assert "max-age=604800" in refresh_attrs  # 7 hari refresh token
    # HTTP (bukan HTTPS) di test: Secure tidak diset supaya cookie
    # tetap terkirim di dev/demo lokal.
    assert "secure" not in access_attrs


async def test_me_authenticated_via_cookie_only(app):
    c, _ = _client(app, _make_user())
    async with c:
        login_r = await _login(c)
        access = _set_cookies(login_r)[ACCESS_COOKIE]
        r = await c.get("/api/auth/me", headers={"Cookie": f"{ACCESS_COOKIE}={access}"})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "admin"


async def test_me_without_cookie_or_header_is_401(app):
    c, _ = _client(app, _make_user())
    async with c:
        r = await c.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_via_authorization_header_fallback(app):
    """Fallback header Authorization tetap berfungsi (klien API)."""
    c, _ = _client(app, _make_user())
    async with c:
        login_r = await _login(c)
        access = login_r.json()["access_token"]
        r = await c.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {access}"}
        )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "admin"


async def test_refresh_via_cookie_rotates(app):
    c, _ = _client(app, _make_user())
    async with c:
        login_r = await _login(c)
        cookies = _set_cookies(login_r)
        old_refresh = cookies[REFRESH_COOKIE]
        r = await c.post(
            "/api/auth/refresh",
            json={},
            headers={"Cookie": f"{REFRESH_COOKIE}={old_refresh}"},
        )
    assert r.status_code == 200, r.text
    new_cookies = _set_cookies(r)
    assert new_cookies.get(REFRESH_COOKIE), "refresh harus mengatur cookie baru"
    assert new_cookies[REFRESH_COOKIE] != old_refresh
    assert new_cookies.get(ACCESS_COOKIE)
    assert "httponly" in _cookie_attrs(r, REFRESH_COOKIE).lower()


async def test_refresh_via_body_still_works(app):
    """Klien API lama yang mengirim refresh_token di body tetap bisa."""
    c, _ = _client(app, _make_user())
    async with c:
        login_r = await _login(c)
        refresh = login_r.json()["refresh_token"]
        r = await c.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200, r.text
    assert r.json()["refresh_token"] != refresh


async def test_refresh_without_cookie_or_body_is_401(app):
    c, _ = _client(app, _make_user())
    async with c:
        r = await c.post("/api/auth/refresh", json={})
    assert r.status_code == 401


async def test_refresh_with_wrong_cookie_is_401(app):
    c, _ = _client(app, _make_user())
    async with c:
        r = await c.post(
            "/api/auth/refresh",
            json={},
            headers={"Cookie": f"{REFRESH_COOKIE}=bukan-token"},
        )
    assert r.status_code == 401


async def test_logout_clears_cookies_and_revokes_refresh(app):
    user = _make_user(refresh_token_hash="abc123")
    c, fake = _client(app, user)
    async with c:
        login_r = await _login(c)
        access = _set_cookies(login_r)[ACCESS_COOKIE]
        r = await c.post(
            "/api/auth/logout", headers={"Cookie": f"{ACCESS_COOKIE}={access}"}
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert user.refresh_token_hash is None
    assert fake.committed
    access_attrs = _cookie_attrs(r, ACCESS_COOKIE).lower()
    refresh_attrs = _cookie_attrs(r, REFRESH_COOKIE).lower()
    assert "max-age=0" in access_attrs
    assert "max-age=0" in refresh_attrs


async def test_guest_login_sets_access_cookie_only(app, monkeypatch):
    """Guest: cookie access 60 menit, tanpa cookie refresh."""
    settings = get_settings()
    monkeypatch.setattr(settings, "guest_enabled", True)
    guest = _make_user(id=9, username="guest", role="guest", is_active=True)
    c, _ = _client(app, guest)
    async with c:
        r = await c.post("/api/auth/guest", json={})
    assert r.status_code == 200, r.text
    cookies = _set_cookies(r)
    assert cookies.get(ACCESS_COOKIE)
    assert "httponly" in _cookie_attrs(r, ACCESS_COOKIE).lower()
    assert "max-age=3600" in _cookie_attrs(r, ACCESS_COOKIE).lower()
    # Guest tidak punya refresh: cookie refresh harus dihapus, bukan diset.
    assert REFRESH_COOKIE not in cookies or cookies[REFRESH_COOKIE] == ""


async def test_guest_me_via_cookie(app, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "guest_enabled", True)
    guest = _make_user(id=9, username="guest", role="guest", is_active=True)
    c, _ = _client(app, guest)
    async with c:
        login_r = await c.post("/api/auth/guest", json={})
        assert login_r.status_code == 200, login_r.text
        access = _set_cookies(login_r)[ACCESS_COOKIE]
        r = await c.get("/api/auth/me", headers={"Cookie": f"{ACCESS_COOKIE}={access}"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "guest"


async def test_login_wrong_password_sets_no_cookie(app):
    c, _ = _client(app, _make_user())
    async with c:
        r = await c.post(
            "/api/auth/login", json={"username": "admin", "password": "salah"}
        )
    assert r.status_code == 401
    assert ACCESS_COOKIE not in _set_cookies(r)
