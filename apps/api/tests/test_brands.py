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
        ("ezviz", "/h264/ch01/main/av_stream", "/h264/ch01/sub/av_stream"),
        # Profil baru dari riset 2026-11-13 (report.md).
        ("bosch", "inst=1", "inst=2"),
        ("avigilon", "/defaultPrimary", "/defaultSecondary"),
        ("vivotek", "/live.sdp", "/live2.sdp"),
        ("pelco", "/h264", "/h264_2"),
        ("arecont", "/h264.sdp", None),
        ("geovision", "/CH001.sdp", None),
        ("provision_isr", "/profile1", "/profile2"),
        ("tvt", "streamType=main", "streamType=sub"),
        ("hiseeu", "/ch0_0.264", "/ch0_1.264"),
        ("zosi", "/onvif1", "/onvif2"),
        ("swann", "/ch01/0", "/ch01/1"),
        ("huawei", "/LiveMedia/ch1/Media1", "/LiveMedia/ch1/Media2"),
        ("dlink", "/play1.sdp", "/live1.sdp"),
        ("digital_watchdog", "/Streaming/Channels/1", None),
        ("zmodo", "/tcp/av0_0", "/tcp/av0_1"),
        ("kedacom", "streamid=main", "streamid=sub"),
        ("infinova", "/1/h264major", "/1/h264minor"),
        ("raysharp", "/stream0", "/stream1"),
        ("canon", "/stream/profile1=u", "/stream/profile1=r"),
        ("lg", "/Master-0", "/Slave-0"),
        ("jvs", "/live0.264", "/live1.264"),
        ("xiaomi", "/ch0_0.h264", "/ch0_1.h264"),
        ("eufy", "/live0", "/live1"),
    ],
)
def test_brand_main_sub(brand, main_mark, sub_mark):
    main, sub = resolve_brand_urls(brand, "admin", "p@ss", "192.168.1.10")
    assert main_mark in main
    if sub_mark is None:
        assert sub is None
    else:
        assert sub is not None and sub_mark in sub
    assert "p%40ss" in main  # password di-quote


def test_axis_sub_lowres():
    """Axis: tidak ada path sub distinct; sub memakai bentuk
    ?camera=..&resolution=640x360 (riset 2026-11-13)."""
    main, sub = resolve_brand_urls("axis", "root", "pass", "192.168.1.11")
    assert "/axis-media/media.amp?camera=1" in main
    assert sub is not None
    assert "resolution=640x360" in sub


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
