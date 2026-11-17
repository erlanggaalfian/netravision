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
        brand="generic", is_active=True, group_name="MRI",
        # A-1.3: reconnect hanya super_admin/pemilik; admin seed adalah
        # pemilik kedua kamera supaya tes reconnect menguji jalurnya.
        created_by=1,
    )
    s2 = Stream(
        id=2, name="Cam 2", rtsp_url="rtsp://cam/2",
        main_url="rtsp://cam/2", sub_url=None,
        created_by=1,
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
    # Transcoder mati total (2026-11-14): sub hanya ada bila kamera
    # punya sub_url asli; Cam 2 tanpa sub_url -> whep_sub_url None
    # dan frontend memakai main sebagai fallback (tile tidak hitam).
    assert body[1]["whep_sub_url"] is None
    assert body[0]["poster_url"] == "/api/posters/stream_1.jpg"
    # group_name ikut di respons (dipakai filter grup di halaman Live).
    assert body[0]["group_name"] == "MRI"
    assert body[1]["group_name"] is None


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
    # Transcoder mati total (2026-11-14): main tanpa runOnReady ffmpeg,
    # sub native dari sub_url kamera (bukan publisher/transcode).
    main = fake.confs["stream_1"]
    assert main["sourceOnDemand"] is False
    assert "runOnReady" not in main
    assert "runOnReadyRestart" not in main
    sub = fake.confs["stream_1_sub"]
    assert sub["source"] == "rtsp://cam/1_sub"
    assert sub["rtspTransport"] == "tcp"
    assert sub["sourceOnDemand"] is False
    assert sub["runOnDemand"] == ""


async def test_reconnect_tanpa_sub_tidak_buat_path_sub(app_client):
    """Reconnect kamera tanpa sub_url: hanya main yang didaftarkan,
    path sub TIDAK dibuat (transcoder mati total)."""
    app, fake, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/streams/2/reconnect")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert fake.paths["stream_2"] == "rtsp://cam/2"
    assert "stream_2_sub" not in fake.confs
    assert "stream_2_sub" in fake.deleted


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
    # Rekaman dari SUB bila kamera punya sub (perintah user 2026-11-14):
    # main berhenti merekam, sub yang merekam.
    assert fake.records["stream_1"] is False
    assert fake.records["stream_1_sub"] is True


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
        # 4.5: poster TIDAK lagi menerima ?token= (token di query string
        # masuk log Apache); token hanya lewat header Authorization,
        # jadi token valid di query pun ditolak 401.
        r = await c.get(f"/api/posters/stream_1.jpg?token={tok}")
        assert r.status_code == 401
        r2 = await c.get("/api/posters/stream_1.jpg?token=palsu")
        assert r2.status_code == 401
        # Header Authorization tetap diterima: auth lolos, file belum ada.
        r3 = await c.get(
            "/api/posters/stream_1.jpg",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r3.status_code == 404
