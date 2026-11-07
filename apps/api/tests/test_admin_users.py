"""Test router admin_users: CRUD user, camera-access, grants, overview."""

from httpx import ASGITransport, AsyncClient

from app.models.access import StreamAdminGrant
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
    # Admin yang membagikan wajib punya grant can_reshare atas kameranya.
    db.add(StreamAdminGrant(admin_id=admin.id, stream_id=1))
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


async def _seed_super_admin_and_guest(db):
    su = make_user(id=1, username="super", role="super_admin")
    guest = make_user(id=9, username="guest", role="guest", is_active=True)
    db.add_all([su, guest])
    await db.commit()
    return su, guest


async def test_create_guest_role_rejected(app_client):
    """Role guest tidak bisa dibuat manual (dibuat otomatis sistem)."""
    app, _, db = app_client
    su, _ = await _seed_super_admin_and_guest(db)
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/users",
            json={"username": "tamu2", "password": "rahasia123", "role": "guest"},
        )
        assert r.status_code == 400, r.text


async def test_update_guest_only_login_and_ads(app_client):
    """Guest hanya bisa diubah login dan iklannya; field lain ditolak."""
    app, _, db = app_client
    su, guest = await _seed_super_admin_and_guest(db)
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.put(f"/api/admin/users/{guest.id}", json={"role": "user"})
        assert r.status_code == 400, r.text
        r = await c.put(f"/api/admin/users/{guest.id}", json={"username": "tamu"})
        assert r.status_code == 400, r.text
        r = await c.put(
            f"/api/admin/users/{guest.id}",
            json={"is_active": False, "show_ads": False},
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        assert r.json()["show_ads"] is False


async def test_update_role_to_guest_rejected(app_client):
    """Mengubah peran user biasa menjadi guest ditolak."""
    app, _, db = app_client
    admin, op = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.put(f"/api/admin/users/{op.id}", json={"role": "guest"})
        assert r.status_code == 400, r.text


async def test_delete_guest_rejected(app_client):
    """Akun guest tidak bisa dihapus."""
    app, _, db = app_client
    su, guest = await _seed_super_admin_and_guest(db)
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.delete(f"/api/admin/users/{guest.id}")
        assert r.status_code == 400, r.text


async def test_guest_token_invalid_after_disable(app_client):
    """Menonaktifkan guest langsung mematikan token guest yang sudah ada."""
    app, _, db = app_client
    guest = make_user(id=9, username="guest", role="guest", is_active=True)
    db.add(guest)
    await db.commit()
    async with _client(app) as c:
        r = await c.post("/api/auth/guest", json={})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        guest.is_active = False
        await db.commit()
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, r.text
