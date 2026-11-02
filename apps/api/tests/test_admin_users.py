"""Test router admin_users: CRUD user, camera-access, grants, overview."""

from httpx import ASGITransport, AsyncClient

from app.models.streams import Stream
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(db):
    admin = make_user()
    op = make_user(id=2, username="op", role="user")
    db.add_all([admin, op])
    await db.commit()
    return admin, op


async def test_user_crud(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/users",
            json={"username": "budi", "password": "rahasia123", "role": "user"},
        )
        assert r.status_code == 201, r.text
        uid = r.json()["id"]

        r = await c.get("/api/admin/users")
        assert any(u["username"] == "budi" for u in r.json())

        r = await c.put(f"/api/admin/users/{uid}", json={"role": "admin"})
        assert r.json()["role"] == "admin"

        # tidak boleh hapus diri sendiri
        r = await c.delete("/api/admin/users/1")
        assert r.status_code == 400

        # paritas v2.0: sesama admin tidak saling mengelola
        r = await c.delete(f"/api/admin/users/{uid}")
        assert r.status_code == 403


async def test_camera_access(app_client):
    app, _, db = app_client
    admin, op = await _seed(db)
    db.add(
        Stream(
            id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
            main_url="rtsp://cam/1", is_active=True,
        )
    )
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/users/2/camera-access", json={"stream_ids": [1]}
        )
        assert r.json() == {"ok": True, "stream_ids": [1]}

        r = await c.get("/api/admin/users/2/camera-access")
        assert r.json()["stream_ids"] == [1]

        # alias legacy
        r = await c.post(
            "/api/admin/users/2/access", json={"stream_ids": []}
        )
        assert r.json()["stream_ids"] == []


async def test_admin_grants_and_overview(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    db.add(
        Stream(
            id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
            main_url="rtsp://cam/1", is_active=True,
        )
    )
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/admins/1/camera-grants", json={"stream_ids": [1]}
        )
        assert r.json() == {"ok": True, "stream_ids": [1]}

        r = await c.get("/api/admin/admins/1/camera-grants")
        assert r.json()["stream_ids"] == [1]

        r = await c.get("/api/admin/access-overview")
        data = r.json()
        assert data["roles"]["admin"] == 1
        assert data["roles"]["user"] == 1


async def test_non_admin_ditolak(app_client):
    app, _, db = app_client
    _, op = await _seed(db)
    auth_as(app, op)
    async with _client(app) as c:
        r = await c.get("/api/admin/users")
        assert r.status_code == 403
