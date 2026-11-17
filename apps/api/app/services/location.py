"""Penyelesaian lokasi multi-format menjadi koordinat.

Satu tempat untuk mengurai semua format lokasi yang bisa ditempel user
di kolom "Lokasi" (Scanner, Tambah/Ubah Kamera, Set Koordinat):
koordinat desimal, URL Google Maps (lengkap dan pendek), Plus Code,
DMS, dan alamat teks bebas (geocoding Nominatim, gratis, tanpa key).

Tidak ada layanan berbayar dan tidak ada API key di sini.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import math
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

log = logging.getLogger("netravision.location")

SUPPORTED_FORMATS = (
    "koordinat desimal (cth. -7.873522, 111.257658), "
    "tautan Google Maps (maps.app.goo.gl atau google.com/maps), "
    "Plus Code (cth. 6P2Q4R5C+6X7), "
    "DMS (cth. 7°52'24.7\"S 111°15'27.6\"E), "
    "atau alamat (cth. Jl. Merdeka, Ponorogo)"
)


class LocationError(ValueError):
    """Input lokasi tidak bisa diurai menjadi koordinat."""


@dataclass
class ResolvedLocation:
    latitude: float
    longitude: float
    format: str
    place_name: str | None = None


def _check_range(lat: float, lng: float) -> tuple[float, float]:
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise LocationError(
            "Koordinat di luar rentang (latitude -90..90, longitude -180..180)."
        )
    return lat, lng


# ---------------------------------------------------------------------------
# Koordinat desimal: "-7.873522, 111.257658" atau "-7.873522 111.257658".
# Bila nilai pertama di luar -90..90 tapi cocok sebagai longitude dan
# nilai kedua cocok sebagai latitude, anggap urutan lng,lat dan tukar.
# ---------------------------------------------------------------------------
_DECIMAL_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$"
)


def parse_decimal(text: str) -> tuple[float, float] | None:
    m = _DECIMAL_RE.match(text.strip())
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if -90 <= a <= 90 and -180 <= b <= 180:
        return _check_range(a, b)
    if -180 <= a <= 180 and -90 <= b <= 90:
        return _check_range(b, a)
    return None


# ---------------------------------------------------------------------------
# URL Google Maps lengkap. Pola yang dicari, berurutan:
#   /@lat,lng   ?q=lat,lng   ?ll=lat,lng   !3dlat!4dlng (parameter data)
#   /search/lat,lng (hasil redirect tautan pendek)
# ---------------------------------------------------------------------------
_MAPS_AT_RE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
_MAPS_Q_RE = re.compile(r"[?&](?:q|ll|destination)=(-?\d+\.\d+),(-?\d+\.\d+)")
_MAPS_DATA_RE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
_MAPS_SEARCH_RE = re.compile(r"/search/(-?\d+\.\d+),\+?(-?\d+\.\d+)")


def parse_google_maps_url(text: str) -> tuple[float, float] | None:
    t = text.strip()
    if "google.com/maps" not in t and "maps.google" not in t and "goo.gl" not in t:
        return None
    for rx in (_MAPS_AT_RE, _MAPS_Q_RE, _MAPS_DATA_RE, _MAPS_SEARCH_RE):
        m = rx.search(t)
        if m:
            try:
                return _check_range(float(m.group(1)), float(m.group(2)))
            except LocationError:
                return None
    return None


# ---------------------------------------------------------------------------
# Plus Code (Open Location Code), decode mandiri tanpa dependensi baru.
# Kode lengkap (10+ karakter) tidak butuh acuan; kode pendek (2/4/6
# karakter sebelum "+") butuh lokasi acuan untuk memulihkan digit awal
# yang dihilangkan. Pusat area kode yang dikembalikan.
# ---------------------------------------------------------------------------
_OLC_ALPHABET = "23456789CFGHJMPQRVWX"
_OLC_INDEX = {c: i for i, c in enumerate(_OLC_ALPHABET)}
_OLC_SEP = "+"
_OLC_PAD = "0"


def _decode_plus_code_full(code: str) -> tuple[float, float] | None:
    """Decode Plus Code lengkap (tanpa padding, sudah tanpa '+').

    Karakter "0" adalah padding digit awal yang dihilangkan pada kode
    pendek, nilainya 0.
    """
    digits = code.replace(_OLC_SEP, "")
    if len(digits) < 10 or any(c not in _OLC_INDEX and c != _OLC_PAD for c in digits):
        return None
    lat = -90.0
    lng = -180.0
    lat_res = 20.0
    lng_res = 20.0
    for i in range(0, 10, 2):
        lat += _OLC_INDEX.get(digits[i], 0) * lat_res
        lng += _OLC_INDEX.get(digits[i + 1], 0) * lng_res
        lat_res /= 20.0
        lng_res /= 20.0
    # Penyempurnaan grid (karakter ke-11 dst): tiap karakter membagi
    # area jadi 4 kolom x 5 baris.
    for c in digits[10:]:
        v = _OLC_INDEX.get(c, 0)
        row, col = divmod(v, 4)
        lat += row * (lat_res / 5.0)
        lng += col * (lng_res / 4.0)
        lat_res /= 5.0
        lng_res /= 4.0
    return lat + lat_res / 2.0, lng + lng_res / 2.0


def parse_plus_code(
    text: str, ref_lat: float | None = None, ref_lng: float | None = None
) -> tuple[float, float] | None:
    t = text.strip().upper().replace(" ", "")
    if not t or _OLC_SEP not in t:
        return None
    head, _, tail = t.partition(_OLC_SEP)
    if any(c not in _OLC_ALPHABET + _OLC_PAD for c in head + tail):
        return None
    if len(head) > 8 or len(tail) > 7:
        return None
    # Kode pendek: digit awal dihilangkan, diganti padding "0".
    if len(head) < 8:
        if len(head) not in (2, 4, 6):
            return None
        if ref_lat is None or ref_lng is None:
            raise LocationError(
                "Plus Code pendek butuh lokasi acuan: tempel Plus Code "
                "lengkap (10 karakter atau lebih) atau tautan Google Maps."
            )
        # Pulihkan digit awal dari acuan: bagian tinggi adalah kelipatan
        # place value pasangan terakhir yang hilang, terdekat dengan acuan.
        missing_pairs = (8 - len(head)) // 2
        place = 20.0 / (20.0 ** (missing_pairs - 1))
        padded = _OLC_PAD * (8 - len(head)) + head + tail
        low = _decode_plus_code_full(padded)
        if low is None:
            return None
        lat_low, lng_low = low
        # low dihitung dari -90/-180 dengan digit awal nol; ganti bagian
        # tingginya dengan nilai dari acuan.
        def _recover(value: float, ref: float, base: float) -> float:
            offset = value - base
            ref_off = ref - base
            high = math.floor(ref_off / place) * place
            total = high + offset
            if total - ref_off > place / 2:
                total -= place
            elif total - ref_off < -place / 2:
                total += place
            return base + total

        return _check_range(
            _recover(lat_low, ref_lat, -90.0),
            _recover(lng_low, ref_lng, -180.0),
        )
    full = _decode_plus_code_full(head + tail)
    if full is None:
        return None
    return _check_range(*full)


# ---------------------------------------------------------------------------
# DMS: 7°52'24.7"S 111°15'27.6"E (juga terima spasi, menit desimal,
# dan tanda minus sebagai pengganti huruf hemisphere).
# ---------------------------------------------------------------------------
_DMS_PART_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[°d]?\s*"
    r"(?:(\d+(?:\.\d+)?)\s*['’m]?\s*)?"
    r"(?:(\d+(?:\.\d+)?)\s*[\"”s]?\s*)?"
    r"([NSEWnsew])?"
)


def parse_dms(text: str) -> tuple[float, float] | None:
    parts = list(_DMS_PART_RE.finditer(text.strip()))
    if len(parts) != 2:
        return None
    # Tanpa menit/detik/huruf hemisphere sama sekali, ini bukan DMS
    # (dua angka polos sudah ditangani parse_decimal; alamat seperti
    # "Merdeka 1 2" tidak boleh salah jadi koordinat).
    if not any(m.group(2) or m.group(3) or m.group(4) for m in parts):
        return None
    vals: list[float] = []
    for m in parts:
        deg = float(m.group(1))
        minutes = float(m.group(2)) if m.group(2) else 0.0
        seconds = float(m.group(3)) if m.group(3) else 0.0
        hemi = (m.group(4) or "").upper()
        v = abs(deg) + minutes / 60.0 + seconds / 3600.0
        if hemi in ("S", "W") or deg < 0:
            v = -v
        vals.append(v)
    lat, lng = vals
    # Bila tidak ada huruf hemisphere, tentukan dari rentang seperti desimal.
    if not any(m.group(4) for m in parts):
        if not (-90 <= lat <= 90) and -90 <= lng <= 90:
            lat, lng = lng, lat
    try:
        return _check_range(lat, lng)
    except LocationError:
        return None


# ---------------------------------------------------------------------------
# Tautan pendek (maps.app.goo.gl / goo.gl/maps): ikuti redirect sampai
# dapat URL Google Maps yang membawa koordinat. Bila URL akhir tetap
# tanpa koordinat, pindai HTML-nya untuk pola koordinat.
# ---------------------------------------------------------------------------
_SHORT_HOSTS = ("maps.app.goo.gl", "goo.gl")

# Host yang boleh dituju saat mengikuti redirect tautan pendek.
# T-3 (SSRF): redirect tidak boleh ke host sembarang; hanya host Google.
_REDIRECT_HOSTS = ("maps.app.goo.gl", "goo.gl", "google.com", "googleapis.com")


def _host_allowed(host: str) -> bool:
    """Host boleh dituju bila sama dengan atau subdomain host Google."""
    h = (host or "").lower().rstrip(".")
    return any(h == base or h.endswith("." + base) for base in _REDIRECT_HOSTS)


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    """True bila IP boleh dihubungi dari server (bukan privat dkk)."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _ip_is_public(host: str) -> bool:
    """Tolak host yang resolve ke IP private/loopback/link-local/reserved."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not _is_public_ip(ip):
            return False
    return True


def _resolve_public_ip(host: str) -> str | None:
    """Satu alamat IP publik untuk host, atau None.

    Temuan 3.18: melakukan SATU getaddrinfo, memvalidasi hasilnya
    sendiri, lalu mengembalikan IP publik pertama (IPv4 diutamakan,
    karena pin IPv4 paling sederhana di URL). IP yang dikembalikan
    inilah yang dipakai koneksi (lihat _PinnedIPTransport), jadi IP
    yang dipakai selalu IP yang divalidasi dalam panggilan ini.
    Gate _ip_is_public dipanggil dulu supaya host yang jawabannya
    bercampur IP privat ditolak seluruhnya, sama seperti sebelum
    pinning ada.
    """
    if not _ip_is_public(host):
        return None
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return None
    if not infos:
        return None
    v6: str | None = None
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not _is_public_ip(ip):
            continue
        if isinstance(ip, ipaddress.IPv4Address):
            return str(ip)
        if v6 is None:
            v6 = str(ip)
    return v6


class _PinnedIPTransport(httpx.AsyncHTTPTransport):
    """Transport httpx yang konek ke IP yang sudah divalidasi.

    Temuan 3.18 (TOCTOU DNS): host boleh resolve ke IP berbeda antara
    cek dan koneksi. Transport ini menulis ulang host URL menjadi IP
    pin (satu-satunya alamat yang dipakai TCP), sambil menjaga Host
    header dan SNI TLS tetap nama host asli, jadi verifikasi sertifikat
    tetap terhadap nama host, bukan terhadap IP. httpcore memakai
    ekstensi `sni_hostname` untuk SNI dan verifikasi sertifikat, dan
    httpx meneruskan request.extensions ke httpcore.
    """

    def __init__(self, pinned: dict[str, str], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pinned = {k.lower(): v for k, v in pinned.items()}

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        host = (request.url.host or "").lower()
        ip = self._pinned.get(host)
        if ip is not None:
            request.url = request.url.copy_with(host=ip)
            request.headers["host"] = host
            request.extensions["sni_hostname"] = host
        return await super().handle_async_request(request)


# Batas body HTML yang dibaca saat mengikuti tautan pendek (temuan 3.18).
_MAX_HTML_BYTES = 512 * 1024


async def resolve_short_url(url: str) -> tuple[float, float] | None:
    t = url.strip()
    # Host awal harus persis tautan pendek Google (bukan substring di
    # path/query, yang sebelumnya bisa memicu fetch ke host sembarang).
    parsed = urlparse(t)
    if parsed.scheme not in ("http", "https"):
        return None
    if not _host_allowed(parsed.hostname or ""):
        return None
    try:
        current = t
        resp = None
        body = b""
        for _ in range(10):
            host = urlparse(current).hostname or ""
            # Tiap hop redirect divalidasi: host Google saja dan
            # IP-nya publik, supaya server tidak dipakai sebagai
            # proxy ke service internal (SSRF).
            if not _host_allowed(host):
                return None
            if not await asyncio.to_thread(_ip_is_public, host):
                return None
            # Temuan 3.18 (pinning DNS penuh): resolve host sekali,
            # validasi IP publik, lalu konek ke IP yang sudah
            # divalidasi itu lewat _PinnedIPTransport. Tanpa pin,
            # httpx me-resolve ulang host saat fetch dan DNS yang
            # berubah di antara cek dan koneksi bisa mengarah ke IP
            # privat. Bila pin tidak bisa dibuat (resolver gagal
            # atau jawaban DNS berubah di antara dua lookup),
            # lanjut tanpa pin tapi tetap lewat gate _ip_is_public
            # di atas dan host tetap dibatasi ke Google; di
            # produksi dengan DNS normal jalur pin selalu terpakai.
            pinned_ip = await asyncio.to_thread(_resolve_public_ip, host)
            transport = (
                _PinnedIPTransport({host: pinned_ip})
                if pinned_ip is not None
                else None
            )
            if transport is None:
                log.warning(
                    "pin DNS gagal untuk %s, lanjut tanpa pin", host
                )
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=10.0,
                headers={"User-Agent": "NetraVision/1.0"},
                transport=transport,
            ) as client:
                # Temuan 3.18: baca respons secara streaming dengan
                # batas byte (dulu `resp.text` tanpa batas, halaman
                # besar membebani memori). Redirect tidak membaca body.
                async with client.stream("GET", current) as r:
                    resp = r
                    if r.status_code in (301, 302, 303, 307, 308):
                        nxt = r.headers.get("location")
                        if not nxt:
                            return None
                        current = str(httpx.URL(current).join(nxt))
                        continue
                    length = r.headers.get("content-length")
                    if length is not None:
                        try:
                            if int(length) > _MAX_HTML_BYTES:
                                body = b""
                                break
                        except ValueError:
                            pass
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in r.aiter_bytes(65536):
                        total += len(chunk)
                        if total > _MAX_HTML_BYTES:
                            break
                        chunks.append(chunk)
                    body = b"".join(chunks)
            break
        else:
            return None
        if resp is None:
            return None
    except (httpx.HTTPError, ValueError):
        log.warning("gagal mengikuti tautan pendek %s", t[:80])
        return None
    # URL akhir dari respons (mock/redirect chain); bila tidak ada, pakai
    # URL terakhir yang diminta.
    final = str(getattr(resp, "url", "") or current)
    got = parse_google_maps_url(final)
    if got:
        return got
    # Temuan 3.18 (TOCTOU DNS): hop terakhir sudah di-fetch lewat IP
    # yang di-pin dan divalidasi, jadi host/IP tujuan akhir cukup
    # divalidasi ulang sebagai pertahanan lapis kedua.
    final_host = urlparse(final).hostname or ""
    if final_host:
        if not _host_allowed(final_host):
            return None
        if not await asyncio.to_thread(_ip_is_public, final_host):
            return None
    # Fallback: pindai HTML halaman tujuan untuk koordinat (hanya prefix
    # yang dibaca, maksimal _MAX_HTML_BYTES).
    text = body.decode("utf-8", "replace")
    for rx in (_MAPS_AT_RE, _MAPS_DATA_RE, _MAPS_SEARCH_RE):
        m = rx.search(text)
        if m:
            try:
                return _check_range(float(m.group(1)), float(m.group(2)))
            except LocationError:
                return None
    return None


# ---------------------------------------------------------------------------
# Geocoding alamat via Nominatim (OpenStreetMap), gratis tanpa key.
# Kebijakan pemakaian: maks 1 request/detik, User-Agent wajib diisi.
# ---------------------------------------------------------------------------
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_nominatim_lock = asyncio.Lock()
_last_nominatim_call = 0.0
# 6.15: cache hasil geocoding per teks alamat (TTL 24 jam, maks 512
# entri, LRU). Alamat yang sama (nama gedung yang dipakai banyak
# kamera) sebelumnya di-geocode ulang tiap kali, padahal hasilnya
# deterministik dan Nominatim membatasi 1 req/dtk.
_GEOCODE_CACHE: dict[str, tuple[float, ResolvedLocation]] = {}
_GEOCODE_TTL_SEC = 86400.0
_GEOCODE_MAX_ENTRIES = 512


def clear_geocode_cache() -> None:
    """Buang cache geocoding (dipakai tes)."""
    _GEOCODE_CACHE.clear()


async def geocode_address(text: str) -> ResolvedLocation | None:
    global _last_nominatim_call
    q = text.strip()
    if len(q) < 3:
        return None
    # 6.15: jawab dari cache bila masih segar (tanpa lock/rate-limit).
    _now = time.monotonic()
    _hit = _GEOCODE_CACHE.get(q.lower())
    if _hit is not None and _now - _hit[0] < _GEOCODE_TTL_SEC:
        return _hit[1]
    async with _nominatim_lock:
        wait = 1.1 - (time.monotonic() - _last_nominatim_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    _NOMINATIM_URL,
                    params={"q": q, "format": "jsonv2", "limit": 1},
                    headers={"User-Agent": "NetraVision/1.0 (cctv-monitoring)"},
                )
            _last_nominatim_call = time.monotonic()
        except httpx.HTTPError:
            log.warning("geocoding gagal (jaringan) untuk %r", q[:80])
            return None
    if resp.status_code != 200:
        return None
    try:
        rows = resp.json()
    except ValueError:
        return None
    if not rows:
        return None
    row = rows[0]
    try:
        lat, lng = _check_range(float(row["lat"]), float(row["lon"]))
    except (KeyError, TypeError, ValueError, LocationError):
        return None
    found = ResolvedLocation(
        latitude=lat, longitude=lng, format="Alamat",
        place_name=row.get("display_name"),
    )
    # 6.15: simpan ke cache (LRU sederhana: buang entri terlama).
    _GEOCODE_CACHE[q.lower()] = (time.monotonic(), found)
    while len(_GEOCODE_CACHE) > _GEOCODE_MAX_ENTRIES:
        _GEOCODE_CACHE.pop(next(iter(_GEOCODE_CACHE)))
    return found


# ---------------------------------------------------------------------------
# Orkestrator: coba format lokal dulu (tanpa jaringan), lalu tautan
# pendek, lalu geocoding alamat sebagai usaha terakhir.
# ---------------------------------------------------------------------------
async def resolve_location(
    text: str, ref_lat: float | None = None, ref_lng: float | None = None
) -> ResolvedLocation:
    t = (text or "").strip()
    if not t:
        raise LocationError("Lokasi masih kosong.")
    got = parse_decimal(t)
    if got:
        return ResolvedLocation(*got, format="Koordinat desimal")
    got = parse_google_maps_url(t)
    if got:
        return ResolvedLocation(*got, format="Tautan Google Maps")
    if any(h in t for h in _SHORT_HOSTS):
        got = await resolve_short_url(t)
        if got:
            return ResolvedLocation(*got, format="Tautan Google Maps")
        raise LocationError(
            "Tautan pendek tidak bisa diikuti atau tidak membawa koordinat. "
            "Coba buka tautan itu di Google Maps lalu salin koordinatnya."
        )
    if _OLC_SEP in t:
        got = parse_plus_code(t, ref_lat, ref_lng)
        if got:
            return ResolvedLocation(*got, format="Plus Code")
    got = parse_dms(t)
    if got:
        return ResolvedLocation(*got, format="DMS")
    # Usaha terakhir: alamat teks bebas.
    found = await geocode_address(t)
    if found:
        return found
    raise LocationError(
        "Lokasi tidak dikenali. Format yang didukung: " + SUPPORTED_FORMATS + "."
    )
