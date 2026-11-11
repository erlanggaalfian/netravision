"""Test router streams: list (filter akses), reconnect, poster 404."""

from httpx import ASGITransport, AsyncClient

from app.models.access import StreamAdminGrant, UserStreamAccess
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
                UserStreamAccess(user_id=2, stream_id=1, can_view=True),
                # A-T2: admin biasa hanya melihat kamera yang di-grant.
                # Beri admin grant can_view + can_playback untuk kedua kamera
                # agar tes list/reconnect/poster menguji jalurnya, bukan 403.
                StreamAdminGrant(stream_id=1, admin_id=1, can_view=True, can_playback=True),
                StreamAdminGrant(stream_id=2, admin_id=1, can_view=True, can_playback=True)])
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
    assert body[1]["whep_sub_url"] == "/whep/stream_2_sub/whep"  # sub transkode selalu ada (v2)
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
    # Pola v2: sub = transkode ffmpeg dari main, bukan URL sub kamera.
    sub = fake.confs["stream_1_sub"]
    assert sub["source"] == "publisher"
    assert "rtsp://127.0.0.1:$RTSP_PORT/stream_1 " in sub["runOnDemand"]
    assert fake.confs["stream_1"]["sourceOnDemand"] is False


async def test_reconnect_pertahankan_record(app_client):
    app, fake, db = app_client
    admin, _ = await _seed(db)
    from app.models.streams import Stream

    st = await db.get(Stream, 1)
    st.recording_enabled = True
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/streams/1/reconnect")
    assert r.status_code == 200, r.text
    assert fake.records["stream_1"] is True
    assert fake.records["stream_1_sub"] is False  # sub tidak direkam (v2)


async def test_reconnect_404(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/streams/99/reconnect")
    assert r.status_code == 404


async def test_poster_404(app_client, monkeypatch, tmp_path):
    # Isolasi dari sisa file demo di working directory: posters_dir default
    # (data/posters) di VM ini berisi stream_1.jpg..stream_4.jpg dari worker
    # poster demo, sehingga tanpa override tes yang mengharapkan 404 ini
    # mendapat 200. Arahkan ke direktori kosong di tmp_path.
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "posters_dir", str(tmp_path / "posters"))
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/posters/stream_1.jpg")
    assert r.status_code == 404


async def test_poster_token_query_param(app_client, monkeypatch, tmp_path):
    """Poster bisa diakses via ?token= (untuk <img> tanpa header)."""
    from app.core.config import get_settings
    from app.core.security import create_access_token

    # Isolasi posters_dir (lihat test_poster_404): file demo di working
    # directory tidak boleh membuat tes 404 ini lolos/ gagal tergantung mesin.
    monkeypatch.setattr(get_settings(), "posters_dir", str(tmp_path / "posters"))
    app, _, db = app_client
    admin, _ = await _seed(db)
    # Tanpa override auth - pakai JWT asli.
    tok = create_access_token(admin.id, admin.username, admin.role, get_settings())
    async with _client(app) as c:
        r = await c.get(f"/api/posters/stream_1.jpg?token={tok}")
        assert r.status_code == 404  # auth lolos, file belum ada
        r2 = await c.get("/api/posters/stream_1.jpg?token=palsu")
        assert r2.status_code == 401
