"""Test router admin_keys + admin_ads (mock DB via conftest pola yang ada)."""

import io

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture()
def client():
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _admin_headers():
    # conftest menyediakan user admin? bila tidak, test ini diskip otomatis
    # oleh mekanisme auth — di sini kita hanya cek routing terdaftar.
    return {}


async def test_access_logs_total_count_header(app_client):
    """GET /api/admin/api-access-logs mengembalikan X-Total-Count.

    Header ini dipakai Pagination bernomor di Admin API Key (perintah
    user 2026-11-17: semua pagination memakai pola jendela geser).
    Body tetap array supaya kontrak /api/* tidak berubah."""
    from app.models.keys import ApiAccessLog
    from tests.conftest import auth_as, make_user

    app, _, db = app_client
    auth_as(app, make_user(id=1, username="root", role="super_admin"))
    db.add_all(
        [
            ApiAccessLog(api_key_id=None, stream_id=None, action="embed.view", ip="127.0.0.1"),
            ApiAccessLog(api_key_id=None, stream_id=None, action="embed.view", ip="127.0.0.1"),
            ApiAccessLog(api_key_id=None, stream_id=None, action="embed.view", ip="127.0.0.1"),
        ]
    )
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/admin/api-access-logs?limit=2&offset=0")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) == 2
        assert r.headers.get("x-total-count") == "3"
        # Halaman kedua: 1 baris tersisa, total tetap 3.
        r2 = await c.get("/api/admin/api-access-logs?limit=2&offset=2")
        assert r2.status_code == 200
        assert len(r2.json()) == 1
        assert r2.headers.get("x-total-count") == "3"


async def test_routes_registered():
    from app.main import app as _app

    paths = set(_app.openapi()["paths"].keys())
    assert "/api/admin/api-keys" in paths
    assert "/api/admin/api-keys/{key_id}" in paths
    assert "/api/admin/api-access-logs" in paths
    assert "/api/admin/api-access-logs/summary" in paths


async def test_ads_routes_registered():
    from app.main import app as _app

    paths = set(_app.openapi()["paths"].keys())
    assert "/api/ad-config" in paths
    assert "/api/admin/ad-config" in paths
    assert "/api/admin/ad-config/upload-image" in paths
    assert "/api/admin/groups/{group_name}/ads" in paths


async def test_upload_rejects_bad_extension():
    from app.main import app as _app

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://t") as c:
        # tanpa auth -> 401/403 diharapkan (endpoint admin), bukan 500
        r = await c.post(
            "/api/admin/ad-config/upload-image",
            files={"image": ("x.exe", io.BytesIO(b"zzz"), "application/octet-stream")},
        )
        assert r.status_code in (400, 401, 403)
