"""Router streams (pengguna): daftar, reconnect, poster.

Path /api/* dipertahankan persis seperti v2.0.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import rate_limited
from app.core.rbac import (
    get_current_user,
    is_super_admin,
    require_camera_access,
    require_roles,
)
from app.core.security import redact_url_credentials
from app.db.session import get_db
from app.models.access import StreamAdminGrant, StreamPermission, UserStreamAccess
from app.models.groups import GroupStream, StreamGroup
from app.models.streams import Stream
from app.models.users import User
from app.schemas.stream import StreamOut
from app.services.mediamtx import MediaMTXClient, get_mediamtx_dep

router = APIRouter(tags=["streams"])
log = logging.getLogger("netravision.streams")


def _whep_urls(settings: Settings, stream_id: int, has_sub: bool) -> tuple[str, str | None]:
    """URL WHEP publik (relatif; Apache mem-proxy /whep/ -> MediaMTX)."""
    base = settings.public_whep_base.rstrip("/")
    main = f"{base}/stream_{stream_id}/whep"
    sub = f"{base}/stream_{stream_id}_sub/whep" if has_sub else None
    return main, sub


def stream_to_out(stream: Stream, settings: Settings) -> StreamOut:
    # Sub HANYA bila kamera punya sub_url asli (transcoder mati total,
    # 2026-11-14). Tanpa sub_url, whep_sub_url None dan frontend
    # memakai main sebagai fallback supaya tile tidak hitam.
    main_url, sub_url = _whep_urls(settings, stream.id, bool(stream.sub_url))
    return StreamOut(
        id=stream.id,
        name=stream.name,
        brand=stream.brand,
        group_name=stream.group_name,
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
        record_disk=stream.record_disk,
    )


def _visible_streams_query(user: User, group_id: int | None = None):
    """Query Stream yang terlihat user, visibilitas di level SQL.

    6.11: aturan RBAC sama persis seperti _visible_streams lama,
    hanya dipindah dari filter Python ke WHERE SQL supaya
    LIMIT/OFFSET + COUNT benar-benar menghemat query DB:
      super_admin: semua kamera aktif.
      admin: miliknya (created_by ATAU owner_id) atau yang
        di-grant can_view (StreamAdminGrant).
      user/guest: yang dibagikan eksplisit (UserStreamAccess
        can_view) atau lewat peran (StreamPermission role-nya,
        user_id NULL, can_view).
    group_id (bila diisi): hanya kamera anggota grup itu
    (GroupStream). Dipakai list_streams (?group=) dan pemanggil
    lain yang butuh filter grup.
    """
    q = select(Stream).where(Stream.is_active.is_(True))
    if user.role == "super_admin":
        pass
    elif user.role == "admin":
        # A-T2: admin biasa hanya melihat kamera miliknya sendiri
        # (created_by ATAU owner_id) atau yang di-grant can_view.
        # Periksa keduanya terpisah: `created_by or owner_id` salah
        # bila created_by terisi orang lain.
        q = q.where(
            or_(
                Stream.created_by == user.id,
                Stream.owner_id == user.id,
                Stream.id.in_(
                    select(StreamAdminGrant.stream_id).where(
                        StreamAdminGrant.admin_id == user.id,
                        StreamAdminGrant.can_view.is_(True),
                    )
                ),
            )
        )
    else:
        q = q.where(
            or_(
                Stream.id.in_(
                    select(UserStreamAccess.stream_id).where(
                        UserStreamAccess.user_id == user.id,
                        UserStreamAccess.can_view.is_(True),
                    )
                ),
                Stream.id.in_(
                    select(StreamPermission.stream_id).where(
                        StreamPermission.role == user.role,
                        StreamPermission.user_id.is_(None),
                        StreamPermission.can_view.is_(True),
                    )
                ),
            )
        )
    if group_id is not None:
        q = q.where(
            Stream.id.in_(
                select(GroupStream.stream_id).where(
                    GroupStream.group_id == group_id
                )
            )
        )
    return q.order_by(Stream.id)


async def _visible_streams(user: User, db: AsyncSession) -> list[Stream]:
    result = await db.execute(_visible_streams_query(user))
    return list(result.scalars().all())


async def _visible_streams_paged(
    user: User,
    db: AsyncSession,
    group: str | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> tuple[list[Stream], int]:
    """Kamera terlihat + total, paginasi di level SQL (6.11).

    Tanpa ?page=/?limit= -> list penuh + total = len (perilaku
    v3.0 sekarang). Dengan salah satunya -> LIMIT/OFFSET di SQL
    dan COUNT terpisah, total dikirim pemanggil lewat header
    X-Total-Count seperti admin_keys.list_logs. ?group= yang
    tidak ada di DB -> ([], 0), sama seperti filter Python lama.
    """
    group_id: int | None = None
    if group:
        # A-S9: keanggotaan grup dibaca dari tabel group_streams,
        # bukan kolom streams.group_name yang tidak pernah diisi.
        grp = (
            (await db.execute(select(StreamGroup).where(StreamGroup.name == group)))
            .scalars()
            .first()
        )
        if grp is None:
            return [], 0
        group_id = grp.id
    q = _visible_streams_query(user, group_id)
    if page is None and limit is None:
        result = await db.execute(q)
        streams = list(result.scalars().all())
        return streams, len(streams)
    lim = limit or 20
    pg = page or 1
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(q.limit(lim).offset((pg - 1) * lim))
    return list(result.scalars().all()), total


async def _get_stream_or_404(
    db: AsyncSession, stream_id: int, require_active: bool = True
) -> Stream:
    """Ambil stream atau 404.

    require_active=True (default, untuk penonton/playback): stream nonaktif
    dianggap tidak ada. require_active=False (untuk admin): cukup ada di DB,
    supaya kamera nonaktif tetap bisa diaktifkan lagi, dihapus, atau diatur.
    """
    stream = await db.get(Stream, stream_id)
    if stream is None or (require_active and not stream.is_active):
        raise HTTPException(status_code=404, detail="stream tidak ditemukan")
    return stream


@router.get("/streams", response_model=list[StreamOut], dependencies=[Depends(rate_limited(60, 60))])
async def list_streams(
    user: User = Depends(require_roles("admin", "user", "guest")),
    db: AsyncSession = Depends(get_db),
    page: int | None = Query(None, ge=1, description="v2.0: halaman"),
    limit: int | None = Query(None, ge=1, le=500, description="v2.0: batas"),
    group: str | None = Query(None, description="v2.0: filter nama grup (persis)"),
    no_check: bool = Query(False, description="v2.0: lewati cek status"),
    response: Response = None,
):
    """Daftar stream yang terlihat user.

    Tanpa ?page=/?limit= -> list penuh (perilaku v3.0 sekarang).
    Dengan salah satunya -> paginasi (limit default 20 bila hanya page dipakai).
    ?group= menyaring nama grup persis (v2.0). ?no_check= diterima untuk
    kompatibilitas v2.0; status online di v3.0 berasal dari poller latar.
    6.11: paginasi di level SQL (LIMIT/OFFSET + COUNT), total lewat
    header X-Total-Count seperti admin_keys.list_logs; sebelumnya
    _visible_streams memuat semua kamera lalu slice Python, jadi
    ?page=/?limit= tidak menghemat query DB sama sekali.
    """
    settings = get_settings()
    streams, total = await _visible_streams_paged(
        user, db, group=group, page=page, limit=limit
    )
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    return [stream_to_out(s, settings) for s in streams]


# A-1.3: reconnect adalah aksi kelola (hapus + daftar ulang path MediaMTX),
# bukan aksi lihat. Dependency lama (require_roles + require_camera_access)
# mengizinkan siapa pun yang bisa melihat kamera, termasuk user can_view.
# Kini hanya super_admin atau pemilik kamera (created_by/owner_id).
# Flag grant can_manage tidak dipakai sebagai kriteria: ia sudah tidak
# dipakai sejak v2.0 dan tertulis True di semua grant, jadi tidak
# membedakan apa pun; kepemilikan adalah kriteria seperti A-T2.
async def _require_reconnect_access(
    stream_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Stream:
    stream = await _get_stream_or_404(db, stream_id)
    if is_super_admin(user):
        return stream
    if stream.created_by == user.id or stream.owner_id == user.id:
        return stream
    raise HTTPException(
        status_code=403,
        detail="reconnect hanya untuk super_admin atau pemilik kamera",
    )


@router.post("/streams/{stream_id}/reconnect", dependencies=[Depends(rate_limited(10, 60))])
async def reconnect_stream(
    stream_id: int,
    stream: Stream = Depends(_require_reconnect_access),
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_dep),
):
    """Hapus + daftarkan ulang path MediaMTX dari main_url/sub_url tersimpan."""
    from app.services.disks import record_path_for
    from app.services.stream_paths import register_stream

    # Pertahankan flag record: tanpa ini rekaman per kamera mati senyap.
    record = bool(stream.recording_enabled)
    try:
        await mediamtx.delete_path(f"stream_{stream_id}")
        await mediamtx.delete_path(f"stream_{stream_id}_sub")
        source = stream.main_url or stream.rtsp_url
        if source:
            await register_stream(
                mediamtx, stream_id, source, record,
                retention_days=stream.retention_days,
                record_path=record_path_for(
                    stream, get_settings().recordings_dir
                ),
                sub_source=stream.sub_url,
            )
    except Exception as e:  # noqa: BLE001 - semua kegagalan MediaMTX -> 502, bukan 500
        # T-4: pesan error MediaMTX bisa memuat source URL berkredensial.
        err = redact_url_credentials(str(e))
        log.warning("reconnect stream %s gagal: %s", stream_id, err)
        raise HTTPException(status_code=502, detail=f"MediaMTX tidak terjangkau: {err}")
    return {"ok": True}


@router.get("/posters/stream_{stream_id}.jpg")
async def get_poster(
    stream_id: int,
    _access: User = Depends(require_camera_access),
):
    # 4.5: token HANYA via header Authorization. Sebelumnya ?token=
    # diterima di sini, sehingga JWT akses penuh masuk URL gambar dan
    # tercatat di log akses Apache + history browser. Frontend sudah
    # mengambil poster lewat apiFetch (header) sebagai blob sejak lama,
    # jadi tidak ada pemakai ?token= yang tersisa (cek: tidak ada
    # "?token=" untuk poster di apps/web). WS tetap memakai ?token=
    # karena handshake WebSocket browser tidak bisa mengirim header.
    # TODO Fase 3: worker capture poster otomatis mengisi direktori ini.
    path = Path(get_settings().posters_dir) / f"stream_{stream_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="poster belum tersedia")
    return FileResponse(path, media_type="image/jpeg")
