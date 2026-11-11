"""Paritas iklan v2.0: show_ads per pengguna + skema Ad Space Config."""

from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.security import create_access_token
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _token(user) -> str:
    s = get_settings()
    return create_access_token(user.id, user.username, user.role, s)


async def test_user_show_ads_crud(app_client):
    app, _, db = app_client
    admin = make_user()
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        # create dengan show_ads=False
        r = await c.post(
            "/api/admin/users",
            json={
                "username": "tamu1",
                "password": "rahasia123",
                "role": "user",
                "show_ads": False,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["show_ads"] is False
        uid = r.json()["id"]

        # list memuat show_ads
        r = await c.get("/api/admin/users")
        row = next(u for u in r.json() if u["username"] == "tamu1")
        assert row["show_ads"] is False

        # update via PUT
        r = await c.put(f"/api/admin/users/{uid}", json={"show_ads": True})
        assert r.json()["show_ads"] is True

        # default True untuk user baru tanpa show_ads eksplisit
        r = await c.post(
            "/api/admin/users",
            json={"username": "tamu2", "password": "rahasia123", "role": "user"},
        )
        assert r.json()["show_ads"] is True


async def test_ad_config_respects_show_ads(app_client):
    app, _, db = app_client
    admin = make_user(role="super_admin")
    noads = make_user(id=2, username="noads", role="user", show_ads=False)
    yesads = make_user(id=3, username="yesads", role="user", show_ads=True)
    db.add_all([admin, noads, yesads])
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        # set config aktif dengan marquee
        r = await c.post(
            "/api/admin/ad-config",
            json={"marquee_text": "Promo!", "is_active": True, "box_width": 80},
        )
        assert r.status_code == 200, r.text
        assert r.json()["marquee_text"] == "Promo!"
        assert r.json()["box_width"] == 80

        # user show_ads=False → config nonaktif (via ?token=)
        r = await c.get("/api/ad-config", params={"token": _token(noads)})
        body = r.json()
        assert body["is_active"] is False
        assert body["marquee_text"] == ""
        assert body["image_url"] == ""

        # user show_ads=False → nonaktif juga via header Authorization
        r = await c.get(
            "/api/ad-config",
            headers={"Authorization": f"Bearer {_token(noads)}"},
        )
        assert r.json()["is_active"] is False

        # user show_ads=True → sesuai config tersimpan
        r = await c.get("/api/ad-config", params={"token": _token(yesads)})
        assert r.json()["is_active"] is True
        assert r.json()["marquee_text"] == "Promo!"

        # tanpa token → config normal (publik, tanpa 401)
        r = await c.get("/api/ad-config")
        assert r.status_code == 200
        assert r.json()["is_active"] is True


async def test_ad_config_roundtrip_new_fields(app_client):
    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        payload = {
            "image_url": "/uploads/ads/x.png",
            "marquee_text": "Halo dunia",
            "bg_color": "#000000",
            "text_color": "#ff0000",
            "scroll_speed": 8,
            "font_size": 14,
            "font_family": "serif",
            "image_opacity": 0.5,
            "bg_opacity": 0.7,
            "text_opacity": 0.9,
            "is_active": True,
            "box_width": 60,
            "text_align": "center",
            "image_height": 40,
            "embed_timeout_seconds": 120,
            "click_to_play": False,
        }
        r = await c.post("/api/admin/ad-config", json=payload)
        assert r.status_code == 200, r.text
        saved = r.json()
        for k, v in payload.items():
            assert saved[k] == v, k

        r = await c.get("/api/ad-config")
        got = r.json()
        for k, v in payload.items():
            assert got[k] == v, k
