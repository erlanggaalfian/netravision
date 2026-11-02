"""Registry template URL RTSP per brand kamera.

Dipakai oleh stream_resolver sebagai lapis kedua setelah ONVIF:
bila kamera tidak support ONVIF, URL main/sub diturunkan dari template brand.
"""

from __future__ import annotations

from urllib.parse import quote

# Tiap profil: {"label", "main", "sub"}. Placeholder: {user} {password} {host}
# {port} {channel}. "sub" boleh None bila brand tidak punya konsep sub stream.
BRAND_PROFILES: dict[str, dict[str, str | None]] = {
    "hikvision": {
        "label": "Hikvision",
        "main": "rtsp://{user}:{password}@{host}:{port}/Streaming/Channels/{channel}01",
        "sub": "rtsp://{user}:{password}@{host}:{port}/Streaming/Channels/{channel}02",
    },
    "dahua": {
        "label": "Dahua / Amcrest",
        "main": "rtsp://{user}:{password}@{host}:{port}/cam/realmonitor?channel={channel}&subtype=0",
        "sub": "rtsp://{user}:{password}@{host}:{port}/cam/realmonitor?channel={channel}&subtype=1",
    },
    "uniview_ipc": {
        "label": "Uniview (kamera langsung)",
        "main": "rtsp://{user}:{password}@{host}:{port}/media/video1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/media/video2",
    },
    "uniview_nvr": {
        "label": "Uniview (NVR)",
        "main": "rtsp://{user}:{password}@{host}:{port}/unicast/c{channel}/s0/live",
        "sub": "rtsp://{user}:{password}@{host}:{port}/unicast/c{channel}/s1/live",
    },
    "hanwha": {
        "label": "Hanwha / Samsung",
        "main": "rtsp://{user}:{password}@{host}:{port}/profile1/media.smp",
        "sub": "rtsp://{user}:{password}@{host}:{port}/profile2/media.smp",
    },
    "axis": {
        "label": "Axis",
        "main": "rtsp://{user}:{password}@{host}:{port}/axis-media/media.amp",
        "sub": None,
    },
    "tplink_vigi": {
        "label": "TP-Link Vigi",
        "main": "rtsp://{user}:{password}@{host}:{port}/stream1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/stream2",
    },
    "reolink": {
        "label": "Reolink",
        "main": "rtsp://{user}:{password}@{host}:{port}/h264Preview_01_main",
        "sub": "rtsp://{user}:{password}@{host}:{port}/h264Preview_01_sub",
    },
    "foscam": {
        "label": "Foscam",
        "main": "rtsp://{user}:{password}@{host}:{port}/videoMain",
        "sub": "rtsp://{user}:{password}@{host}:{port}/videoSub",
    },
    "milesight": {
        "label": "Milesight",
        "main": "rtsp://{user}:{password}@{host}:{port}/main",
        "sub": "rtsp://{user}:{password}@{host}:{port}/sub",
    },
    "panasonic": {
        "label": "Panasonic",
        "main": "rtsp://{user}:{password}@{host}:{port}/MediaInput/h264/stream_1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/MediaInput/h264/stream_2",
    },
    # Ezviz (konsumen): banyak model hanya mengekspos main stream — sub di bawah
    # ini best-effort. Password umumnya = device verification code (6 karakter
    # di stiker perangkat), dan RTSP kadang nonaktif default di firmware baru
    # (aktifkan dulu di aplikasi Ezviz / web perangkat).
    "ezviz": {
        "label": "Ezviz",
        "main": "rtsp://{user}:{password}@{host}:{port}/H.264",
        "sub": "rtsp://{user}:{password}@{host}:{port}/H.264_sub",
    },
}


def resolve_brand_urls(
    brand: str,
    user: str,
    password: str,
    host: str,
    port: int = 554,
    channel: int = 1,
) -> tuple[str, str | None]:
    """Format template brand menjadi URL main/sub konkret.

    Raises:
        ValueError: bila brand tidak dikenal.
    """
    key = brand.strip().lower()
    profile = BRAND_PROFILES.get(key)
    if profile is None:
        known = ", ".join(sorted(BRAND_PROFILES))
        raise ValueError(f"Brand '{brand}' tidak dikenal. Pilihan: {known}")

    ctx = {
        "user": user,
        "password": quote(password, safe=""),
        "host": host,
        "port": port,
        "channel": channel,
    }
    main = str(profile["main"]).format(**ctx)
    sub = str(profile["sub"]).format(**ctx) if profile["sub"] else None
    return main, sub
