"""Router embed pihak ketiga (MIGRATION-MAP §8 — KONTRAK FROZEN).

Tidak memakai login user; auth via API key di query string.
Bentuk response mengikuti packages/contracts/openapi.yaml dan TIDAK diubah:
  - GET /api/external/cameras  -> [{id, name}] (+is_online aditif)
  - GET /api/external/stream   -> {url, expires_at}
  - GET /api/external/playback -> {url, expires_at}
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
from app.models.streams import Stream

router = APIRouter()

_DEFAULT_TTL_MNT = 60


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


# ── endpoint ──────────────────────────────────────────────────────────

@router.get("/external/cameras")
async def external_cameras(
    request: Request,
    key: str = Query(...),
    password: str | None = Query(None),
    pass_: str | None = Query(None, alias="pass"),
    db: AsyncSession = Depends(get_db),
):
    """FROZEN — daftar kamera milik satu kunci API."""
    key_rec = await _validate_key(
        db, request, key, password or pass_, "external.cameras"
    )
    ids = await _key_stream_ids(db, key_rec.id)
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
    """FROZEN — URL WHEP embed + token sesi singkat. Response {url, expires_at}."""
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
    await _log(
        db, request, "external.stream.ok", key_id=key_rec.id, stream_id=target
    )
    return {"url": url, "expires_at": expires_at.isoformat()}


@router.get("/external/playback")
async def external_playback(
    request: Request,
    key: str = Query(...),
    camera: int | None = Query(None),
    stream_id: int | None = Query(None, description="alias dari camera"),
    time: str | None = Query(None),
    password: str | None = Query(None),
    pass_: str | None = Query(None, alias="pass"),
    db: AsyncSession = Depends(get_db),
):
    """FROZEN — URL playback embed. Response {url, expires_at}."""
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

    # Service rekaman dibangun Fase 3a — import defensif di dalam fungsi.
    try:
        from app.services import recordings  # noqa: F401
        builder = getattr(recordings, "build_playback_url", None)
    except ImportError:
        builder = None
    if builder is None:
        await _log(
            db, request, "external.playback.denied:no_service",
            key_id=key_rec.id, stream_id=target,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Pemutaran ulang tersedia mulai Fase 3",
        )

    ttl = key_rec.session_ttl_mnt or _DEFAULT_TTL_MNT
    expires_at = _now() + timedelta(minutes=ttl)
    url = builder(target, time)
    await _log(
        db, request, "external.playback.ok", key_id=key_rec.id, stream_id=target
    )
    return {"url": url, "expires_at": expires_at.isoformat()}
