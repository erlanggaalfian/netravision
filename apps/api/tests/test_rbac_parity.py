"""Test paritas RBAC v2.0: super_admin, cakupan admin, masking RTSP, can_playback."""

import os
import sys

# deploy/seed_admin.py ada di root repo (sejajar apps/), bukan di sys.path test.
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.rbac import (
    _check_camera_access,
    can_manage_user,
    is_super_admin,
    mask_rtsp_url,
    require_super_admin,
)
from app.models.access import StreamAdminGrant, StreamPermission
from app.models.streams import Stream
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_hierarchy(db):
    """super(1) > admin_a(2) > user_u(3); admin_b(4) mandiri."""
    super_ = make_user(id=1, username="super", role="super_admin")
    admin_a = make_user(id=2, username="admin_a", role="admin", parent_admin_id=1)
    user_u = make_user(
        id=3, username="user_u", role="user", parent_admin_id=2
    )
    admin_b = make_user(id=4, username="admin_b", role="admin", parent_admin_id=1)
    db.add_all([super_, admin_a, user_u, admin_b])
    await db.commit()
    return super_, admin_a, user_u, admin_b


def test_is_super_admin():
    assert is_super_admin(make_user(role="super_admin"))
    assert not is_super_admin(make_user(role="admin"))
    assert not is_super_admin(make_user(role="user"))


def test_can_manage_user_matrix():
    super_, admin_a, user_u, admin_b = (
        make_user(id=1, username="super", role="super_admin"),
        make_user(id=2, username="a", role="admin", parent_admin_id=1),
        make_user(id=3, username="u", role="user", parent_admin_id=2),
        make_user(id=4, username="b", role="admin", parent_admin_id=1),
    )
    assert can_manage_user(super_, admin_a)
    assert can_manage_user(super_, super_)
    # admin kelola buatannya + dirinya sendiri
    assert can_manage_user(admin_a, user_u)
    assert can_manage_user(admin_a, admin_a)
    # admin tak boleh kelola sesama admin / super_admin / user orang lain
    assert not can_manage_user(admin_a, admin_b)
    assert not can_manage_user(admin_a, super_)
    other = make_user(id=5, username="x", role="user", parent_admin_id=4)
    assert not can_manage_user(admin_a, other)
    # non-admin tak bisa kelola siapa pun
    assert not can_manage_user(user_u, user_u)


async def test_admin_cannot_create_super_admin(app_client):
    app, _, db = app_client
    _, admin_a, _, _ = await _seed_hierarchy(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/users",
            json={"username": "jahat", "password": "rahasia123", "role": "super_admin"},
        )
        assert r.status_code == 403, r.text


async def test_super_admin_can_create_super_admin(app_client):
    app, _, db = app_client
    super_, _, _, _ = await _seed_hierarchy(db)
    auth_as(app, super_)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/users",
            json={"username": "super2", "password": "rahasia123", "role": "super_admin"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "super_admin"
        assert r.json()["parent_admin_id"] == super_.id
        assert r.json()["dibuat_oleh"] == "super"


async def test_admin_scoped_list(app_client):
    app, _, db = app_client
    _, admin_a, user_u, admin_b = await _seed_hierarchy(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        names = {u["username"] for u in (await c.get("/api/admin/users")).json()}
        assert names == {"admin_a", "user_u"}, names
        assert not {"admin_b"} & names
    auth_as(app, admin_b)
    async with _client(app) as c:
        names = {u["username"] for u in (await c.get("/api/admin/users")).json()}
        assert names == {"admin_b"}, names


async def test_admin_cannot_manage_other_admin(app_client):
    app, _, db = app_client
    _, admin_a, _, admin_b = await _seed_hierarchy(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.put(f"/api/admin/users/{admin_b.id}", json={"is_active": False})
        assert r.status_code == 403, r.text
        r = await c.delete(f"/api/admin/users/{admin_b.id}")
        assert r.status_code == 403, r.text


async def test_admin_cannot_touch_super_admin(app_client):
    app, _, db = app_client
    super_, admin_a, _, _ = await _seed_hierarchy(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.put(f"/api/admin/users/{super_.id}", json={"show_ads": False})
        assert r.status_code == 403, r.text


async def test_update_username(app_client):
    app, _, db = app_client
    super_, _, user_u, _ = await _seed_hierarchy(db)
    # user_u parent=admin_a(2); super boleh kelola
    auth_as(app, super_)
    async with _client(app) as c:
        r = await c.put(
            f"/api/admin/users/{user_u.id}", json={"username": "user_baru"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["username"] == "user_baru"


async def _stream(db, sid, owner_id, rtsp="rtsp://x/cam"):
    s = Stream(id=sid, name=f"cam{sid}", rtsp_url=rtsp, owner_id=owner_id)
    db.add(s)
    await db.commit()
    return s


async def test_mask_rtsp(db_session):
    db = db_session
    super_ = make_user(id=1, username="super", role="super_admin")
    admin_a = make_user(id=2, username="a", role="admin")
    user_u = make_user(id=3, username="u", role="user")
    db.add_all([super_, admin_a, user_u])
    s = await _stream(db, 10, owner_id=2)  # milik admin_a
    # toleran: kolom created_by belum ada di model (lihat _rbac_patch_notes.md)
    assert await mask_rtsp_url(s, super_, db) == "rtsp://x/cam"
    assert await mask_rtsp_url(s, admin_a, db) == "rtsp://x/cam"  # fallback owner_id
    assert await mask_rtsp_url(s, user_u, db) == ""
    s2 = await _stream(db, 11, owner_id=1)  # milik super
    assert await mask_rtsp_url(s2, admin_a, db) == ""
    # grant can_manage membuka masking (sesuai spec tugas)
    db.add(StreamAdminGrant(stream_id=11, admin_id=2, can_manage=True))
    await db.commit()
    assert await mask_rtsp_url(s2, admin_a, db) == "rtsp://x/cam"


async def test_need_playback_role_perm(db_session):
    db = db_session
    user_u = make_user(id=3, username="u", role="user")
    db.add(user_u)
    await _stream(db, 20, owner_id=1)
    db.add(
        StreamPermission(
            stream_id=20, role="user", can_view=True, can_playback=False
        )
    )
    await db.commit()
    # tonton boleh, playback ditolak
    out = await _check_camera_access(20, user_u, db, need_playback=False)
    assert out.id == 3
    with pytest.raises(HTTPException) as e:
        await _check_camera_access(20, user_u, db, need_playback=True)
    assert e.value.status_code == 403
    # can_playback=True -> lolos
    perm = (
        (await db.execute(select(StreamPermission).where(StreamPermission.stream_id == 20)))
        .scalars()
        .first()
    )
    perm.can_playback = True
    await db.commit()
    out = await _check_camera_access(20, user_u, db, need_playback=True)
    assert out.id == 3


async def test_need_playback_admin_owns_or_grant(db_session):
    db = db_session
    admin_a = make_user(id=2, username="a", role="admin")
    db.add(admin_a)
    await _stream(db, 30, owner_id=2)  # miliknya
    await _stream(db, 31, owner_id=1)  # milik super
    # milik sendiri -> lolos playback
    out = await _check_camera_access(30, admin_a, db, need_playback=True)
    assert out.id == 2
    # milik orang lain tanpa grant -> 403
    with pytest.raises(HTTPException) as e:
        await _check_camera_access(31, admin_a, db, need_playback=True)
    assert e.value.status_code == 403
    # dengan grant can_manage -> lolos
    db.add(StreamAdminGrant(stream_id=31, admin_id=2, can_manage=True))
    await db.commit()
    out = await _check_camera_access(31, admin_a, db, need_playback=True)
    assert out.id == 2
    # super_admin selalu lolos
    super_ = make_user(id=1, username="super", role="super_admin")
    out = await _check_camera_access(31, super_, db, need_playback=True)
    assert out.id == 1


async def test_require_super_admin_dependency():
    # dipanggil langsung sebagai dependency function
    out = await require_super_admin(make_user(role="super_admin"))
    assert out.role == "super_admin"
    with pytest.raises(HTTPException) as e:
        await require_super_admin(make_user(role="admin"))
    assert e.value.status_code == 403


async def test_seed_super_admin_idempotent(tmp_path):
    from deploy.seed_admin import ensure_admin
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.base import Base

    url = f"sqlite+aiosqlite:///{tmp_path}/seed.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    r1 = await ensure_admin("bos", "rahasia123", url)
    assert r1 == "created:super_admin", r1
    r2 = await ensure_admin("bos", "rahasia123", url)
    assert r2 == "exists", r2
    r3 = await ensure_admin("op", "rahasia123", url)
    assert r3 == "created:admin", r3
