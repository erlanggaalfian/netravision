"""Router embed pihak ketiga (MIGRATION-MAP §8, KONTRAK FROZEN).

Tidak memakai login user; auth via API key di HEADER.
2026-11-18 (BREAKING CHANGE): kunci + password TIDAK LAGI diterima
lewat query string (?key= / ?password= / ?pass=), kredensial di URL
tercatat di access log Apache, history browser, dan header Referer.
Kirim lewat header `X-Api-Key` (dan `X-Api-Key-Password` bila kunci
berpassword), atau `Authorization: Bearer <kunci>`. Query string
berkredensial ditolak 400. GET /external/playback/file HANYA menerima
?session= (token sesi file); fallback legacy ?key=&pass= DIHAPUS.
Bentuk response mengikuti packages/contracts/openapi.yaml; field v2.0
ditambahkan SECARA ADITIF (tidak menghapus field v3.0 yang ada):
  - GET /api/external/cameras  -> [{id, name}] (+is_online aditif; ?camera= opsional)
  - GET /api/external/stream   -> {url, expires_at} (+stream {...}, +ad {...})
  - GET /api/external/playback -> v2.0: tanpa ?date=/?time= daftar tanggal;
                                  ?date=YYYY-MM-DD -> segmen + URL putar;
                                  ?time=ISO -> satu {url, expires_at}
  - GET /api/external/playback/file -> berkas segmen (auth via ?session=)
Kegagalan -> 403 (perilaku v2.0), tanpa membocorkan informasi.
"""

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import client_ip as _trusted_client_ip, rate_limited
from app.core.security import decode_token, verify_password
from app.db.session import get_db
from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream
from app.models.misc import AdConfig
from app.models.streams import Stream
from app.routers.admin_ads import AdConfigIn

router = APIRouter()

log = logging.getLogger("netravision.external")

_DEFAULT_TTL_MNT = 60

# Kunci per (API key, IP) terhadap brute force password (T-1): 5 password
# salah dalam 15 menit -> 429 sampai jendela habis. Rate limit per IP
# saja tidak cukup karena penyerang bisa dari banyak IP; kunci per
# key menutupnya. Sukses membersihkan hitungan.
# 4.9: kunci per key saja bisa dipakai untuk DoS mitra (penyerang yang
# tahu kunci embed, kunci itu tampil di halaman mitra, mematikan
# playback mitra dengan 5 password salah). Dengan kunci gabungan
# (key, IP), kegagalan dari satu IP hanya mengunci kombinasi itu;
# mitra dari IP lain tetap bisa masuk.
_KEY_FAILURES: dict[tuple[int, str], list[float]] = {}
_KEY_LOCKOUT_MAX = 5
_KEY_LOCKOUT_WINDOW_SEC = 900.0


def _key_locked(key_id: int, ip: str) -> bool:
    now = time.monotonic()
    hits = [t for t in _KEY_FAILURES.get((key_id, ip), []) if t > now - _KEY_LOCKOUT_WINDOW_SEC]
    _KEY_FAILURES[(key_id, ip)] = hits
    return len(hits) >= _KEY_LOCKOUT_MAX


def _record_key_failure(key_id: int, ip: str) -> None:
    _KEY_FAILURES.setdefault((key_id, ip), []).append(time.monotonic())

# Default konfigurasi iklan; disamakan dengan AdConfigIn saat ini (v3.0),
# digabung dengan yang tersimpan. A-1.18: sebelumnya hanya 16 field v2.0
# di sini sehingga config embed kehilangan field v3.0 (position,
# banner_height, display_mode, periodic_trigger, audience, click_url,
# dll.) dan perilaku iklan embed vs web bisa berbeda.
_AD_DEFAULTS = AdConfigIn().model_dump()


# ── util ──────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _api_key_credentials(request: Request) -> tuple[str | None, str | None]:
    """Kunci + password embed dari header (didahulukan, satu-satunya
    jalur yang sah sejak 2026-11-18).

    Key: header `X-Api-Key`, atau `Authorization: Bearer <kunci>`.
    Password: header `X-Api-Key-Password`.
    Return (key, password); (None, None) bila tidak ada header.
    Query string TIDAK PERNAH dibaca di sini.
    """
    key = request.headers.get("x-api-key", "").strip() or None
    if not key:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip() or None
    password = request.headers.get("x-api-key-password", "").strip() or None
    return key, password


def _reject_query_credentials(request: Request) -> None:
    """Tolak kredensial lewat query string dengan 400 yang jelas.

    2026-11-18 (BREAKING CHANGE): ?key= / ?password= / ?pass= tidak
    lagi diterima di endpoint embed mana pun. Parameter query lain
    (camera, stream_id, date, time, session, start, end) tidak
    terpengaruh.
    """
    qp = request.query_params
    if (
        qp.get("key") is not None
        or qp.get("password") is not None
        or qp.get("pass") is not None
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Kunci API tidak boleh dikirim lewat query string (?key=). "
            "Kirim lewat header X-Api-Key "
            "(dan X-Api-Key-Password bila ada password).",
        )


def _client_ip(request: Request) -> str:
    # A-R5: hanya percaya X-Forwarded-For dari proxy tepercaya.
    return _trusted_client_ip(request)


def _domain_of(url: str) -> str:
    if not url:
        return ""
    if "://" in url:
        url = url.split("://", 1)[1]
    return url.split("/")[0].split(":")[0].lower()


def _domain_match(target: str, host: str) -> bool:
    """Host sama persis atau subdomain dari target (pola v2.0, anti-spoof)."""
    if not target or not host:
        return False
    return host == target or host.endswith("." + target)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _log(
    db: AsyncSession,
    request: Request,
    action: str,
    key_id: int | None = None,
    stream_id: int | None = None,
) -> None:
    """Catat akses embed. ok/gagal dikodekan di `action` karena skema
    api_access_logs tidak punya kolom ok/reason terpisah.

    6.8: ini SATU-SATUNYA titik commit per request embed: satu add
    + satu commit di akhir request (atau di jalur ditolak, sebelum
    raise). Update last_used_at throttled di _validate_key TIDAK
    lagi commit sendiri; perubahannya ikut ter-commit bersama
    insert log ini dalam transaksi yang sama. Request yang ditolak
    di _validate_key tetap punya satu insert (log denied di sini)
    karena sesi ditutup tanpa commit bila tidak ada _log.

    A-1.9: gagal tulis log (DB error) TIDAK boleh mengubah respons
    403/200 yang seharusnya menjadi 500, efek samping sudah terjadi
    (mis. password salah sudah dicatat di _KEY_FAILURES). Kegagalan
    hanya ditulis ke log server, lalu sesi di-rollback supaya tetap
    bisa dipakai pemanggil.
    """
    try:
        db.add(
            ApiAccessLog(
                api_key_id=key_id,
                stream_id=stream_id,
                action=action,
                # 2.7: kolom boolean is_denied diisi dari action yang
                # sama, supaya filter status di list_logs tidak memakai
                # LIKE '%.denied%' (leading %, tak terindeks).
                is_denied=".denied" in action,
                ip=_client_ip(request)[:64],
                user_agent=(request.headers.get("user-agent", "") or "")[:512],
            )
        )
        await db.commit()
    except Exception as e:  # noqa: BLE001 - logging tidak boleh menggagalkan request
        log.warning("log akses embed %s gagal: %s", action, e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


# ── validasi kunci ────────────────────────────────────────────────────

async def _find_key(db: AsyncSession, raw_key: str) -> ApiKey | None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == _key_hash(raw_key))
    )
    return result.scalars().first()


async def _validate_key(
    db: AsyncSession,
    request: Request,
    raw_key: str,
    password: str | None,
    action: str,
) -> ApiKey:
    """Validasi key + password + domain lock. Gagal -> 403 + log."""
    key = await _find_key(db, raw_key or "")
    if key is None or not key.is_active:
        await _log(db, request, f"{action}.denied:bad_key")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Kunci API tidak valid atau tidak aktif"
        )
    if _as_aware(key.expires_at) is not None and _as_aware(key.expires_at) < _now():
        await _log(db, request, f"{action}.denied:expired", key_id=key.id)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Kunci API tidak valid atau tidak aktif"
        )
    if key.password_hash:
        ip = _client_ip(request)
        if _key_locked(key.id, ip):
            await _log(db, request, f"{action}.denied:locked", key_id=key.id)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Terlalu banyak percobaan password salah, coba lagi nanti",
            )
        if not password or not verify_password(password, key.password_hash):
            _record_key_failure(key.id, ip)
            await _log(db, request, f"{action}.denied:bad_password", key_id=key.id)
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Kata sandi akses salah atau tidak disertakan"
            )
        _KEY_FAILURES.pop((key.id, ip), None)
    if key.domain_lock and key.domain_lock.strip():
        # 4.13: domain lock HANYA pencegahan hotlink di browser, BUKAN
        # kontrol akses: header Referer/Origin dikontrol penuh oleh
        # klien non-browser (curl -H "Referer: ..." lolos). Jangan
        # andalkan sebagai keamanan; yang mengunci akses adalah kunci +
        # password + token sesi terikat kamera di bawah ini.
        target = key.domain_lock.strip().lower()
        ref = _domain_of(request.headers.get("referer", ""))
        org = _domain_of(request.headers.get("origin", ""))
        if not (_domain_match(target, ref) or _domain_match(target, org)):
            await _log(db, request, f"{action}.denied:bad_domain", key_id=key.id)
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Akses ditolak: domain asal tidak diizinkan"
            )
    # 6.8: update last_used_at secara throttled (maks 1x per 5 menit
    # per kunci), TANPA commit sendiri. Sebelumnya tiap request embed
    # murah (cek key + ambil URL WHEP) diikuti commit ini + commit
    # _log di akhir request, mengunci baris api_keys yang sama saat
    # banyak embed polling bersamaan. Kini perubahan hanya ditandai
    # di sesi dan ikut ter-commit bersama SATU insert _log di akhir
    # request yang sama (atau bersama log denied bila endpoint
    # menolak setelah validasi). Bila request berakhir tanpa _log
    # (mis. format date/time tidak valid), update ini hilang saat
    # sesi ditutup, dan itu tidak apa-apa: last_used_at hanya
    # penanda pemakaian terakhir, bukan data kritis.
    _now_v = _now()
    _last = _as_aware(key.last_used_at)
    if _last is None or (_now_v - _last).total_seconds() > 300:
        key.last_used_at = _now_v
    return key


async def _key_stream_ids(db: AsyncSession, key_id: int) -> list[int]:
    result = await db.execute(
        select(ApiKeyStream.stream_id)
        .where(ApiKeyStream.api_key_id == key_id)
        .order_by(ApiKeyStream.id)
    )
    return list(result.scalars().all())


def _resolve_camera_ref(ref: int | None, cam_ids: list[int]) -> int | None:
    """Terjemahkan ?camera= menjadi id kamera (pola v2.0).

    Utamakan NOMOR URUT (1 = kamera pertama). Bila bukan nomor urut yang sah
    tapi cocok dengan id milik kunci, id itu tetap diterima (URL lama).
    """
    if not cam_ids:
        return None
    if ref is None:
        return cam_ids[0]
    if 1 <= ref <= len(cam_ids):
        return cam_ids[ref - 1]
    if ref in cam_ids:
        return ref
    return None


def _public_base(request: Request) -> str:
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = request.headers.get("host", "")
    scheme = request.url.scheme or "https"
    return f"{scheme}://{host}".rstrip("/")


def _session_token(key: ApiKey, stream_id: int, ttl_mnt: int) -> str:
    """Token sesi embed yang TERIKAT ke satu kamera (A-T3).

    create_access_token tidak punya parameter klaim tambahan, jadi
    payload dibangun di sini dengan bentuk yang sama ditambah klaim
    "stream_id". Validator WHEP wajib memeriksa klaim itu lewat
    _validate_session_token sebelum memutar kamera.
    """
    settings = get_settings()
    payload = {
        "sub": f"key:{key.id}",
        "username": f"embed:{key.name}",
        "role": "embed",
        "type": "access",
        "stream_id": stream_id,
        "iat": _now(),
        "exp": _now() + timedelta(minutes=ttl_mnt),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _validate_session_token(
    db: AsyncSession, token: str, stream_id: int
) -> int:
    """Validasi token sesi embed untuk satu kamera tertentu.

    Return id API key bila sah. Raise ValueError bila signature/
    kedaluwarsa salah, bukan token embed, atau stream_id di token
    tidak cocok dengan kamera yang diminta (token kamera A tidak
    bisa dipakai untuk kamera B).
    S-2: kunci yang sudah dinonaktifkan, kedaluwarsa, atau tidak
    lagi mengikat kamera itu DITOLAK, supaya mencabut key langsung
    mematikan token sesi yang sudah diterbitkan (bukan menunggu
    token habis sendiri). Pemeriksaan yang sama seperti _validate_key.
    """
    payload = decode_token(token, get_settings())
    if payload.get("type") != "access" or payload.get("role") != "embed":
        raise ValueError("bukan token sesi embed")
    if payload.get("stream_id") != stream_id:
        raise ValueError("token sesi bukan untuk kamera ini")
    sub = str(payload.get("sub") or "")
    if not sub.startswith("key:"):
        raise ValueError("token sesi tidak valid")
    try:
        key_id = int(sub[4:])
    except ValueError as e:
        raise ValueError("token sesi tidak valid") from e
    key = await db.get(ApiKey, key_id)
    if key is None or not key.is_active:
        raise ValueError("kunci API tidak aktif")
    if _as_aware(key.expires_at) is not None and _as_aware(key.expires_at) < _now():
        raise ValueError("kunci API kedaluwarsa")
    bound = await db.execute(
        select(ApiKeyStream.stream_id).where(
            ApiKeyStream.api_key_id == key_id,
            ApiKeyStream.stream_id == stream_id,
        )
    )
    if bound.scalars().first() is None:
        raise ValueError("kamera tidak lagi terikat kunci ini")
    return key_id


def _file_session_token(
    key: ApiKey, stream_id: int, start: datetime, end: datetime, ttl_mnt: int
) -> str:
    """Token sesi embed untuk SATU berkas segmen (4.4).

    Sama seperti _session_token (terikat satu kamera, TTL singkat,
    dicabut bila kunci dinonaktifkan/kedaluwarsa), ditambah klaim
    "kind" + rentang start/end: token ini hanya berlaku untuk segmen
    itu, bukan untuk segmen lain kamera yang sama. URL playback file
    yang bocor hanya hidup selama TTL sesi (default 60 menit, ikut
    session_ttl_mnt kunci), bukan selamanya.
    """
    settings = get_settings()
    payload = {
        "sub": f"key:{key.id}",
        "username": f"embed:{key.name}",
        "role": "embed",
        "type": "access",
        "kind": "playback_file",
        "stream_id": stream_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "iat": _now(),
        "exp": _now() + timedelta(minutes=ttl_mnt),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _validate_file_session_token(
    db: AsyncSession, token: str, start: str, end: str
) -> tuple[int, int]:
    """Validasi token sesi file: kembalikan (key_id, stream_id).

    Memeriksa klaim kind + rentang, lalu memakai _validate_session_token
    untuk signature/kedaluwarsa/kunci aktif/tidak kedaluwarsa/kamera
    masih terikat kunci. Raise ValueError bila tidak sah.
    """
    payload = decode_token(token, get_settings())
    if payload.get("type") != "access" or payload.get("role") != "embed":
        raise ValueError("bukan token sesi file")
    if payload.get("kind") != "playback_file":
        raise ValueError("bukan token sesi file")
    if payload.get("start") != start or payload.get("end") != end:
        raise ValueError("token sesi bukan untuk rentang ini")
    stream_id = payload.get("stream_id")
    if not isinstance(stream_id, int):
        raise ValueError("token sesi tidak valid")
    key_id = await _validate_session_token(db, token, stream_id)
    return key_id, stream_id


def _whep_url(request: Request, stream_id: int, session: str) -> str:
    settings = get_settings()
    base = _public_base(request)
    return f"{base}{settings.public_whep_base}/stream_{stream_id}/whep?session={quote(session)}"


def _whep_url_sub(
    request: Request, stream_id: int, session: str
) -> str:
    """URL WHEP sub-stream (konvensi v3.0: stream_{id}_sub)."""
    settings = get_settings()
    base = _public_base(request)
    wbase = settings.public_whep_base.rstrip("/")
    return f"{base}{wbase}/stream_{stream_id}_sub/whep?session={quote(session)}"


async def _ad_config_dict(
    db: AsyncSession, base_url: str, key: ApiKey | None = None
) -> dict | None:
    """Konfigurasi iklan penuh (field AdConfigIn saat ini); None bila tidak aktif.

    Bila kunci API punya show_ads=False, embed kunci itu tanpa iklan
    (None). Tanpa kunci, atau show_ads True, perilaku lama: tampil
    bila config aktif.

    6.13: baris AdConfig (satu baris, berubah hanya saat admin ubah
    iklan) di-cache in-process TTL 60 dtk, bukan satu query DB per
    request /external/stream. Cache menyimpan config mentah (sebelum
    prefix base_url pada image_url); invalidasi eksplisit di
    admin_ads._set_value.
    """
    if key is not None and key.show_ads is False:
        return None
    cfg = await _cached_ad_config(db)
    if cfg is None:
        return None
    cfg = dict(cfg)
    img = cfg.get("image_url") or ""
    if img.startswith("/"):
        cfg["image_url"] = f"{base_url}{img}"
    return cfg


_AD_CONFIG_TTL_SEC = 60.0
_AD_CONFIG_CACHE_AT = 0.0
_AD_CONFIG_CACHE: dict | None = None
_AD_CONFIG_CACHE_SET = False


def invalidate_ad_config_cache() -> None:
    """Buang cache config iklan (dipakai setelah admin ubah iklan)."""
    global _AD_CONFIG_CACHE_AT, _AD_CONFIG_CACHE, _AD_CONFIG_CACHE_SET
    _AD_CONFIG_CACHE_AT = 0.0
    _AD_CONFIG_CACHE = None
    _AD_CONFIG_CACHE_SET = False


async def _cached_ad_config(db: AsyncSession) -> dict | None:
    """Config iklan gabungan (default + baris DB), atau None bila nonaktif."""
    global _AD_CONFIG_CACHE_AT, _AD_CONFIG_CACHE, _AD_CONFIG_CACHE_SET
    now = time.monotonic()
    if _AD_CONFIG_CACHE_SET and now - _AD_CONFIG_CACHE_AT < _AD_CONFIG_TTL_SEC:
        return dict(_AD_CONFIG_CACHE) if _AD_CONFIG_CACHE is not None else None
    result = await db.execute(select(AdConfig).where(AdConfig.key == "default"))
    row = result.scalars().first()
    cfg = dict(_AD_DEFAULTS)
    if row and isinstance(row.value, dict):
        cfg.update({k: v for k, v in row.value.items() if k in cfg})
    if not cfg.get("is_active"):
        _AD_CONFIG_CACHE = None
        _AD_CONFIG_CACHE_SET = True
        _AD_CONFIG_CACHE_AT = now
        return None
    _AD_CONFIG_CACHE = cfg
    _AD_CONFIG_CACHE_SET = True
    _AD_CONFIG_CACHE_AT = now
    return dict(cfg)


# ── endpoint ──────────────────────────────────────────────────────────

@router.get("/external/cameras", dependencies=[Depends(rate_limited(20, 60))])
async def external_cameras(
    request: Request,
    camera: int | None = Query(None, description="nomor urut (1=utama); id juga diterima"),
    stream_id: int | None = Query(None, description="alias dari camera"),
    db: AsyncSession = Depends(get_db),
):
    """FROZEN, daftar kamera milik satu kunci API. ?camera= menyaring satu kamera.

    Auth: header X-Api-Key (+ X-Api-Key-Password). Query ?key= ditolak 400.
    """
    _reject_query_credentials(request)
    raw_key, raw_password = _api_key_credentials(request)
    key_rec = await _validate_key(
        db, request, raw_key or "", raw_password, "external.cameras"
    )
    ids = await _key_stream_ids(db, key_rec.id)
    if camera is not None or stream_id is not None:
        target = _resolve_camera_ref(
            camera if camera is not None else stream_id, ids
        )
        if target is None or target not in ids:
            await _log(
                db, request, "external.cameras.denied:bad_camera",
                key_id=key_rec.id,
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Nomor kamera tidak sah. Kunci ini punya {len(ids)} kamera.",
            )
        ids = [target]
    items = []
    if ids:
        result = await db.execute(
            select(Stream).where(Stream.id.in_(ids), Stream.is_active.is_(True))
        )
        by_id = {st.id: st for st in result.scalars().all()}
        # Urutan mengikuti urutan kamera di kunci (bukan alfabetis):
        # ?camera=1 berarti kamera pertama di daftar ini, jadi daftar
        # dan penomoran harus selaras.
        for sid in ids:
            st = by_id.get(sid)
            if st is not None:
                items.append(
                    {"id": st.id, "name": st.name, "is_online": bool(st.is_online)}
                )
    await _log(db, request, "external.cameras.ok", key_id=key_rec.id)
    return items


@router.get("/external/stream", dependencies=[Depends(rate_limited(20, 60))])
async def external_stream(
    request: Request,
    camera: int | None = Query(None, description="nomor urut (1=utama); id juga diterima"),
    stream_id: int | None = Query(None, description="alias dari camera"),
    db: AsyncSession = Depends(get_db),
):
    """FROZEN, URL WHEP embed + token sesi singkat.

    Auth: header X-Api-Key (+ X-Api-Key-Password). Query ?key= ditolak 400.

    Response {url, expires_at} + ADITIF v2.0: stream {id, name, webrtc_url,
    webrtc_url_sub, coordinates, embed_timeout_seconds, click_to_play}
    dan ad {konfigurasi iklan penuh, field AdConfigIn} (null bila iklan
    nonaktif).
    """
    _reject_query_credentials(request)
    raw_key, raw_password = _api_key_credentials(request)
    key_rec = await _validate_key(
        db, request, raw_key or "", raw_password, "external.stream"
    )
    ids = await _key_stream_ids(db, key_rec.id)
    target = _resolve_camera_ref(camera if camera is not None else stream_id, ids)
    if target is None or target not in ids:
        await _log(
            db, request, "external.stream.denied:bad_camera", key_id=key_rec.id
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Nomor kamera tidak sah. Kunci ini punya {len(ids)} kamera.",
        )
    result = await db.execute(select(Stream).where(Stream.id == target))
    stream = result.scalars().first()
    if stream is None or not stream.is_active:
        await _log(
            db, request, "external.stream.denied:gone",
            key_id=key_rec.id, stream_id=target,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kamera tidak tersedia")

    ttl = key_rec.session_ttl_mnt or _DEFAULT_TTL_MNT
    token = _session_token(key_rec, target, ttl)
    expires_at = _now() + timedelta(minutes=ttl)
    url = _whep_url(request, target, token)
    base = _public_base(request)
    ad_cfg = await _ad_config_dict(db, base, key_rec)
    coords = None
    if stream.latitude is not None and stream.longitude is not None:
        coords = f"{stream.latitude},{stream.longitude}"
    await _log(
        db, request, "external.stream.ok", key_id=key_rec.id, stream_id=target
    )
    return {
        "url": url,
        "expires_at": expires_at.isoformat(),
        "stream": {
            "id": target,
            "name": stream.name,
            "webrtc_url": url,
            # A-1.15: tanpa sub_url, kembalikan None seperti stream_to_out;
            # sebelumnya URL sub selalu dikembalikan dan klien embed
            # mencoba substream yang tidak terdaftar di MediaMTX.
            "webrtc_url_sub": (
                _whep_url_sub(request, target, token)
                if stream.sub_url
                else None
            ),
            "coordinates": coords,
            "embed_timeout_seconds": (
                ad_cfg.get("embed_timeout_seconds", 300) if ad_cfg else 300
            ),
            "click_to_play": (
                ad_cfg.get("click_to_play", True) if ad_cfg else True
            ),
        },
        "ad": ad_cfg,
    }


@router.get("/external/playback", dependencies=[Depends(rate_limited(20, 60))])
async def external_playback(
    request: Request,
    camera: int | None = Query(None),
    stream_id: int | None = Query(None, description="alias dari camera"),
    date: str | None = Query(None, description="YYYY-MM-DD (v2.0)"),
    time: str | None = Query(None, description="ISO datetime -> satu URL (v3.0)"),
    db: AsyncSession = Depends(get_db),
):
    """FROZEN, playback untuk klien kunci API (pola v2.0).

    Auth: header X-Api-Key (+ X-Api-Key-Password). Query ?key= ditolak 400.

    Tanpa ?date=/?time= -> {camera, camera_name, total_cameras, cameras, dates}.
    Dengan ?date=YYYY-MM-DD -> segmen tanggal itu + URL putar tiap segmen.
    Dengan ?time=ISO -> satu {url, expires_at} (bentuk v3.0).
    """
    from app.routers.recordings import _all_segments

    _reject_query_credentials(request)
    raw_key, raw_password = _api_key_credentials(request)
    key_rec = await _validate_key(
        db, request, raw_key or "", raw_password, "external.playback"
    )
    ids = await _key_stream_ids(db, key_rec.id)
    target = _resolve_camera_ref(camera if camera is not None else stream_id, ids)
    if target is None or target not in ids:
        await _log(
            db, request, "external.playback.denied:bad_camera", key_id=key_rec.id
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Nomor kamera tidak sah. Kunci ini punya {len(ids)} kamera.",
        )
    result = await db.execute(select(Stream).where(Stream.id == target))
    stream = result.scalars().first()
    if stream is None or not stream.is_active:
        await _log(
            db, request, "external.playback.denied:gone",
            key_id=key_rec.id, stream_id=target,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kamera tidak tersedia")

    # A-T4: hormati include_playback=False pada API key.
    if key_rec.include_playback is False:
        await _log(
            db, request, "external.playback.denied:no_playback",
            key_id=key_rec.id, stream_id=target,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Playback tidak diizinkan untuk kunci ini"
        )

    settings = get_settings()
    rec_dir = settings.recordings_dir
    nomor = ids.index(target) + 1
    # A-1.14: urutan `cameras` mengikuti urutan kamera di kunci (ids),
    # selaras dengan penomoran ?camera=N di _resolve_camera_ref dan
    # dengan external_cameras; sebelumnya tanpa ORDER BY sehingga
    # daftar dan penomoran bisa tidak selaras.
    cam_result = await db.execute(
        select(Stream.id, Stream.name).where(Stream.id.in_(ids))
    )
    by_id = {i: n for i, n in cam_result.all()}
    cameras = [
        {"id": sid, "name": by_id[sid]} for sid in ids if sid in by_id
    ]

    def _file_url(seg_start: datetime, seg_end: datetime | None) -> str:
        # 4.4: URL file memakai token sesi singkat terikat kamera +
        # rentang (bukan key+pass mentah tanpa kedaluwarsa). Token
        # kedaluwarsa mengikuti session_ttl_mnt kunci, sama seperti
        # expires_at yang dikembalikan cabang ?time= di bawah.
        ttl = key_rec.session_ttl_mnt or _DEFAULT_TTL_MNT
        seg_end = seg_end or seg_start
        token = _file_session_token(key_rec, target, seg_start, seg_end, ttl)
        return (
            "/api/external/playback/file"
            f"?session={quote(token)}&camera={nomor}"
            f"&start={quote(seg_start.isoformat())}"
            f"&end={quote(seg_end.isoformat())}"
        )

    if date:
        # A-1.17: ?date= dan ?time= bersamaan ditolak 403 (kontrak
        # FROZEN external memakai 403 untuk semua error); sebelumnya
        # cabang date menang dan time diabaikan diam-diam.
        if time:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "kirim ?date= atau ?time= saja, tidak keduanya",
            )
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            # A-S3: kontrak FROZEN external memakai 403 untuk semua error.
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "format date tidak valid (pakai YYYY-MM-DD)",
            )
        # Segmen Drive-aware seperti /recordings (lokal + folder-link +
        # rclone + OAuth), bukan hanya lokal: kamera mode drive/both
        # yang segmennya hanya di Drive sebelumnya tampil kosong di sini.
        segs = await _all_segments(stream, day, db)
        items = [
            {
                "start": s.start.isoformat(),
                "end": (s.end or s.start).isoformat(),
                "size_bytes": s.size,
                "url": _file_url(s.start, s.end),
            }
            for s in segs
        ]
        await _log(
            db, request, "external.playback.ok", key_id=key_rec.id,
            stream_id=target,
        )
        return {
            "camera": nomor, "camera_name": stream.name,
            "total_cameras": len(ids), "cameras": cameras,
            "date": date, "segments": items,
        }

    if time:
        from app.routers.recordings import _containing

        try:
            at = datetime.fromisoformat(time)
        except ValueError:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "format time tidak valid"
            )
        seg = await _containing(stream, at, db)
        if seg is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "tidak ada rekaman"
            )
        ttl = key_rec.session_ttl_mnt or _DEFAULT_TTL_MNT
        expires_at = _now() + timedelta(minutes=ttl)
        await _log(
            db, request, "external.playback.ok", key_id=key_rec.id,
            stream_id=target,
        )
        return {
            "url": _file_url(seg.start, seg.end),
            "expires_at": expires_at.isoformat(),
        }

    dates = []
    # 6.5: tanggal + jumlah segmen dari sumber murah (listdir lokal +
    # drive_uploads), bukan _all_segments penuh (lsjson + list_files
    # Drive) hanya untuk daftar tanggal. Fallback penuh hanya bila
    # jejak upload kosong (pola 1ce30a2).
    from app.routers.recordings import _cheap_segment_dates

    _counts, _needs_full = await _cheap_segment_dates(stream, db)
    if _needs_full:
        all_segs = await _all_segments(stream, None, db)
        from collections import Counter as _Counter

        _counts = _Counter(s.start.date().isoformat() for s in all_segs)
    for d in sorted(_counts, reverse=True):
        dates.append({"date": d, "segment_count": _counts[d]})
    await _log(
        db, request, "external.playback.ok", key_id=key_rec.id,
        stream_id=target,
    )
    return {
        "camera": nomor, "camera_name": stream.name,
        "total_cameras": len(ids), "cameras": cameras,
        "dates": dates,
    }


@router.get("/external/playback/file", dependencies=[Depends(rate_limited(20, 60))])
async def external_playback_file(
    request: Request,
    camera: int | None = Query(None),
    stream_id: int | None = Query(None, description="alias dari camera"),
    start: str = Query(...),
    end: str = Query(...),
    session: str | None = Query(
        None,
        description="token sesi file dari GET /external/playback (4.4)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Berkas segmen rekaman untuk klien kunci API.

    Auth HANYA: ?session= (token sesi file terikat kamera + rentang,
    TTL singkat, diterbitkan GET /external/playback).
    2026-11-18 (BREAKING CHANGE): fallback legacy ?key=&pass= (pola
    v2.0) DIHAPUS. URL lama yang bocor tidak lagi berlaku selamanya;
    klien wajib memakai URL baru dari GET /external/playback.
    Kredensial di query (?key=/?password=/?pass=) ditolak 400.
    """
    from app.routers.recordings import _containing, _serve_segment

    _reject_query_credentials(request)
    if not session:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Token sesi file tidak valid"
        )
    try:
        key_id, token_stream_id = await _validate_file_session_token(
            db, session, start, end
        )
    except ValueError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Token sesi file tidak valid"
        )
    key_rec = await db.get(ApiKey, key_id)
    if key_rec is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Kunci API tidak valid atau tidak aktif"
        )
    ids = await _key_stream_ids(db, key_rec.id)
    target = _resolve_camera_ref(camera if camera is not None else stream_id, ids)
    if target is None or target not in ids or target != token_stream_id:
        await _log(
            db, request, "external.playback.file.denied:bad_camera",
            key_id=key_rec.id,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Nomor kamera tidak sah. Kunci ini punya {len(ids)} kamera.",
        )
    result = await db.execute(select(Stream).where(Stream.id == target))
    stream = result.scalars().first()
    if stream is None or not stream.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kamera tidak tersedia")
    # A-T4: hormati include_playback=False pada API key.
    if key_rec.include_playback is False:
        await _log(
            db, request, "external.playback.file.denied:no_playback",
            key_id=key_rec.id, stream_id=target,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Playback tidak diizinkan untuk kunci ini"
        )
    try:
        at = datetime.fromisoformat(start)
    except ValueError:
        # A-S3: kontrak FROZEN external memakai 403 untuk semua error.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "format start tidak valid"
        )
    try:
        at_end = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "format end tidak valid"
        )
    # A-1.16: tolak end <= start seperti /recordings/{id}/file;
    # sebelumnya end == start lolos lalu trim durasi 0 mengembalikan
    # None dan segmen utuh disajikan diam-diam. A-1.7: bandingkan
    # setelah konversi ke waktu lokal server (aware vs naive yang
    # dicampur bisa TypeError; _containing/_serve_segment juga
    # mengonversi, tapi perbandingan di sini harus konsisten).
    from app.routers.recordings import _to_server_naive

    at = _to_server_naive(at)
    at_end = _to_server_naive(at_end)
    if at_end <= at:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "end harus setelah start"
        )
    seg = await _containing(stream, at, db)
    if seg is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tidak ada rekaman")
    await _log(
        db, request, "external.playback.file.ok", key_id=key_rec.id,
        stream_id=target,
    )
    # Teruskan rentang yang diminta seperti /recordings/{id}/file
    # (potong via ffmpeg bila perlu); sebelumnya `end` diabaikan dan
    # selalu dikembalikan segmen utuh.
    return await _serve_segment(
        stream, seg, download=False, db=db, request=request,
        start=at, end=at_end,
    )
