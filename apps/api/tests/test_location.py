"""Test location: parser multi-format + endpoint resolve-location.

Semua format lokal diuji tanpa jaringan. Geocoding alamat dan tautan
pendek diuji dengan mock httpx supaya tidak bergantung jaringan.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.services.location import (
    LocationError,
    parse_decimal,
    parse_dms,
    parse_google_maps_url,
    parse_plus_code,
    resolve_location,
)
from tests.conftest import auth_as, make_user


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- Koordinat desimal ------------------------------------------------------

def test_decimal_lat_lng():
    assert parse_decimal("-7.873522, 111.257658") == (-7.873522, 111.257658)


def test_decimal_spasi():
    assert parse_decimal("-7.873522 111.257658") == (-7.873522, 111.257658)


def test_decimal_lng_lat_ditukar():
    # Urutan lng,lat terdeteksi dari rentang dan ditukar.
    assert parse_decimal("111.257658, -7.873522") == (-7.873522, 111.257658)


def test_decimal_tidak_valid():
    assert parse_decimal("abc") is None
    assert parse_decimal("100, 200") is None  # di luar rentang keduanya
    assert parse_decimal("Jl. Merdeka 1") is None


# --- URL Google Maps ---------------------------------------------------------

def test_maps_at():
    assert parse_google_maps_url(
        "https://www.google.com/maps/@-7.873522,111.257658,15z"
    ) == (-7.873522, 111.257658)


def test_maps_q():
    assert parse_google_maps_url(
        "https://maps.google.com/?q=-7.873522,111.257658"
    ) == (-7.873522, 111.257658)


def test_maps_place():
    assert parse_google_maps_url(
        "https://www.google.com/maps/place/Ponorogo/@-7.873522,111.257658,17z"
    ) == (-7.873522, 111.257658)


def test_maps_data():
    assert parse_google_maps_url(
        "https://www.google.com/maps/place/X/data=!3d-7.873522!4d111.257658"
    ) == (-7.873522, 111.257658)


def test_maps_search():
    # Bentuk URL hasil redirect tautan pendek maps.app.goo.gl.
    assert parse_google_maps_url(
        "https://www.google.com/maps/search/-7.873522,+111.257658?entry=tts"
    ) == (-7.873522, 111.257658)


def test_maps_bukan_url():
    assert parse_google_maps_url("https://example.com/foo") is None


# --- Plus Code ---------------------------------------------------------------

def test_plus_code_lengkap():
    # Markas Google, nilai rujukan yang dikenal.
    lat, lng = parse_plus_code("849VCWC8+R9")
    assert abs(lat - 37.422) < 0.001
    assert abs(lng - (-122.084)) < 0.001


def test_plus_code_pendek_butuh_acuan():
    with pytest.raises(LocationError):
        parse_plus_code("CWC8+R9")


def test_plus_code_pendek_dengan_acuan():
    lat, lng = parse_plus_code("CWC8+R9", ref_lat=37.42, ref_lng=-122.08)
    assert abs(lat - 37.422) < 0.001
    assert abs(lng - (-122.084)) < 0.001


def test_plus_code_tidak_valid():
    assert parse_plus_code("ZZZZ+ZZZZ") is None
    assert parse_plus_code("tidak ada plus") is None


# --- DMS ----------------------------------------------------------------------

def test_dms_simbol():
    lat, lng = parse_dms("7°52'24.7\"S 111°15'27.6\"E")
    assert abs(lat - (-7.8735277)) < 1e-6
    assert abs(lng - 111.2576666) < 1e-6


def test_dms_spasi():
    lat, lng = parse_dms("7 52 24.7 S 111 15 27.6 E")
    assert abs(lat - (-7.8735277)) < 1e-6
    assert abs(lng - 111.2576666) < 1e-6


def test_dms_menit_desimal():
    lat, lng = parse_dms("7°52.4117'S 111°15.46'E")
    assert abs(lat - (-7.8735283)) < 1e-6


def test_dms_bukan_dms():
    assert parse_dms("hello world") is None
    assert parse_dms("Merdeka 1 2") is None


# --- Orkestrator + endpoint ----------------------------------------------------

async def test_resolve_decimal(app_client):
    got = await resolve_location("-7.873522, 111.257658")
    assert (got.latitude, got.longitude) == (-7.873522, 111.257658)
    assert got.format == "Koordinat desimal"


async def test_resolve_tidak_dikenali(monkeypatch):
    async def _no_geo(_text):
        return None

    import app.services.location as loc

    monkeypatch.setattr(loc, "geocode_address", _no_geo)
    with pytest.raises(LocationError):
        await resolve_location("asdfghjkl qwerty")


async def test_resolve_short_url_mock(monkeypatch):
    import httpx

    import app.services.location as loc

    class _FakeResp:
        url = "https://www.google.com/maps/@-7.873522,111.257658,15z"
        text = ""
        status_code = 200

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    got = await resolve_location("https://maps.app.goo.gl/pTktsJf8UZg1qZWW6")
    assert (got.latitude, got.longitude) == (-7.873522, 111.257658)
    assert got.format == "Tautan Google Maps"


async def test_resolve_geocode_mock(monkeypatch):
    import httpx

    import app.services.location as loc

    class _FakeResp:
        status_code = 200

        def json(self):
            return [{
                "lat": "-7.873522",
                "lon": "111.257658",
                "display_name": "Ponorogo, Jawa Timur",
            }]

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(loc, "_last_nominatim_call", 0.0)
    got = await resolve_location("Ponorogo, Jawa Timur")
    assert (got.latitude, got.longitude) == (-7.873522, 111.257658)
    assert got.format == "Alamat"
    assert got.place_name == "Ponorogo, Jawa Timur"


async def test_endpoint_decimal(app_client):
    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as client:
        r = await client.post(
            "/api/maps/resolve-location",
            json={"text": "-7.873522, 111.257658"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["latitude"] == -7.873522
    assert data["longitude"] == 111.257658
    assert data["format"] == "Koordinat desimal"


async def test_endpoint_tidak_dikenali(app_client, monkeypatch):
    app, _, db = app_client
    admin = make_user(role="super_admin")
    db.add(admin)
    await db.commit()
    auth_as(app, admin)

    async def _no_geo(_text):
        return None

    import app.services.location as loc

    monkeypatch.setattr(loc, "geocode_address", _no_geo)
    async with _client(app) as client:
        r = await client.post(
            "/api/maps/resolve-location", json={"text": "asdfghjkl qwerty"}
        )
    assert r.status_code == 422


async def test_endpoint_butuh_login(app_client):
    app, _, _ = app_client
    async with _client(app) as client:
        r = await client.post(
            "/api/maps/resolve-location", json={"text": "-7.87, 111.25"}
        )
    assert r.status_code == 401
