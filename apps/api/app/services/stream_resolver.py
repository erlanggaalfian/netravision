"""Brand-aware stream resolver: ONVIF -> template brand -> pola generik.

Menentukan URL main/sub stream sebuah kamera dari input apa pun yang tersedia
(URL eksplisit, kredensial+host+brand, atau ONVIF). Hasilnya disimpan eksplisit
di streams.main_url/sub_url — tidak di-derive ulang setiap request.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

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


@dataclass
class ProbeResult:
    url: str
    reachable: bool       # TCP + respons RTSP valid
    status: str           # ok | auth_required | not_found | connection_failed | timeout | error
    authenticated: bool = False


def _parse_www_authenticate(header_value: str) -> dict | None:
    """Parse header WWW-Authenticate Digest -> dict param. None bila Basic/unknown."""
    if "digest" not in header_value.lower():
        return None
    params: dict[str, str] = {}
    for m in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*)"|([^\s,]+))', header_value):
        params[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
    return params if "nonce" in params else None


def _digest_auth_value(user: str, password: str, method: str, uri: str,
                       params: dict, cnonce: str = "netravision") -> str:
    realm = params.get("realm", "")
    nonce = params["nonce"]
    qop = params.get("qop", "")
    ha1 = hashlib.md5(f"{user}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    if "auth" in qop:
        nc = "00000001"
        resp = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}".encode()).hexdigest()
        return (f'Digest username="{user}", realm="{realm}", nonce="{nonce}", '
                f'uri="{uri}", qop=auth, nc={nc}, cnonce="{cnonce}", response="{resp}"')
    resp = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    return (f'Digest username="{user}", realm="{realm}", nonce="{nonce}", '
            f'uri="{uri}", response="{resp}"')


async def _rtsp_describe(reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter,
                         url: str, auth: str | None,
                         timeout: float) -> str:
    cseq = 2
    req = (f"DESCRIBE {url} RTSP/1.0\r\nCSeq: {cseq}\r\n"
           f"Accept: application/sdp\r\n")
    if auth:
        req += f"Authorization: {auth}\r\n"
    req += "User-Agent: NetraVision/3.0\r\n\r\n"
    writer.write(req.encode())
    await writer.drain()
    try:
        data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
    except asyncio.LimitOverrunError as e:
        data = await reader.read(e.consumed)
    return data.decode("utf-8", errors="replace")


async def probe_rtsp(url: str, timeout: float = 6.0) -> ProbeResult:
    """Tes koneksi RTSP via DESCRIBE (tanpa ffmpeg).

    Mengembalikan apakah URL dapat dijangkau dan apakah kredensial valid.
    401 = server ada & path valid tapi butuh auth; 404 = path tidak ada.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return ProbeResult(url=url, reachable=False, status="invalid_url")
    port = parsed.port or 554
    user = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    path = parsed.path or "/"
    clean = f"rtsp://{host}:{port}{path}"
    if parsed.query:
        clean += f"?{parsed.query}"

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
    except asyncio.TimeoutError:
        return ProbeResult(url=url, reachable=False, status="timeout")
    except OSError:
        return ProbeResult(url=url, reachable=False, status="connection_failed")

    try:
        resp = await _rtsp_describe(reader, writer, clean, None, timeout)
        if resp.startswith("RTSP/1.0 200"):
            return ProbeResult(url=url, reachable=True, status="ok",
                               authenticated=True)
        if resp.startswith("RTSP/1.0 404"):
            return ProbeResult(url=url, reachable=True, status="not_found")
        if resp.startswith("RTSP/1.0 401") and user and password:
            # Coba auth: Basic dulu, lalu Digest bila ditantang.
            basic = "Basic " + base64.b64encode(
                f"{user}:{password}".encode()).decode()
            resp2 = await _rtsp_describe(reader, writer, clean, basic, timeout)
            if resp2.startswith("RTSP/1.0 200"):
                return ProbeResult(url=url, reachable=True, status="ok",
                                   authenticated=True)
            m = re.search(r"WWW-Authenticate:\s*(.+)",
                          resp if not resp2.startswith("RTSP/1.0 401") else resp2,
                          re.IGNORECASE)
            if m:
                params = _parse_www_authenticate(m.group(1))
                if params:
                    digest = _digest_auth_value(user, password, "DESCRIBE",
                                                clean, params)
                    resp3 = await _rtsp_describe(reader, writer, clean,
                                                 digest, timeout)
                    if resp3.startswith("RTSP/1.0 200"):
                        return ProbeResult(url=url, reachable=True,
                                           status="ok", authenticated=True)
                    if resp3.startswith("RTSP/1.0 401"):
                        return ProbeResult(url=url, reachable=True,
                                           status="auth_failed")
            return ProbeResult(url=url, reachable=True,
                               status="auth_required")
        if resp.startswith("RTSP/1.0 401"):
            return ProbeResult(url=url, reachable=True,
                               status="auth_required")
        first_line = resp.split("\r\n", 1)[0][:40]
        return ProbeResult(url=url, reachable=True,
                           status=f"unexpected:{first_line}")
    except (asyncio.TimeoutError, OSError):
        return ProbeResult(url=url, reachable=False, status="timeout")
    except Exception:  # noqa: BLE001
        return ProbeResult(url=url, reachable=False, status="error")
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass
