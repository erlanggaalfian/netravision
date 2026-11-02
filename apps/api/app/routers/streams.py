"""Router streams (pengguna): daftar, reconnect, poster.

Path /api/* dipertahankan persis seperti v2.0.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rbac import (
    require_camera_access,
    require_camera_access_token_qp,
    require_roles,
)
from app.db.session import get_db
from app.models.access import StreamPermission, UserStreamAccess
from app.models.streams import Stream
from app.models.users import User
from app.schemas.stream import StreamOut
from app.services.mediamtx import MediaMTXClient, get_mediamtx

router = APIRouter(tags=["streams"])
log = logging.getLogger("netravision.streams")


def _whep_urls(settings: Settings, stream_id: int, has_sub: bool) -> tuple[str, str | None]:
    """URL WHEP publik (relatif; Apache mem-proxy /whep/ -> MediaMTX)."""
    base = settings.public_whep_base.rstrip("/")
    main = f"{base}/stream_{stream_id}/whep"
    sub = f"{base}/stream_{stream_id}_sub/whep" if has_sub else None
    return main, sub


def stream_to_out(stream: Stream, settings: Settings) -> StreamOut:
    main_url, sub_url = _whep_urls(settings, stream.id, bool(stream.sub_url))
    return StreamOut(
        id=stream.id,
        name=stream.name,
        brand=stream.brand,
        is_online=stream.is_online,
        is_active=stream.is_active,
        last_seen_at=stream.last_seen_at,
        whep_main_url=main_url,
        whep_sub_url=sub_url,
        poster_url=f"/api/posters/stream_{stream.id}.jpg",
        latitude=stream.latitude,
        longitude=stream.longitude,
        storage_mode=stream.storage_mode,
        drive_account_id=stream.drive_account_id,
        drive_folder_id=stream.drive_folder_id,
        recording_enabled=stream.recording_enabled,
        retention_days=stream.retention_days,
    )


async def _visible_streams(user: User, db: AsyncSession) -> list[Stream]:
    result = await db.execute(
        select(Stream).where(Stream.is_active.is_(True)).order_by(Stream.id)
    )
    streams = list(result.scalars().all())
    if user.role == "admin":
        return streams
    allowed: set[int] = set(
        (
            await db.execute(
                select(UserStreamAccess.stream_id).where(
                    UserStreamAccess.user_id == user.id,
                    UserStreamAccess.can_view.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    allowed.update(
        (
            await db.execute(
                select(StreamPermission.stream_id).where(
                    StreamPermission.role == user.role,
                    StreamPermission.can_view.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return [s for s in streams if s.id in allowed]


async def _get_stream_or_404(db: AsyncSession, stream_id: int) -> Stream:
    stream = await db.get(Stream, stream_id)
    if stream is None or not stream.is_active:
        raise HTTPException(status_code=404, detail="stream tidak ditemukan")
    return stream


@router.get("/streams", response_model=list[StreamOut])
async def list_streams(
    user: User = Depends(require_roles("admin", "user", "guest")),
    db: AsyncSession = Depends(get_db),
    page: int | None = Query(None, ge=1, description="v2.0: halaman"),
    limit: int | None = Query(None, ge=1, le=500, description="v2.0: batas"),
    group: str | None = Query(None, description="v2.0: filter nama grup (persis)"),
    no_check: bool = Query(False, description="v2.0: lewati cek status"),
):
    """Daftar stream yang terlihat user.

    Tanpa ?page=/?limit= -> list penuh (perilaku v3.0 sekarang).
    Dengan salah satunya -> paginasi (limit default 20 bila hanya page dipakai).
    ?group= menyaring nama grup persis (v2.0). ?no_check= diterima untuk
    kompatibilitas v2.0; status online di v3.0 berasal dari poller latar.
    """
    settings = get_settings()
    streams = await _visible_streams(user, db)
    if group:
        streams = [s for s in streams if (s.group_name or "") == group]
    if page is not None or limit is not None:
        lim = limit or 20
        pg = page or 1
        streams = streams[(pg - 1) * lim : pg * lim]
    return [stream_to_out(s, settings) for s in streams]


@router.post("/streams/{stream_id}/reconnect")
async def reconnect_stream(
    stream_id: int,
    _user: User = Depends(require_roles("admin", "user")),
    _access: User = Depends(require_camera_access),
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx),
):
    """Hapus + daftarkan ulang path MediaMTX dari main_url/sub_url tersimpan."""
    stream = await _get_stream_or_404(db, stream_id)
    try:
        await mediamtx.delete_path(f"stream_{stream_id}")
        if stream.main_url:
            await mediamtx.create_path(f"stream_{stream_id}", stream.main_url)
        await mediamtx.delete_path(f"stream_{stream_id}_sub")
        if stream.sub_url:
            await mediamtx.create_path(f"stream_{stream_id}_sub", stream.sub_url)
    except Exception as e:  # noqa: BLE001 - semua kegagalan MediaMTX -> 502, bukan 500
        log.warning("reconnect stream %s gagal: %s", stream_id, e)
        raise HTTPException(status_code=502, detail=f"MediaMTX tidak terjangkau: {e}")
    return {"ok": True}


@router.get("/posters/stream_{stream_id}.jpg")
async def get_poster(
    stream_id: int,
    _access: User = Depends(require_camera_access_token_qp),
):
    # Token boleh via header Authorization atau ?token= (img tidak bisa kirim header).
    # TODO Fase 3: worker capture poster otomatis mengisi direktori ini.
    path = Path(get_settings().posters_dir) / f"stream_{stream_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="poster belum tersedia")
    return FileResponse(path, media_type="image/jpeg")
