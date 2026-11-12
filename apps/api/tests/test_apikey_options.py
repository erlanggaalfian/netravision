"""Opsi API key ala v2.0: custom_camera_name, include_playback, position."""

from httpx import ASGITransport, AsyncClient

from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_apikey_options_create_update(app_client):
    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    # A-S6: stream_ids divalidasi keberadaannya; seed kameranya dulu.
    from app.models.streams import Stream

    for i in (1, 2, 3):
        db.add(Stream(id=i, name=f"Cam {i}", rtsp_url=f"rtsp://x/{i}",
                      main_url=f"rtsp://x/{i}", is_active=True))
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        # create dengan opsi baru
        r = await c.post(
            "/api/admin/api-keys",
            json={
                "name": "Mitra A",
                "stream_ids": [3, 1, 2],
                "custom_camera_name": "Kamera Depan",
                "include_playback": False,
                "show_ads": False,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["custom_camera_name"] == "Kamera Depan"
        assert body["include_playback"] is False
        assert body["show_ads"] is False
        assert body["stream_ids"] == [3, 1, 2]  # urutan dipertahankan
        kid = body["id"]

        # list memuat opsi + urutan
        r = await c.get("/api/admin/api-keys")
        row = next(k for k in r.json() if k["id"] == kid)
        assert row["custom_camera_name"] == "Kamera Depan"
        assert row["include_playback"] is False
        assert row["show_ads"] is False
        assert row["stream_ids"] == [3, 1, 2]

        # update: ubah nama kustom, nyalakan playback, susun ulang kamera
        r = await c.put(
            f"/api/admin/api-keys/{kid}",
            json={
                "custom_camera_name": "Pos Jaga",
                "include_playback": True,
                "show_ads": True,
                "stream_ids": [2, 3],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["custom_camera_name"] == "Pos Jaga"
        assert body["include_playback"] is True
        assert body["show_ads"] is True
        assert body["stream_ids"] == [2, 3]

        # default: nama kustom kosong, playback aktif, iklan tampil
        r = await c.post(
            "/api/admin/api-keys",
            json={"name": "Mitra B", "stream_ids": []},
        )
        assert r.status_code == 201, r.text
        assert r.json()["custom_camera_name"] == ""
        assert r.json()["include_playback"] is True
        assert r.json()["show_ads"] is True


async def test_logs_offset_and_status_filter(app_client):
    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        # tanpa log -> list kosong, offset tidak error
        r = await c.get("/api/admin/api-access-logs?limit=10&offset=5&status=ok")
        assert r.status_code == 200, r.text
        assert r.json() == []
