"""Router embed pihak ketiga (MIGRATION-MAP §8 — KONTRAK FROZEN).

Tidak memakai login user; auth via API key di query string.
Bentuk response mengikuti packages/contracts/openapi.yaml; field v2.0
ditambahkan SECARA ADITIF (tidak menghapus field v3.0 yang ada):
  - GET /api/external/cameras  -> [{id, name}] (+is_online aditif; ?camera= opsional)
  - GET /api/external/stream   -> {url, expires_at} (+stream {...}, +ad {...})
  - GET /api/external/playback -> v2.0: tanpa ?date=/?time= daftar tanggal;
                                  ?date=YYYY-MM-DD -> segmen + URL putar;
                                  ?time=ISO -> satu {url, expires_at}
  - GET /api/external/playback/file -> berkas segmen (auth via ?key=)
Kegagalan -> 403 (perilaku v2.0), tanpa membocorkan informasi.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream
from app.models.misc import AdConfig
from app.models.streams import Stream

router = APIRouter()

_DEFAULT_TTL_MNT = 60

# Default konfigurasi iklan v2.0 (16 field); digabung dengan yang tersimpan.
_AD_DEFAULTS = {
    "image_url": "", "marquee_text": "", "bg_color": "#1e293b",
    "text_color": "#ffffff", "scroll_speed": 5, "font_size": 10,
    "font_family": "monospace", "image_opacity": 1.0, "bg_opacity": 1.0,
    "text_opacity": 1.0, "is_active": True, "box_width": 100,
    "text_align": "left", "image_height": 20,
    "embed_timeout_seconds": 300, "click_to_play": True,
}


# ── util ──────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return (
        request.headers.get("x-real-ip", "")
        or (request.client.host if request.client else "")
    )


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
    api_access_logs tidak punya kolom ok/reason terpisah."""
    db.add(
        ApiAccessLog(
            api_key_id=key_id,
            stream_id=stream_id,
            action=action,
            ip=_client_ip(request)[:64],
            user_agent=(request.headers.get("user-agent", "") or "")[:512],
        )
    )
    await db.commit()


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
        if not password or not verify_password(password, key.password_hash):
            await _log(db, request, f"{action}.denied:bad_password", key_id=key.id)
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Kata sandi akses salah atau tidak disertakan"
            )
    if key.domain_lock and key.domain_lock.strip():
        target = key.domain_lock.strip().lower()
        ref = _domain_of(request.headers.get("referer", ""))
        org = _domain_of(request.headers.get("origin", ""))
        if not (_domain_match(target, ref) or _domain_match(target, org)):
            await _log(db, request, f"{action}.denied:bad_domain", key_id=key.id)
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Akses ditolak: domain asal tidak diizinkan"
            )
    key.last_used_at = _now()
    await db.commit()
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
    settings = get_settings()
    return create_access_token(
        user_id=f"key:{key.id}",
        username=f"embed:{key.name}",
        role="embed",
        settings=settings,
        expires_minutes=ttl_mnt,
    )


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


async def _ad_config_dict(db: AsyncSession, base_url: str) -> dict | None:
    """Konfigurasi iklan penuh (16 field v2.0); None bila tidak aktif.

    Akses API key bukan user login -> show_ads dianggap boleh tampil (v2.0).
    """
    result = await db.execute(select(AdConfig).where(AdConfig.key == "default"))
    row = result.scalars().first()
    cfg = dict(_AD_DEFAULTS)
    if row and isinstance(row.value, dict):
        cfg.update({k: v for k, v in row.value.items() if k in cfg})
    if not cfg.get("is_active"):
        return None
    img = cfg.get("image_url") or ""
    if img.startswith("/"):
        cfg["image_url"] = f"{base_url}{img}"
    return cfg


# ── endpoint ──────────────────────────────────────────────────────────

@router.get("/external/cameras")
async def external_cameras(
    request: Request,
    key: str = Query(...),
    camera: int | None = Query(None, description="nomor urut (1=utama); id juga diterima"),
    stream_id: int | None = Query(None, description="alias dari camera"),
    password: str | None = Query(None),
    pass_: str | None = Query(None, alias="pass"),
    db: AsyncSession = Depends(get_db),
):
    """FROZEN — daftar kamera milik satu kunci API. ?camera= menyaring satu kamera."""
    key_rec = await _validate_key(
        db, request, key, password or pass_, "external.cameras"
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
        for st in result.scalars().all():
            items.append(
                {"id": st.id, "name": st.name, "is_online": bool(st.is_online)}
            )
    items.sort(key=lambda x: x["name"].lower())
    await _log(db, request, "external.cameras.ok", key_id=key_rec.id)
    return items


@router.get("/external/stream")
async def external_stream(
    request: Request,
    key: str = Query(...),
    camera: int | None = Query(None, description="nomor urut (1=utama); id juga diterima"),
    stream_id: int | None = Query(None, description="alias dari camera"),
    password: str | None = Query(None),
    pass_: str | None = Query(None, alias="pass"),
    db: AsyncSession = Depends(get_db),
):
    """FROZEN — URL WHEP embed + token sesi singkat.

    Response {url, expires_at} + ADITIF v2.0: stream {id, name, webrtc_url,
    webrtc_url_sub, coordinates, embed_timeout_seconds, click_to_play}
    dan ad {16 field konfigurasi iklan} (null bila iklan nonaktif).
    """
    key_rec = await _validate_key(
        db, request, key, password or pass_, "external.stream"
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
    ad_cfg = await _ad_config_dict(db, base)
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
            "webrtc_url_sub": (
                _whep_url_sub(request, target, token)
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


@router.get("/external/playback")
async def external_playback(
    request: Request,
    key: str = Query(...),
    camera: int | None = Query(None),
    stream_id: int | None = Query(None, description="alias dari camera"),
    date: str | None = Query(None, description="YYYY-MM-DD (v2.0)"),
    time: str | None = Query(None, description="ISO datetime -> satu URL (v3.0)"),
    password: str | None = Query(None),
    pass_: str | None = Query(None, alias="pass"),
    db: AsyncSession = Depends(get_db),
):
    """FROZEN — playback untuk klien kunci API (pola v2.0).

    Tanpa ?date=/?time= -> {camera, camera_name, total_cameras, cameras, dates}.
    Dengan ?date=YYYY-MM-DD -> segmen tanggal itu + URL putar tiap segmen.
    Dengan ?time=ISO -> satu {url, expires_at} (bentuk v3.0).
    """
    from app.services.recording import list_dates, list_segments

    key_rec = await _validate_key(
        db, request, key, password or pass_, "external.playback"
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

    settings = get_settings()
    rec_dir = settings.recordings_dir
    nomor = ids.index(target) + 1
    cam_result = await db.execute(
        select(Stream.id, Stream.name).where(Stream.id.in_(ids))
    )
    cameras = [{"id": i, "name": n} for i, n in cam_result.all()]

    def _file_url(seg_start: datetime, seg_end: datetime | None) -> str:
        q = f"key={quote(key)}"
        if password or pass_:
            q += f"&pass={quote(password or pass_ or '')}"
        return (
            "/api/external/playback/file"
            f"?{q}&camera={nomor}"
            f"&start={quote(seg_start.isoformat())}"
            f"&end={quote((seg_end or seg_start).isoformat())}"
        )

    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "format date tidak valid (pakai YYYY-MM-DD)",
            )
        segs = list_segments(target, day=day, recordings_dir=rec_dir)
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
                status.HTTP_400_BAD_REQUEST, "format time tidak valid"
            )
        seg = await _containing(stream, at, db)
        if seg is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "tidak ada rekaman"
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
    for d in list_dates(target, rec_dir):
        try:
            day = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        n = len(list_segments(target, day=day, recordings_dir=rec_dir))
        dates.append({"date": d, "segment_count": n})
    dates.sort(key=lambda x: x["date"], reverse=True)
    await _log(
        db, request, "external.playback.ok", key_id=key_rec.id,
        stream_id=target,
    )
    return {
        "camera": nomor, "camera_name": stream.name,
        "total_cameras": len(ids), "cameras": cameras,
        "dates": dates,
    }


@router.get("/external/playback/file")
async def external_playback_file(
    request: Request,
    key: str = Query(...),
    camera: int | None = Query(None),
    stream_id: int | None = Query(None, description="alias dari camera"),
    start: str = Query(...),
    end: str = Query(...),
    password: str | None = Query(None),
    pass_: str | None = Query(None, alias="pass"),
    db: AsyncSession = Depends(get_db),
):
    """Berkas segmen rekaman untuk klien kunci API (auth via ?key=, pola v2.0)."""
    from app.routers.recordings import _containing, _serve_segment

    key_rec = await _validate_key(
        db, request, key, password or pass_, "external.playback.file"
    )
    ids = await _key_stream_ids(db, key_rec.id)
    target = _resolve_camera_ref(camera if camera is not None else stream_id, ids)
    if target is None or target not in ids:
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
    try:
        at = datetime.fromisoformat(start)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "format start tidak valid"
        )
    seg = await _containing(stream, at, db)
    if seg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
    await _log(
        db, request, "external.playback.file.ok", key_id=key_rec.id,
        stream_id=target,
    )
    return await _serve_segment(stream, seg, download=False, db=db)
