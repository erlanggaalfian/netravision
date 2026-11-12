"""Test router admin_streams: grup CRUD, scan, create, owner."""

from httpx import ASGITransport, AsyncClient

from app.models.access import StreamAdminGrant
from app.models.streams import Stream
from tests.conftest import auth_as, make_user


async def _seed(db):
    # Admin di produksi selalu punya grup (ditentukan _tentukan_grup);
    # op satu grup dengan admin agar Bagikan diizinkan.
    admin = make_user(admin_group="grup-jakarta")
    op = make_user(id=2, username="op", role="user", admin_group="grup-jakarta")
    db.add_all([admin, op])
    await db.commit()
    return admin, op


async def _seed_super(db):
    """Superadmin untuk operasi kamera (tambah/ubah/hapus/owner/grup)."""
    su = make_user(id=9, username="super", role="super_admin")
    db.add(su)
    await db.commit()
    return su


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_group_crud(app_client):
    app, _, db = app_client
    await _seed(db)
    su = await _seed_super(db)
    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1", main_url="rtsp://cam/1", is_active=True)
    db.add(s)
    await db.commit()
    # Grup kamera hanya diatur superadmin.
    auth_as(app, su)
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
            "user": "admin", "password": "x", "probe": False,
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
            "user": "admin", "password": "x", "probe": False,
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
    await _seed(db)
    su = await _seed_super(db)
    auth_as(app, su)
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
    _, op = await _seed(db)
    su = await _seed_super(db)
    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1", main_url="rtsp://cam/1", is_active=True)
    db.add(s)
    await db.commit()
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams/1/owner", json={"user_id": 2})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "owner_id": 2}
        r = await c.post("/api/admin/streams/1/owner", json={"user_id": 99})
        assert r.status_code == 404


async def test_stream_crud_hanya_superadmin(app_client):
    """Admin biasa tidak boleh tambah/ubah/hapus kamera; hanya
    superadmin. Admin hanya boleh membagikan (lewat sharing)."""
    app, _, db = app_client
    admin, _ = await _seed(db)
    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1", main_url="rtsp://cam/1", is_active=True)
    db.add(s)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams", json={"name": "Cam Baru", "rtsp_url": "rtsp://cam/1"})
        assert r.status_code == 403, r.text
        r = await c.put("/api/admin/streams/1", json={"name": "Cam Ubah"})
        assert r.status_code == 403, r.text
        r = await c.delete("/api/admin/streams/1")
        assert r.status_code == 403, r.text
        r = await c.post("/api/admin/streams/1/owner", json={"user_id": 2})
        assert r.status_code == 403, r.text
        r = await c.put("/api/admin/groups/Gedung-A", json={"name": "Gedung-A"})
        assert r.status_code == 403, r.text
    # Superadmin tetap boleh.
    su = await _seed_super(db)
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.put("/api/admin/streams/1", json={"name": "Cam Ubah"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Cam Ubah"


async def test_disks(app_client):
    app, _, db = app_client
    admin, _ = await _seed(db)
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/admin/disk-summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] > 0 and body["free"] >= 0


async def _seed_stream(db):
    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
               main_url="rtsp://cam/1", is_active=True)
    db.add(s)
    await db.commit()
    return s


async def test_sharing_crud(app_client):
    app, _, db = app_client
    admin, op = await _seed(db)
    await _seed_stream(db)
    # Admin yang membagikan wajib punya grant can_reshare atas kameranya.
    db.add(StreamAdminGrant(admin_id=admin.id, stream_id=1))
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.get("/api/admin/streams/1/sharing")
        assert r.status_code == 200 and r.json()["user_ids"] == []

        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": [op.id]})
        assert r.status_code == 200, r.text
        assert r.json()["user_ids"] == [op.id]

        r = await c.get("/api/admin/streams/1/sharing")
        assert r.json()["user_ids"] == [op.id]

        # Cabut akses.
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": []})
        assert r.status_code == 200
        r = await c.get("/api/admin/streams/1/sharing")
        assert r.json()["user_ids"] == []

        # Stream tidak ada / user tidak ada.
        r = await c.get("/api/admin/streams/99/sharing")
        assert r.status_code == 404
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": [999]})
        assert r.status_code == 400


async def test_sharing_reshare_ditolak(app_client):
    """Admin tanpa grant can_reshare tidak bisa membagikan kamera;
    grant live saja tidak boleh membagikan playback."""
    app, _, db = app_client
    admin, op = await _seed(db)
    await _seed_stream(db)
    auth_as(app, admin)
    async with _client(app) as c:
        # Tanpa grant sama sekali.
        r = await c.post(
            "/api/admin/streams/1/sharing",
            json={"shares": [{"user_id": op.id, "can_playback": False}]},
        )
        assert r.status_code == 403

        # Grant live + reshare, tanpa playback.
        db.add(
            StreamAdminGrant(
                admin_id=admin.id,
                stream_id=1,
                can_view=True,
                can_playback=False,
                can_reshare=True,
            )
        )
        await db.commit()
        r = await c.post(
            "/api/admin/streams/1/sharing",
            json={"shares": [{"user_id": op.id, "can_playback": True}]},
        )
        assert r.status_code == 403
        r = await c.post(
            "/api/admin/streams/1/sharing",
            json={"shares": [{"user_id": op.id, "can_playback": False}]},
        )
        assert r.status_code == 200


async def test_sharing_cakupan_admin_grup(app_client):
    """Admin biasa hanya boleh membagikan ke user/guest di grupnya
    sendiri, bukan ke diri sendiri atau ke admin lain. Baris di luar
    cakupannya (superadmin, user grup lain) dipertahankan saat ia
    menyimpan. Superadmin tetap boleh ke semua."""
    app, _, db = app_client
    su = make_user(id=1, username="super", role="super_admin")
    admin_a = make_user(id=2, username="adminkota", role="admin", admin_group="grup-jakarta")
    user_jkt = make_user(id=3, username="petugas1", role="user", admin_group="grup-jakarta")
    user_bdg = make_user(id=4, username="petugas2", role="user", admin_group="grup-bandung")
    admin_b = make_user(id=5, username="adminlain", role="admin", admin_group="grup-jakarta")
    db.add_all([su, admin_a, user_jkt, user_bdg, admin_b])
    await _seed_stream(db)
    db.add(StreamAdminGrant(admin_id=admin_a.id, stream_id=1))
    await db.commit()

    # Superadmin membagikan dulu ke user grup lain (baris ini harus
    # dipertahankan saat admin_a menyimpan).
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": [user_bdg.id]})
        assert r.status_code == 200, r.text

    auth_as(app, admin_a)
    async with _client(app) as c:
        # Ke diri sendiri ditolak.
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": [admin_a.id]})
        assert r.status_code == 400, r.text
        # Ke user grup lain ditolak.
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": [user_bdg.id]})
        assert r.status_code == 400, r.text
        # Ke admin lain (satu grup sekalipun) ditolak: admin dikelola superadmin.
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": [admin_b.id]})
        assert r.status_code == 400, r.text
        # Ke user grup sendiri boleh.
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": [user_jkt.id]})
        assert r.status_code == 200, r.text
        # Baris user grup lain tetap ada (dipertahankan).
        r = await c.get("/api/admin/streams/1/sharing")
        assert sorted(r.json()["user_ids"]) == sorted([user_jkt.id, user_bdg.id])
        # Simpan kosong tidak menghapus baris di luar cakupan.
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": []})
        assert r.status_code == 200, r.text
        r = await c.get("/api/admin/streams/1/sharing")
        assert r.json()["user_ids"] == [user_bdg.id]

    # Superadmin tetap boleh membagikan ke siapa saja dan mengganti semua.
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/streams/1/sharing",
            json={"user_ids": [admin_a.id, user_jkt.id]},
        )
        assert r.status_code == 200, r.text
        r = await c.get("/api/admin/streams/1/sharing")
        assert sorted(r.json()["user_ids"]) == sorted([admin_a.id, user_jkt.id])


async def test_sharing_grants_view_access(app_client):
    """User biasa hanya melihat kamera yang di-sharing kepadanya."""
    app, _, db = app_client
    admin, op = await _seed(db)
    db.add(Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
                  main_url="rtsp://cam/1", is_active=True))
    db.add(Stream(id=2, name="Cam 2", rtsp_url="rtsp://cam/2",
                  main_url="rtsp://cam/2", is_active=True))
    await db.commit()
    # Admin yang membagikan wajib punya grant can_reshare atas kameranya.
    db.add(StreamAdminGrant(admin_id=admin.id, stream_id=1))
    await db.commit()

    auth_as(app, op)
    async with _client(app) as c:
        r = await c.get("/api/streams")
        assert r.json() == []

    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams/1/sharing", json={"user_ids": [op.id]})
        assert r.status_code == 200

    auth_as(app, op)
    async with _client(app) as c:
        r = await c.get("/api/streams")
        names = [s["name"] for s in r.json()]
        assert names == ["Cam 1"]


async def test_update_toggle_record_patch_mediamtx(app_client):
    """PUT recording_enabled mem-patch record path main (sub tidak direkam)."""
    app, fake, db = app_client
    admin = make_user(role="super_admin")
    s = Stream(id=1, name="Cam 1", rtsp_url="rtsp://u:p@cam/1",
               main_url="rtsp://u:p@cam/1", sub_url="rtsp://u:p@cam/1_sub")
    db.add_all([admin, s])
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.put("/api/admin/streams/1", json={"recording_enabled": True})
    assert r.status_code == 200, r.text
    assert fake.patches["stream_1"] == {"record": True}
    assert "stream_1_sub" not in fake.patches
    async with _client(app) as c:
        r = await c.put("/api/admin/streams/1", json={"recording_enabled": False})
    assert r.status_code == 200, r.text
    assert fake.patches["stream_1"]["record"] is False
