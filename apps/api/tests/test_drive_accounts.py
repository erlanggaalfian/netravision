"""Test Google Drive multi-akun: enkripsi, CRUD, OAuth callback, resolusi."""

import json
import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.drive_tokens import decrypt_token, encrypt_token
from app.models.drive import DriveAccount
from app.models.streams import Stream
from app.routers import admin_drive
from app.services import drive_accounts as da
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def drive_env(monkeypatch, tmp_path):
    """DRIVE_TOKEN_KEY + credentials.json + public_base untuk test."""
    monkeypatch.setenv("DRIVE_TOKEN_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    cred = tmp_path / "credentials.json"
    cred.write_text(json.dumps(
        {"installed": {"client_id": "cid-test", "client_secret": "csec-test"}}
    ))
    s = get_settings()
    monkeypatch.setattr(s, "drive_credentials_file", str(cred))
    monkeypatch.setattr(s, "public_base_url", "https://netra.example.id")
    yield s
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clean_clients():
    da._clients.clear()
    yield
    da._clients.clear()


def _audit_factory_for(db_session):
    engine = db_session.bind
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _mk_account(db_session, name, **kw):
    acc = DriveAccount(name=name, **kw)
    db_session.add(acc)
    await db_session.commit()
    await db_session.refresh(acc)
    return acc


async def _mk_stream(db_session, name="cam1", **kw):
    s = Stream(name=name, rtsp_url="rtsp://x/1", **kw)
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


# ---------- enkripsi ----------

async def test_fernet_roundtrip(drive_env):
    token = {"access_token": "a", "refresh_token": "r", "token_type": "Bearer"}
    blob = encrypt_token(token)
    assert blob != json.dumps(token)
    assert decrypt_token(blob) == token


async def test_fernet_wrong_key(drive_env, monkeypatch):
    blob = encrypt_token({"a": 1})
    monkeypatch.setenv("DRIVE_TOKEN_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            decrypt_token(blob)
    finally:
        get_settings.cache_clear()


async def test_fernet_no_key(monkeypatch):
    monkeypatch.delenv("DRIVE_TOKEN_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DRIVE_TOKEN_KEY"):
            encrypt_token({"a": 1})
    finally:
        get_settings.cache_clear()


# ---------- CRUD ----------

async def test_create_account_returns_oauth_url(app_client, drive_env):
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.post("/api/admin/drive-accounts", json={"name": "Akun A"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Akun A"
    assert "accounts.google.com" in body["oauth_url"]
    assert "state=" in body["oauth_url"]


async def test_create_duplicate_name_409(app_client, drive_env, db_session):
    await _mk_account(db_session, "Akun A")
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    auth_as(app, make_user())
    async with _client(app) as c:
        r = await c.post("/api/admin/drive-accounts", json={"name": "Akun A"})
    assert r.status_code == 409


async def test_list_includes_camera_count(app_client, db_session):
    acc = await _mk_account(db_session, "Akun A")
    await _mk_stream(db_session, "cam1", drive_account_id=acc.id)
    await _mk_stream(db_session, "cam2", drive_account_id=acc.id)
    app, _, _ = app_client
    auth_as(app, make_user())
    async with _client(app) as c:
        r = await c.get("/api/admin/drive-accounts")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["camera_count"] == 2
    assert body[0]["connected"] is False


async def test_set_default_revokes_old(app_client, db_session):
    a = await _mk_account(db_session, "A", is_default=True)
    b = await _mk_account(db_session, "B")
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    auth_as(app, make_user())
    async with _client(app) as c:
        r = await c.put(f"/api/admin/drive-accounts/{b.id}", json={"is_default": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_default"] is True
    ra = (await db.execute(select(DriveAccount).where(DriveAccount.id == a.id))).scalar_one()
    assert ra.is_default is False


async def test_delete_409_when_used(app_client, db_session):
    acc = await _mk_account(db_session, "Akun A")
    await _mk_stream(db_session, "cam1", drive_account_id=acc.id)
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    auth_as(app, make_user())
    async with _client(app) as c:
        r = await c.delete(f"/api/admin/drive-accounts/{acc.id}")
    assert r.status_code == 409
    assert r.json()["detail"]["camera_count"] == 1


async def test_delete_ok_when_unused(app_client, db_session):
    acc = await _mk_account(db_session, "Akun A")
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    auth_as(app, make_user())
    async with _client(app) as c:
        r = await c.delete(f"/api/admin/drive-accounts/{acc.id}")
    assert r.status_code == 200, r.text
    assert await db.get(DriveAccount, acc.id) is None


async def test_non_admin_forbidden(app_client):
    app, _, _ = app_client
    auth_as(app, make_user(role="user"))
    async with _client(app) as c:
        r = await c.get("/api/admin/drive-accounts")
    assert r.status_code == 403


# ---------- OAuth callback ----------

async def test_callback_rejects_fake_state(app_client):
    app, _, _ = app_client
    # TANPA auth — Google yang memanggil.
    async with _client(app) as c:
        r = await c.get(
            "/api/admin/drive-accounts/oauth/callback",
            params={"code": "x", "state": "palsu"},
            follow_redirects=False,
        )
    assert r.status_code == 400


async def test_callback_success(app_client, db_session, drive_env, monkeypatch):
    acc = await _mk_account(db_session, "Akun A")

    async def _fake_exchange(code, settings):
        assert code == "kode-valid"
        return {"access_token": "at", "refresh_token": "rt", "token_type": "Bearer"}

    monkeypatch.setattr(admin_drive, "_exchange_code", _fake_exchange)
    app, _, db = app_client
    state = admin_drive._sign_state(str(acc.id))
    async with _client(app) as c:
        r = await c.get(
            "/api/admin/drive-accounts/oauth/callback",
            params={"code": "kode-valid", "state": state},
            follow_redirects=False,
        )
    assert r.status_code == 302, r.text
    assert r.headers["location"].startswith("https://netra.example.id/admin/drive/")
    assert "connected=1" in r.headers["location"]
    await db.refresh(acc)
    assert acc.status == "connected"
    assert decrypt_token(acc.token_encrypted)["refresh_token"] == "rt"


async def test_reauth_returns_oauth_url(app_client, db_session, drive_env):
    acc = await _mk_account(db_session, "Akun A")
    app, _, _ = app_client
    auth_as(app, make_user())
    async with _client(app) as c:
        r = await c.post(f"/api/admin/drive-accounts/{acc.id}/reauth")
    assert r.status_code == 200
    assert "accounts.google.com" in r.json()["oauth_url"]


# ---------- resolusi akun ----------

async def _connected(db_session, name, **kw):
    kw.setdefault("status", "connected")
    kw.setdefault("token_encrypted", "blob")
    return await _mk_account(db_session, name, **kw)


async def test_resolve_assigned(db_session):
    a = await _connected(db_session, "A")
    await _connected(db_session, "B", is_default=True)
    s = await _mk_stream(db_session, drive_account_id=a.id)
    assert (await da.resolve_drive_account(db_session, s)).id == a.id


async def test_resolve_default(db_session):
    b = await _connected(db_session, "B", is_default=True)
    s = await _mk_stream(db_session)
    assert (await da.resolve_drive_account(db_session, s)).id == b.id


async def test_resolve_none_when_no_accounts(db_session):
    s = await _mk_stream(db_session)
    assert await da.resolve_drive_account(db_session, s) is None


async def test_resolve_none_when_assigned_broken(db_session):
    a = await _mk_account(db_session, "A", status="error", last_error="x")
    s = await _mk_stream(db_session, drive_account_id=a.id)
    assert await da.resolve_drive_account(db_session, s) is None


# ---------- drive_account_id di update stream ----------

async def test_update_stream_drive_account(app_client, db_session):
    acc = await _mk_account(db_session, "Akun A")
    s = await _mk_stream(db_session)
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    auth_as(app, make_user(role="super_admin"))
    async with _client(app) as c:
        r = await c.put(f"/api/admin/streams/{s.id}",
                        json={"drive_account_id": str(acc.id)})
        assert r.status_code == 200, r.text
        await db.refresh(s)
        assert s.drive_account_id == acc.id
        # null eksplisit = kembali ke default
        r = await c.put(f"/api/admin/streams/{s.id}", json={"drive_account_id": None})
        assert r.status_code == 200, r.text
        await db.refresh(s)
        assert s.drive_account_id is None
        # akun tak ada = 404
        r = await c.put(f"/api/admin/streams/{s.id}",
                        json={"drive_account_id": str(uuid.uuid4())})
        assert r.status_code == 404
