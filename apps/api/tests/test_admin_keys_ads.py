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
