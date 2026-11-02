"""Brand-aware stream resolver: ONVIF -> template brand -> pola generik.

Menentukan URL main/sub stream sebuah kamera dari input apa pun yang tersedia
(URL eksplisit, kredensial+host+brand, atau ONVIF). Hasilnya disimpan eksplisit
di streams.main_url/sub_url — tidak di-derive ulang setiap request.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.services.brands import resolve_brand_urls

# Pola generik v2.0 (get_substream_url): (penanda_main, penanda_sub).
_GENERIC_PATTERNS: tuple[tuple[str, str], ...] = (
    ("_main", "_sub"),
    ("/stream1", "/stream2"),
    ("/h264", "/h264_sub"),
    ("/h.264", "/H.264_sub"),
)


def derive_sub_url(rtsp_url: str) -> str | None:
    """Turunkan URL sub stream dari URL main via pola generik.

    Returns None bila tidak ada pola yang cocok (v2.0 mengembalikan URL asli;
    di sini None agar pemanggil tahu tidak ada sub stream yang valid).
    """
    if not rtsp_url:
        return None
    lowered = rtsp_url.lower()
    for main_mark, sub_mark in _GENERIC_PATTERNS:
        idx = lowered.find(main_mark)
        if idx != -1:
            return rtsp_url[:idx] + sub_mark + rtsp_url[idx + len(main_mark):]
    return None


@dataclass
class StreamResolution:
    main_url: str
    sub_url: str | None
    brand: str
    method: str  # "explicit" | "onvif" | "brand" | "generic"


async def _try_onvif(
    host: str, port: int, user: str, password: str
) -> tuple[str, str | None, str | None] | None:
    """Best-effort: ambil stream URI langsung dari kamera via ONVIF.

    Returns (main_url, sub_url, profile_token) atau None bila gagal / lib tidak ada.

    TODO: perlu dependensi `onvif_zeep_async` (atau `python-onvif-zeep`) di
    pyproject; saat ini dibungkus try/except agar tidak crash tanpanya.
    TODO: WS-Discovery untuk auto-deteksi kamera di jaringan (Fase 2+).
    """
    try:
        from onvif import ONVIFCamera  # type: ignore[import-not-found]
    except ImportError:
        return None

    def _blocking() -> tuple[str, str | None, str | None] | None:
        try:
            cam = ONVIFCamera(host, port, user, password)
            media = cam.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                return None
            uris: list[str] = []
            token = None
            for profile in profiles[:2]:  # main + sub cukup
                req = media.create_type("GetStreamUri")
                req.ProfileToken = profile.token
                uri = media.GetStreamUri(req)["Uri"]
                uris.append(uri)
                if token is None:
                    token = profile.token
            main = uris[0] if uris else None
            sub = uris[1] if len(uris) > 1 else None
            return (main, sub, token) if main else None
        except Exception:
            return None

    return await asyncio.to_thread(_blocking)


async def resolve_stream(
    *,
    brand: str | None,
    rtsp_url: str | None,
    user: str | None = None,
    password: str | None = None,
    host: str | None = None,
    port: int = 554,
    channel: int = 1,
) -> StreamResolution:
    """Tentukan main/sub URL dengan strategi berlapis.

    Urutan: (a) URL eksplisit -> sub via pola generik; (b) ONVIF bila ada
    host+user+password; (c) template brand; (d) pola generik dari rtsp_url.

    Raises:
        ValueError: bila input tidak cukup untuk menentukan stream.
    """
    brand_key = (brand or "").strip().lower() or "generic"

    # (a) URL eksplisit tanpa brand: user menempel URL langsung.
    if rtsp_url and not brand:
        return StreamResolution(
            main_url=rtsp_url,
            sub_url=derive_sub_url(rtsp_url),
            brand=brand_key,
            method="explicit",
        )

    # (b) ONVIF: tanya langsung ke kameranya.
    if host and user and password:
        onvif = await _try_onvif(host, port, user, password)
        if onvif:
            main, sub, token = onvif
            return StreamResolution(
                main_url=main, sub_url=sub, brand=brand_key, method="onvif"
            )
        # TODO: simpan token profil ke streams.onvif_profile saat dipakai.

    # (c) Template brand (butuh host untuk format URL).
    if brand and host:
        try:
            main, sub = resolve_brand_urls(
                brand, user or "", password or "", host, port, channel
            )
            return StreamResolution(
                main_url=main, sub_url=sub, brand=brand_key, method="brand"
            )
        except ValueError:
            pass  # brand tak dikenal -> (d)

    # (d) Pola generik: brand tak dikenal tapi URL tersedia.
    if rtsp_url:
        return StreamResolution(
            main_url=rtsp_url,
            sub_url=derive_sub_url(rtsp_url),
            brand=brand_key,
            method="generic",
        )

    raise ValueError(
        "Tidak cukup input: berikan rtsp_url, atau host+user+password, "
        "atau brand yang dikenal beserta host."
    )
