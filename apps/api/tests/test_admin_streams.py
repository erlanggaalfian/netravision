"""Test router admin_streams: grup CRUD, scan, create, owner."""

from httpx import ASGITransport, AsyncClient

from app.models.streams import Stream
from tests.conftest import auth_as, make_user


async def _seed(db):
    admin = make_user()
    op = make_user(id=2, username="op", role="user")
    db.add_all([admin, op])
    await db.commit()
    return admin, op


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_group_crud(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1", main_url="rtsp://cam/1", is_active=True)
    db.add(s)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.put(
            "/api/admin/groups/Gedung-A",
            json={"name": "Gedung-A", "description": "Lantai 1"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Gedung-A"

        r = await c.get("/api/admin/groups/Gedung-A/camera-grants")
        assert r.json() == {"stream_ids": []}

        r = await c.post("/api/admin/groups/Gedung-A/camera-grants", json={"stream_ids": [1]})
        assert r.json() == {"ok": True, "stream_ids": [1]}

        r = await c.get("/api/admin/groups/Gedung-A/camera-grants")
        assert r.json() == {"stream_ids": [1]}

        r = await c.get("/api/admin/groups/Tidak-Ada/camera-grants")
        assert r.status_code == 404


async def test_scan_auto(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/scan", json={
            "brand": "auto", "host": "192.168.1.10",
            "user": "admin", "password": "x",
        })
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert len(cands) == 5
    brands = {c["brand"] for c in cands}
    assert brands == {"hikvision", "dahua", "uniview_ipc", "tplink_vigi", "reolink"}
    assert all(c["main_url"] and c["method"] == "brand" for c in cands)


async def test_scan_single_brand(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/scan", json={
            "brand": "dahua", "host": "192.168.1.11",
            "user": "admin", "password": "x",
        })
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert len(cands) == 1
    assert "subtype=0" in cands[0]["main_url"]
    assert "subtype=1" in cands[0]["sub_url"]


async def test_scan_preview(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/scan/preview",
                         json={"rtsp_url": "rtsp://h:554/h264Preview_01_main"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sub_url"] == "rtsp://h:554/h264Preview_01_sub"
    assert body["method"] == "explicit"


async def test_create_stream_registers_mediamtx(app_client):
    app, fake, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={
            "name": "Cam Baru", "rtsp_url": "rtsp://h:554/h264Preview_01_main",
        })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["brand"] == "generic"
    assert body["whep_sub_url"] == f"/whep/stream_{body['id']}_sub/whep"
    assert fake.paths[f"stream_{body['id']}"] == "rtsp://h:554/h264Preview_01_main"


async def test_set_owner(app_client):
    app, _, db = app_client
    admin, op = await _seed(db)
    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1", main_url="rtsp://cam/1", is_active=True)
    db.add(s)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams/1/owner", json={"user_id": 2})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "owner_id": 2}
        r = await c.post("/api/admin/streams/1/owner", json={"user_id": 99})
        assert r.status_code == 404


async def test_disks(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/admin/disks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] > 0 and body["free"] >= 0
