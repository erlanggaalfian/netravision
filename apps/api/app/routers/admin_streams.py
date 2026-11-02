"""Router admin: CRUD stream, sharing, owner, grup, scan, disk.

Semua endpoint butuh peran admin. Path /api/* persis v2.0.
"""

import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.core.rbac import get_current_user, mask_rtsp_url, require_roles
from app.db.session import get_db
from app.models.access import StreamPermission, UserStreamAccess
from app.models.groups import GroupStream, StreamGroup
from app.models.streams import Stream
from app.models.users import User
from app.routers.streams import _get_stream_or_404, stream_to_out
from app.schemas.stream import (
    GroupCreate,
    GroupOut,
    OwnerIn,
    PreviewIn,
    ScanCandidate,
    ScanRequest,
    ScanResult,
    StreamCreate,
    StreamIdsIn,
    StreamOut,
    StreamUpdate,
    UserIdsIn,
)
from app.services.mediamtx import MediaMTXClient, get_mediamtx
from app.services.stream_resolver import resolve_stream

router = APIRouter(tags=["admin-streams"], dependencies=[Depends(require_roles("admin"))])
log = logging.getLogger("netravision.admin_streams")

# Brand yang dicoba saat scan "auto" (semua terdaftar di app/services/brands.py).
_AUTO_BRANDS = ["hikvision", "dahua", "uniview_ipc", "tplink_vigi", "reolink"]


async def _register_paths(
    mediamtx: MediaMTXClient, stream_id: int, main_url: str, sub_url: str | None
) -> None:
    """Daftarkan path ke MediaMTX (best-effort: warning bila down)."""
    try:
        await mediamtx.create_path(f"stream_{stream_id}", main_url)
        if sub_url:
            await mediamtx.create_path(f"stream_{stream_id}_sub", sub_url)
    except Exception as e:  # noqa: BLE001 - best-effort, jangan gagalkan tambah kamera
        log.warning("MediaMTX tidak terjangkau (stream %s): %s", stream_id, e)


@router.get("/admin/streams", response_model=list[StreamOut])
async def admin_list_streams(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    settings = get_settings()
    result = await db.execute(select(Stream).order_by(Stream.id))
    out = []
    for s in result.scalars().all():
        o = stream_to_out(s, settings)
        o.rtsp_url = await mask_rtsp_url(s, admin, db)
        out.append(o)
    return out


@router.post("/admin/streams", response_model=StreamOut, status_code=201)
async def admin_create_stream(
    data: StreamCreate,
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx),
    admin: User = Depends(get_current_user),
):
    try:
        res = await resolve_stream(
            brand=data.brand, rtsp_url=data.rtsp_url, user=data.user,
            password=data.password, host=data.host, port=data.port,
            channel=data.channel,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # TODO Fase 2: simpan data.onvif (profile token) ke streams.onvif_profile
    # bila resolver sudah mengembalikannya.
    stream = Stream(
        name=data.name,
        rtsp_url=data.rtsp_url or res.main_url,
        brand=res.brand,
        main_url=res.main_url,
        sub_url=res.sub_url,
        storage_mode=data.storage_mode,
        recording_enabled=data.recording_enabled,
        retention_days=data.retention_days,
        latitude=data.latitude,
        longitude=data.longitude,
        created_by=admin.id,
    )
    db.add(stream)
    await db.commit()
    await db.refresh(stream)
    await _register_paths(mediamtx, stream.id, res.main_url, res.sub_url)
    return stream_to_out(stream, get_settings())


@router.put("/admin/streams/{stream_id}", response_model=StreamOut)
async def admin_update_stream(
    stream_id: int, data: StreamUpdate, db: AsyncSession = Depends(get_db)
):
    stream = await _get_stream_or_404(db, stream_id)
    if data.name is not None:
        stream.name = data.name
    if data.is_active is not None:
        stream.is_active = data.is_active
    if data.storage_mode is not None:
        stream.storage_mode = data.storage_mode
    if "drive_account_id" in data.model_fields_set:
        if data.drive_account_id is not None:
            from app.models.drive import DriveAccount

            acc = await db.get(DriveAccount, data.drive_account_id)
            if acc is None:
                raise HTTPException(
                    status_code=404, detail="akun Drive tidak ditemukan"
                )
        stream.drive_account_id = data.drive_account_id
    if "drive_folder_id" in data.model_fields_set:
        if data.drive_folder_id is not None:
            from app.models.drive import GoogleDriveFolder

            fol = await db.get(GoogleDriveFolder, data.drive_folder_id)
            if fol is None:
                raise HTTPException(
                    status_code=404, detail="folder Drive tidak ditemukan"
                )
        stream.drive_folder_id = data.drive_folder_id
    if data.latitude is not None:
        stream.latitude = data.latitude
    if data.longitude is not None:
        stream.longitude = data.longitude
    if data.recording_enabled is not None:
        stream.recording_enabled = data.recording_enabled
    if data.retention_days is not None:
        stream.retention_days = data.retention_days
    await db.commit()
    await db.refresh(stream)
    return stream_to_out(stream, get_settings())


@router.delete("/admin/streams/{stream_id}")
async def admin_delete_stream(
    stream_id: int,
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx),
):
    stream = await _get_stream_or_404(db, stream_id)
    try:
        await mediamtx.delete_path(f"stream_{stream_id}")
        await mediamtx.delete_path(f"stream_{stream_id}_sub")
    except Exception as e:  # noqa: BLE001 - best-effort, jangan gagalkan hapus kamera
        log.warning("hapus path MediaMTX stream %s gagal: %s", stream_id, e)
    await db.delete(stream)
    await db.commit()
    return {"ok": True}


@router.get("/admin/streams/{stream_id}/sharing")
async def get_sharing(stream_id: int, db: AsyncSession = Depends(get_db)):
    await _get_stream_or_404(db, stream_id)
    result = await db.execute(
        select(UserStreamAccess.user_id).where(
            UserStreamAccess.stream_id == stream_id,
            UserStreamAccess.can_view.is_(True),
        )
    )
    return {"user_ids": list(result.scalars().all())}


@router.post("/admin/streams/{stream_id}/sharing")
async def set_sharing(stream_id: int, data: UserIdsIn, db: AsyncSession = Depends(get_db)):
    await _get_stream_or_404(db, stream_id)
    if data.user_ids:
        result = await db.execute(select(User.id).where(User.id.in_(data.user_ids)))
        found = set(result.scalars().all())
        missing = set(data.user_ids) - found
        if missing:
            raise HTTPException(status_code=400, detail=f"user tidak ada: {sorted(missing)}")
    await db.execute(delete(UserStreamAccess).where(UserStreamAccess.stream_id == stream_id))
    for uid in data.user_ids:
        db.add(UserStreamAccess(user_id=uid, stream_id=stream_id, can_view=True))
    await db.commit()
    return {"ok": True, "user_ids": data.user_ids}


@router.post("/admin/streams/{stream_id}/owner")
async def set_owner(stream_id: int, data: OwnerIn, db: AsyncSession = Depends(get_db)):
    stream = await _get_stream_or_404(db, stream_id)
    user = await db.get(User, data.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user tidak ditemukan")
    stream.owner_id = data.user_id
    await db.commit()
    return {"ok": True, "owner_id": data.user_id}


class RoleAccessIn(BaseModel):
    role: str
    can_view: bool = True
    can_playback: bool = True


@router.put("/admin/streams/{stream_id}/role-access")
async def set_role_access(stream_id: int, data: RoleAccessIn, db: AsyncSession = Depends(get_db)):
    """Kelola akses per peran (mis. role 'guest') untuk satu kamera.

    Paritas v2.0: tamu dapat diberi kamera tertentu satu per satu.
    """
    await _get_stream_or_404(db, stream_id)
    if data.role not in ("admin", "user", "guest"):
        raise HTTPException(status_code=400, detail="role tidak dikenal")
    result = await db.execute(
        select(StreamPermission).where(
            StreamPermission.stream_id == stream_id,
            StreamPermission.role == data.role,
            StreamPermission.user_id.is_(None),
        )
    )
    perm = result.scalars().first()
    if perm is None:
        perm = StreamPermission(
            stream_id=stream_id, role=data.role,
            can_view=data.can_view, can_playback=data.can_playback,
        )
        db.add(perm)
    else:
        perm.can_view = data.can_view
        perm.can_playback = data.can_playback
    await db.commit()
    return {"ok": True, "stream_id": stream_id, "role": data.role,
            "can_view": perm.can_view, "can_playback": perm.can_playback}


@router.get("/admin/streams/{stream_id}/role-access")
async def get_role_access(stream_id: int, db: AsyncSession = Depends(get_db)):
    await _get_stream_or_404(db, stream_id)
    result = await db.execute(
        select(StreamPermission).where(
            StreamPermission.stream_id == stream_id,
            StreamPermission.user_id.is_(None),
        )
    )
    return {
        "roles": [
            {"role": p.role, "can_view": p.can_view, "can_playback": p.can_playback}
            for p in result.scalars().all()
        ]
    }


async def _get_group_or_404(db: AsyncSession, nama_grup: str) -> StreamGroup:
    result = await db.execute(select(StreamGroup).where(StreamGroup.name == nama_grup))
    group = result.scalars().first()
    if group is None:
        raise HTTPException(status_code=404, detail="grup tidak ditemukan")
    return group


@router.get("/admin/groups", response_model=list[GroupOut])
async def list_groups(db: AsyncSession = Depends(get_db)):
    """Daftar semua grup wilayah (tambahan v3.0 untuk halaman admin)."""
    result = await db.execute(select(StreamGroup).order_by(StreamGroup.name))
    return [
        GroupOut(id=g.id, name=g.name, description=g.description)
        for g in result.scalars().all()
    ]


@router.put("/admin/groups/{nama_grup}", response_model=GroupOut)
async def upsert_group(nama_grup: str, data: GroupCreate, db: AsyncSession = Depends(get_db)):
    name = data.name or nama_grup
    result = await db.execute(select(StreamGroup).where(StreamGroup.name == name))
    group = result.scalars().first()
    if group is None:
        group = StreamGroup(name=name, description=data.description)
        db.add(group)
    elif data.description is not None:
        group.description = data.description
    await db.commit()
    await db.refresh(group)
    return GroupOut(id=group.id, name=group.name, description=group.description)


@router.get("/admin/groups/{nama_grup}/camera-grants")
async def get_group_grants(nama_grup: str, db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, nama_grup)
    result = await db.execute(
        select(GroupStream.stream_id).where(GroupStream.group_id == group.id)
    )
    return {"stream_ids": list(result.scalars().all())}


@router.post("/admin/groups/{nama_grup}/camera-grants")
async def set_group_grants(nama_grup: str, data: StreamIdsIn, db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, nama_grup)
    if data.stream_ids:
        result = await db.execute(select(Stream.id).where(Stream.id.in_(data.stream_ids)))
        found = set(result.scalars().all())
        missing = set(data.stream_ids) - found
        if missing:
            raise HTTPException(status_code=400, detail=f"stream tidak ada: {sorted(missing)}")
    await db.execute(delete(GroupStream).where(GroupStream.group_id == group.id))
    for sid in data.stream_ids:
        db.add(GroupStream(group_id=group.id, stream_id=sid))
    await db.commit()
    return {"ok": True, "stream_ids": data.stream_ids}


@router.get("/admin/disks")
async def disk_info(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    target = settings.recordings_dir if Path(settings.recordings_dir).exists() else "/"
    usage = shutil.disk_usage(target)
    out: dict = {
        "path": settings.recordings_dir,
        "measured_on": target,
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
    }

    # Entri Google Drive mode folder-link + rclone (multi-tautan):
    # satu entri per folder yang punya path lokal.
    try:
        from app.models.drive import GoogleDriveFolder

        res = await db.execute(select(GoogleDriveFolder).order_by(GoogleDriveFolder.id))
        folders = res.scalars().all()
    except Exception:  # noqa: BLE001
        folders = []
    gdrive_entries = []
    for fol in folders:
        gdrive_path = ((fol.local_path or "").rstrip("/") or
                       (settings.gdrive_record_path or "").rstrip("/"))
        if not gdrive_path:
            continue
        try:
            os.makedirs(gdrive_path, exist_ok=True)
            quota_tb = settings.gdrive_quota_tb
            total = int(quota_tb * (1024**4))
            used = 0
            for root, _dirs, files in os.walk(gdrive_path):
                for fn in files:
                    try:
                        used += os.path.getsize(os.path.join(root, fn))
                    except OSError:
                        pass
            avail = max(total - used, 0)
            label = f"Google Drive — {fol.folder_name or fol.folder_id}"
            gdrive_entries.append({
                "folder_id": fol.id,
                "mount": gdrive_path,
                "label": label,
                "drive_folder_id": fol.folder_id,
                "drive_folder_name": fol.folder_name or "",
                "drive_folder_url": fol.folder_url or "",
                "storage_type": "google_drive",
                "size_bytes": total,
                "avail_bytes": avail,
                "size_human": f"{quota_tb:g}TB",
                "avail_human": f"{avail / (1024**4):.1f}TB",
                "fstype": "gdrive",
                "usage_pct": round(used / total * 100, 1) if total else 0,
            })
        except Exception as e:  # noqa: BLE001
            log.warning("disk Google Drive gagal: %s", e)
    if gdrive_entries:
        out["google_drive"] = gdrive_entries[0]  # kompatibel lama: satu entri
        out["google_drive_folders"] = gdrive_entries
    return out


@router.post(
    "/admin/scan",
    response_model=ScanResult,
    dependencies=[Depends(rate_limited(10, 60))],
)
async def scan_camera(data: ScanRequest):
    """Coba brand yang diminta; bila 'auto', coba 5 brand umum berurutan.
    Bila rtsp_url diisi, langsung resolve URL tersebut (tanpa host).
    Bila probe=True, tiap kandidat dites koneksi RTSP-nya via DESCRIBE."""
    from app.services.stream_resolver import probe_rtsp

    candidates: list[ScanCandidate] = []
    if data.rtsp_url and data.rtsp_url.strip():
        try:
            res = await resolve_stream(brand=None, rtsp_url=data.rtsp_url.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        candidates.append(
            ScanCandidate(
                main_url=res.main_url, sub_url=res.sub_url,
                brand=res.brand, method=res.method,
            )
        )
    else:
        if not data.host:
            raise HTTPException(
                status_code=400, detail="host wajib diisi bila tanpa URL RTSP langsung"
            )
        brands = [data.brand] if data.brand and data.brand != "auto" else _AUTO_BRANDS
        for brand in brands:
            try:
                res = await resolve_stream(
                    brand=brand, rtsp_url=None, user=data.user,
                    password=data.password, host=data.host, port=data.port,
                    channel=data.channel,
                )
            except ValueError:
                continue
            candidates.append(
                ScanCandidate(
                    main_url=res.main_url, sub_url=res.sub_url,
                    brand=res.brand, method=res.method,
                )
            )
    if not candidates:
        raise HTTPException(status_code=400, detail="tidak ada kandidat stream dari input ini")
    if data.probe:
        for c in candidates:
            main_probe = await probe_rtsp(c.main_url)
            c.main_ok = main_probe.reachable and main_probe.status in ("ok", "auth_required")
            c.probe_status = main_probe.status
            if c.sub_url:
                sub_probe = await probe_rtsp(c.sub_url)
                c.sub_ok = sub_probe.reachable and sub_probe.status in ("ok", "auth_required")
    return ScanResult(candidates=candidates)


@router.post(
    "/admin/scan/preview", dependencies=[Depends(rate_limited(10, 60))]
)
async def scan_preview(data: PreviewIn):
    # TODO Fase 2: frontend memutar URL hasil resolve untuk preview visual
    # sebelum kamera disimpan.
    try:
        res = await resolve_stream(brand=None, rtsp_url=data.rtsp_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"main_url": res.main_url, "sub_url": res.sub_url, "method": res.method}
