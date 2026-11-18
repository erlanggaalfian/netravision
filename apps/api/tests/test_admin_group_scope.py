"""Scoping admin per grup (S-4/S-7) + sweep RBAC per menu.

Aturan yang diuji di sini:
- Admin hanya melihat kamera milik/grant-nya (GET /admin/streams),
  grup yang berisi kamera itu (GET /admin/groups), dan grant grup
  hanya untuk kamera milik/grant-nya (GET /admin/groups/{nama}/camera-grants).
- Detail kamera grup lain ditolak 403 (sharing/grants/role-access).
- Pemilik kamera = created_by ATAU owner_id (bukan `created_by or owner_id`).
- list_users dan akses kamera memakai satu aturan visibilitas admin.
- Menu lain: maps resolve-location admin-only, disk-summary
  super_admin-only, playback picker hanya kamera berizin playback,
  OAuth state sekali pakai, lockout password API key.
"""

import os
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_password
from app.models.access import StreamAdminGrant, UserStreamAccess
from app.models.groups import GroupStream, StreamGroup
from app.models.keys import ApiKey
from app.models.streams import Stream
from app.models.users import User
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_scope(db):
    """Admin A (grup-a) vs admin B (grup-b); kamera + grup per admin."""
    su = make_user(id=1, username="super", role="super_admin")
    admin_a = make_user(id=2, username="admin_a", role="admin", admin_group="grup-a")
    admin_b = make_user(id=3, username="admin_b", role="admin", admin_group="grup-b")
    db.add_all([su, admin_a, admin_b])
    cam_a = Stream(
        id=10, name="Cam A", rtsp_url="rtsp://a/1", main_url="rtsp://a/1",
        is_active=True, created_by=2, owner_id=2, group_name="Grup A",
    )
    cam_b = Stream(
        id=11, name="Cam B", rtsp_url="rtsp://b/1", main_url="rtsp://b/1",
        is_active=True, created_by=3, owner_id=3, group_name="Grup B",
    )
    db.add_all([cam_a, cam_b])
    grp_a = StreamGroup(id=1, name="Grup A")
    grp_b = StreamGroup(id=2, name="Grup B")
    db.add_all([grp_a, grp_b])
    db.add_all([
        GroupStream(group_id=1, stream_id=10),
        GroupStream(group_id=2, stream_id=11),
    ])
    await db.commit()
    return su, admin_a, admin_b


async def test_admin_list_streams_hanya_milik_sendiri(app_client):
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.get("/api/admin/streams")
        assert r.status_code == 200, r.text
        ids = [s["id"] for s in r.json()]
        assert ids == [10], ids


async def test_admin_list_streams_kamera_grant_ikut_terlihat(app_client):
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    db.add(StreamAdminGrant(stream_id=11, admin_id=2, can_view=True))
    await db.commit()
    auth_as(app, admin_a)
    async with _client(app) as c:
        ids = [s["id"] for s in (await c.get("/api/admin/streams")).json()]
        assert ids == [10, 11], ids


async def test_admin_list_groups_hanya_grup_sendiri(app_client):
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        names = [g["name"] for g in (await c.get("/api/admin/groups")).json()]
        assert names == ["Grup A"], names


async def test_admin_group_grants_grup_lain_403(app_client):
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.get("/api/admin/groups/Grup%20B/camera-grants")
        assert r.status_code == 403, r.text
        r = await c.get("/api/admin/groups/Grup%20A/camera-grants")
        assert r.status_code == 200, r.text
        assert r.json()["stream_ids"] == [10]


async def test_admin_group_grants_hanya_kamera_sendiri(app_client):
    """Grup yang sama berisi kamera admin A dan B: admin A hanya
    mendapat id kameranya sendiri, bukan semua kamera grup itu."""
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    db.add(GroupStream(group_id=1, stream_id=11))
    await db.commit()
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.get("/api/admin/groups/Grup%20A/camera-grants")
        assert r.status_code == 200, r.text
        assert r.json()["stream_ids"] == [10]


async def test_admin_detail_kamera_grup_lain_403(app_client):
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        for path in (
            "/api/admin/streams/11/sharing",
            "/api/admin/streams/11/grants",
            "/api/admin/streams/11/role-access",
        ):
            r = await c.get(path)
            assert r.status_code == 403, (path, r.text)
        r = await c.get("/api/admin/streams/10/sharing")
        assert r.status_code == 200, r.text


async def test_admin_pemilik_lewat_owner_id_bukan_created_by(app_client):
    """Kamera dipasang super_admin (created_by=1) tapi dimiliki admin A
    (owner_id=2): admin A tetap melihatnya. Pola lama
    `created_by or owner_id` mengabaikan owner_id di kasus ini."""
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    db.add(Stream(
        id=12, name="Cam Milik A", rtsp_url="rtsp://a/2",
        main_url="rtsp://a/2", is_active=True, created_by=1, owner_id=2,
    ))
    await db.commit()
    auth_as(app, admin_a)
    async with _client(app) as c:
        ids = [s["id"] for s in (await c.get("/api/admin/streams")).json()]
        assert 12 in ids, ids
        ids = [s["id"] for s in (await c.get("/api/streams")).json()]
        assert 12 in ids, ids


async def test_admin_list_users_satu_aturan_visibilitas(app_client):
    app, _, db = app_client
    su, admin_a, _ = await _seed_scope(db)
    segrup = make_user(
        id=4, username="user_a", role="user", admin_group="grup-a",
        parent_admin_id=1,  # dibuat super_admin, tetap segrup
    )
    luar = make_user(
        id=5, username="user_b", role="user", admin_group="grup-b",
        parent_admin_id=1,
    )
    tamu = make_user(
        id=6, username="guest", role="guest", admin_group="grup-a",
        parent_admin_id=1, is_active=True,
    )
    db.add_all([segrup, luar, tamu])
    await db.commit()
    auth_as(app, admin_a)
    async with _client(app) as c:
        names = {u["username"] for u in (await c.get("/api/admin/users")).json()}
        assert names == {"admin_a", "user_a", "guest"}, names


async def test_admin_camera_access_peer_admin_403(app_client):
    app, _, db = app_client
    _, admin_a, admin_b = await _seed_scope(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.post(
            f"/api/admin/users/{admin_b.id}/camera-access",
            json={"stream_ids": [10]},
        )
        assert r.status_code == 403, r.text


async def test_disk_summary_agregat_boleh_admin(app_client):
    """Disk-summary agregat (bukan inventaris per kamera/grup) tetap
    bisa dibaca admin biasa, dikunci test_disks; yang super_admin-only
    adalah /admin/disks dan menu Penyimpanan."""
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    auth_as(app, admin_a)
    async with _client(app) as c:
        r = await c.get("/api/admin/disk-summary")
        assert r.status_code == 200, r.text


async def test_maps_resolve_hanya_admin(app_client):
    app, _, db = app_client
    _, admin_a, _ = await _seed_scope(db)
    user = make_user(id=9, username="user", role="user", admin_group="grup-a")
    db.add(user)
    await db.commit()
    async with _client(app) as c:
        auth_as(app, user)
        r = await c.post(
            "/api/maps/resolve-location", json={"text": "-7.87, 111.25"}
        )
        assert r.status_code == 403, r.text
        auth_as(app, admin_a)
        r = await c.post(
            "/api/maps/resolve-location", json={"text": "-7.87, 111.25"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["latitude"] == pytest.approx(-7.87)


async def test_recording_cameras_hanya_berizin_playback(app_client, monkeypatch):
    """Pemilih Putar Ulang tidak menampilkan kamera yang live-nya
    boleh tapi playback-nya tidak."""
    from app.routers import recordings as rec
    from app.services.recording import Segment

    app, _, db = app_client
    su, admin_a, _ = await _seed_scope(db)
    user = make_user(id=9, username="user", role="user", admin_group="grup-a")
    db.add(user)
    db.add(UserStreamAccess(user_id=9, stream_id=10, can_view=True, can_playback=False))
    db.add(UserStreamAccess(user_id=9, stream_id=11, can_view=True, can_playback=True))
    await db.commit()

    def fake_list(stream_id, day=None, recordings_dir=None, stream=None):
        return [Segment(start=datetime(2026, 11, 2, 10, 0), path="/tmp/x.mp4",
                        size=100, name="2026-11-02_10-00-00-000000.mp4")]

    monkeypatch.setattr(rec, "list_segments", fake_list)
    auth_as(app, user)
    async with _client(app) as c:
        r = await c.get("/api/recordings/cameras")
        assert r.status_code == 200, r.text
        ids = [s["id"] for s in r.json()]
        assert ids == [11], ids


async def test_multidisk_timeline_terbaca(app_client, tmp_path, monkeypatch):
    """Rekaman kamera record_disk tidak lagi hilang dari Putar Ulang."""
    from app.routers import recordings as rec
    from types import SimpleNamespace

    app, _, db = app_client
    su, _, _ = await _seed_scope(db)
    disk = tmp_path / "disk2"
    segdir = disk / "recordings" / "Grup_A" / "Cam_A" / "stream_10"
    segdir.mkdir(parents=True)
    (segdir / "2026-11-02_10-00-00-000000.mp4").write_bytes(b"x" * 100)
    stream = await db.get(Stream, 10)
    stream.record_disk = str(disk)
    stream.group_name = "Grup A"
    stream.name = "Cam A"
    await db.commit()
    monkeypatch.setattr(
        rec, "get_settings",
        lambda: SimpleNamespace(recordings_dir=str(tmp_path / "rec"), drive_enabled=False),
    )
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.get(
            "/api/recordings/10/timeline", params={"date": "2026-11-02"}
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["entries"]) == 1, r.json()


async def test_put_toggle_rekaman_sub_native(app_client):
    """PUT recording_enabled pada kamera bersub mengubah flag record
    di path SUB (sumber rekaman), bukan main saja."""
    app, fake_mtmx, db = app_client
    su, _, _ = await _seed_scope(db)
    stream = await db.get(Stream, 10)
    stream.sub_url = "rtsp://a/1sub"
    stream.recording_enabled = True
    await db.commit()
    auth_as(app, su)
    async with _client(app) as c:
        r = await c.put("/api/admin/streams/10", json={"recording_enabled": False})
        assert r.status_code == 200, r.text
        assert fake_mtmx.confs["stream_10_sub"]["record"] is False
        assert fake_mtmx.confs["stream_10"]["record"] is False
        r = await c.put("/api/admin/streams/10", json={"recording_enabled": True})
        assert r.status_code == 200, r.text
        assert fake_mtmx.confs["stream_10_sub"]["record"] is True
        assert fake_mtmx.confs["stream_10"]["record"] is False


async def test_oauth_state_sekali_pakai():
    from app.routers import admin_drive

    state = admin_drive._sign_state("acc-1")
    assert admin_drive._verify_state(state) == "acc-1"
    with pytest.raises(ValueError):
        admin_drive._verify_state(state)


async def test_external_kunci_password_5_salah(app_client):
    """Password API key salah 5x dalam 15 menit -> percobaan ke-6 429."""
    import hashlib

    app, _, db = app_client
    key = ApiKey(
        id=1, name="K", key_hash=hashlib.sha256(b"KUNCI-1").hexdigest(),
        password_hash=hash_password("benar123"), is_active=True,
    )
    db.add(key)
    db.add(Stream(id=10, name="Cam A", rtsp_url="rtsp://a/1",
                  main_url="rtsp://a/1", is_active=True))
    await db.commit()
    async with _client(app) as c:
        for _ in range(5):
            r = await c.get(
                "/api/external/cameras",
                headers={"X-Api-Key": "KUNCI-1", "X-Api-Key-Password": "salah"},
            )
            assert r.status_code == 403, r.text
        r = await c.get(
            "/api/external/cameras",
            headers={"X-Api-Key": "KUNCI-1", "X-Api-Key-Password": "salah"},
        )
        assert r.status_code == 429, r.text
