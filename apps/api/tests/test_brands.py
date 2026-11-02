"""Test registry template URL brand (murni, tanpa network)."""

import pytest

from app.services.brands import BRAND_PROFILES, resolve_brand_urls


@pytest.mark.parametrize(
    "brand, main_mark, sub_mark",
    [
        ("hikvision", "/Streaming/Channels/101", "/Streaming/Channels/102"),
        ("dahua", "subtype=0", "subtype=1"),
        ("uniview_ipc", "/media/video1", "/media/video2"),
        ("uniview_nvr", "/unicast/c1/s0/live", "/unicast/c1/s1/live"),
        ("hanwha", "/profile1/media.smp", "/profile2/media.smp"),
        ("tplink_vigi", "/stream1", "/stream2"),
        ("reolink", "/h264Preview_01_main", "/h264Preview_01_sub"),
        ("foscam", "/videoMain", "/videoSub"),
        ("milesight", "/main", "/sub"),
        ("panasonic", "/MediaInput/h264/stream_1", "/MediaInput/h264/stream_2"),
        ("ezviz", "/H.264", "/H.264_sub"),
    ],
)
def test_brand_main_sub(brand, main_mark, sub_mark):
    main, sub = resolve_brand_urls(brand, "admin", "p@ss", "192.168.1.10")
    assert main_mark in main
    assert sub is not None and sub_mark in sub
    assert "p%40ss" in main  # password di-quote


def test_axis_sub_none():
    main, sub = resolve_brand_urls("axis", "root", "pass", "192.168.1.11")
    assert "/axis-media/media.amp" in main
    assert sub is None


def test_brand_case_insensitive():
    main, _ = resolve_brand_urls("HikVision", "a", "b", "h")
    assert "/Streaming/Channels/101" in main


def test_unknown_brand_raises():
    with pytest.raises(ValueError, match="tidak dikenal"):
        resolve_brand_urls("merek_aneh", "a", "b", "h")


def test_channel_dan_port_dipakai():
    main, sub = resolve_brand_urls(
        "dahua", "a", "b", "h", port=8554, channel=3
    )
    assert ":8554/cam/realmonitor?channel=3&subtype=0" in main
    assert "subtype=1" in sub


def test_semua_profil_punya_label():
    for key, profile in BRAND_PROFILES.items():
        assert profile["label"], key
        assert "{host}" in str(profile["main"]), key
