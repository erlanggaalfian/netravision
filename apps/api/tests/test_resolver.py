"""Test stream resolver: derive pola + strategi berlapis (tanpa network)."""

import pytest

from app.services.stream_resolver import derive_sub_url, resolve_stream


@pytest.mark.parametrize(
    "main, expected_sub",
    [
        ("rtsp://a:554/h264Preview_01_main", "rtsp://a:554/h264Preview_01_sub"),
        ("rtsp://a:554/stream1", "rtsp://a:554/stream2"),
        ("rtsp://a:554/h264/ch1", "rtsp://a:554/h264_sub/ch1"),
        ("rtsp://a:554/H.264/ch1", "rtsp://a:554/H.264_sub/ch1"),
    ],
)
def test_derive_sub_url_pola(main, expected_sub):
    assert derive_sub_url(main) == expected_sub


@pytest.mark.parametrize("url", ["", "rtsp://a:554/cam/realmonitor?channel=1"])
def test_derive_sub_url_none(url):
    assert derive_sub_url(url) is None


async def test_resolve_explicit():
    r = await resolve_stream(
        brand=None, rtsp_url="rtsp://a:554/h264Preview_01_main"
    )
    assert r.method == "explicit"
    assert r.main_url == "rtsp://a:554/h264Preview_01_main"
    assert r.sub_url == "rtsp://a:554/h264Preview_01_sub"


async def test_resolve_explicit_tanpa_pola():
    r = await resolve_stream(brand=None, rtsp_url="rtsp://a:554/live")
    assert r.method == "explicit"
    assert r.sub_url is None


async def test_resolve_brand():
    r = await resolve_stream(
        brand="hikvision", rtsp_url=None,
        user="admin", password="pw", host="192.168.1.10",
    )
    assert r.method == "brand"
    assert r.brand == "hikvision"
    assert "/Streaming/Channels/101" in r.main_url
    assert r.sub_url is not None and "/Streaming/Channels/102" in r.sub_url


async def test_resolve_generic_brand_tak_dikenal():
    r = await resolve_stream(
        brand="merek_aneh", rtsp_url="rtsp://a:554/cam_main"
    )
    assert r.method == "generic"
    assert r.sub_url == "rtsp://a:554/cam_sub"


async def test_resolve_onvif_dilewati_tanpa_lib(monkeypatch):
    # Tanpa package onvif terinstal, _try_onvif -> None -> lanjut ke brand.
    import app.services.stream_resolver as mod

    async def fake_onvif(*a, **k):
        return None

    monkeypatch.setattr(mod, "_try_onvif", fake_onvif)
    r = await resolve_stream(
        brand="dahua", rtsp_url=None,
        user="admin", password="pw", host="192.168.1.10",
    )
    assert r.method == "brand"
    assert "subtype=0" in r.main_url


async def test_resolve_input_kurang():
    with pytest.raises(ValueError, match="Tidak cukup input"):
        await resolve_stream(brand=None, rtsp_url=None)
    with pytest.raises(ValueError, match="Tidak cukup input"):
        await resolve_stream(brand="hikvision", rtsp_url=None)  # tanpa host
