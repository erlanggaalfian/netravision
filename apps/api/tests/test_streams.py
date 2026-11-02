"""Test router streams: list (filter akses), reconnect, poster 404."""

from httpx import ASGITransport, AsyncClient

from app.models.access import UserStreamAccess
from app.models.streams import Stream
from tests.conftest import auth_as, make_user


async def _seed(db):
    admin = make_user()
    op = make_user(id=2, username="op", role="user")
    s1 = Stream(
        id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
        main_url="rtsp://cam/1", sub_url="rtsp://cam/1_sub",
        brand="generic", is_active=True,
    )
    s2 = Stream(
        id=2, name="Cam 2", rtsp_url="rtsp://cam/2",
        main_url="rtsp://cam/2", sub_url=None,
        brand="generic", is_active=True,
    )
    db.add_all([admin, op, s1, s2,
                UserStreamAccess(user_id=2, stream_id=1, can_view=True)])
    await db.commit()
    return admin, op


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_list_streams_admin_sees_all(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/streams")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert body[0]["whep_main_url"] == "/whep/stream_1/whep"
    assert body[0]["whep_sub_url"] == "/whep/stream_1_sub/whep"
    assert body[1]["whep_sub_url"] is None
    assert body[0]["poster_url"] == "/api/posters/stream_1.jpg"


async def test_list_streams_user_filtered(app_client):
    app, _, db = app_client
    _, op = await _seed(db)
    auth_as(app, op)
    async with _client(app) as c:
        r = await c.get("/api/streams")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["id"] for s in body] == [1]


async def test_reconnect_ok(app_client):
    app, fake, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/streams/1/reconnect")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert fake.paths["stream_1"] == "rtsp://cam/1"
    assert fake.paths["stream_1_sub"] == "rtsp://cam/1_sub"


async def test_reconnect_404(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/streams/99/reconnect")
    assert r.status_code == 404


async def test_poster_404(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/posters/stream_1.jpg")
    assert r.status_code == 404
