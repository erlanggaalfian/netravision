"""Router admin: CRUD stream, sharing, owner, grup, scan, disk.

Semua endpoint butuh peran admin. Path /api/* persis v2.0.
"""

import logging
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.core.rbac import get_current_user, is_super_admin, mask_rtsp_url, require_reshare, require_roles
from app.db.session import get_db
from app.models.access import StreamAdminGrant, StreamPermission, UserStreamAccess
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
    ScanPath,
    ScanRequest,
    ScanResult,
    ShareIn,
    SharingIn,
    StreamCreate,
    StreamIdsIn,
    StreamOut,
    StreamUpdate,
)
from app.services import rtsp_discovery
from app.services.mediamtx import MediaMTXClient, get_mediamtx
from app.services.stream_resolver import StreamResolution, resolve_stream

router = APIRouter(tags=["admin-streams"], dependencies=[Depends(require_roles("admin"))])
log = logging.getLogger("netravision.admin_streams")

# Tambah/ubah/hapus kamera dan pengaturannya hanya superadmin. Admin
# biasa hanya boleh membagikan kamera yang diizinkan (can_reshare)
# ke user di grupnya, lewat endpoint sharing.
super_admin_only = require_roles("super_admin")

# Brand yang dicoba saat scan "auto" (semua terdaftar di app/services/brands.py).
_AUTO_BRANDS = ["hikvision", "dahua", "uniview_ipc", "tplink_vigi", "reolink"]


async def _register_paths(
    mediamtx: MediaMTXClient, stream_id: int, main_url: str, sub_url: str | None,
    record: bool = False,
) -> tuple[bool, str | None]:
    """Daftarkan path ke MediaMTX. Return (ok, pesan_error).

    Kamera tetap disimpan ke DB walau gagal — dengan sync berkala (poin 3
    laporan staging), path akan terdaftar sendiri begitu MediaMTX pulih.
    """
    from app.services.stream_paths import register_stream

    try:
        # Pola v2: sub = transkode dari main (sub_url kamera tidak ditarik).
        await register_stream(mediamtx, stream_id, main_url, record)
        return True, None
    except Exception as e:  # noqa: BLE001 - best-effort, jangan gagalkan tambah kamera
        msg = f"MediaMTX tidak terjangkau (stream {stream_id}): {e}"
        log.warning(msg)
        return False, str(e)


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


@router.post("/admin/streams", response_model=StreamOut, status_code=201, dependencies=[Depends(super_admin_only)])
async def admin_create_stream(
    data: StreamCreate,
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx),
    admin: User = Depends(get_current_user),
):
    if data.rtsp_url:
        # URL langsung: verifikasi video dulu (kecuali force).
        try:
            res = await resolve_stream(
                brand=data.brand, rtsp_url=data.rtsp_url, user=data.user,
                password=data.password, host=data.host, port=data.port,
                channel=data.channel,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not data.force:
            vp = await rtsp_discovery.verify_url(data.rtsp_url)
            if vp.status != "video":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"URL tidak mengirim video ({vp.status}). Perbaiki URL, "
                        "atau kirim force=true untuk tetap mendaftar."
                    ),
                )
    elif data.host and not data.force:
        # Tanpa URL: discovery otomatis, pakai path video terbaik.
        disc = await rtsp_discovery.discover_host(
            data.host, data.port, data.user, data.password, data.channel
        )
        if not disc.best_main:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Tidak ada path yang mengirim video ("
                    f"{disc.ringkasan()}). Periksa kredensial/path, atau kirim "
                    "force=true beserta brand untuk tetap mendaftar."
                ),
            )
        res = StreamResolution(
            main_url=disc.best_main,
            sub_url=disc.best_sub,
            brand=data.brand if data.brand and data.brand != "auto" else "generic",
            method="discovery",
        )
    else:
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
    ok, err = await _register_paths(mediamtx, stream.id, res.main_url, res.sub_url,
                                    record=data.recording_enabled)
    out = stream_to_out(stream, get_settings())
    # Status registrasi MediaMTX dikembalikan ke UI (bukan 500, bukan diam).
    out_dict = out.model_dump()
    out_dict["mediamtx_registered"] = ok
    out_dict["mediamtx_error"] = err
    return out_dict


@router.put("/admin/streams/{stream_id}", response_model=StreamOut, dependencies=[Depends(super_admin_only)])
async def admin_update_stream(
    stream_id: int, data: StreamUpdate,
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx),
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
        # Sinkronkan flag record di MediaMTX (best-effort).
        try:
            # Hanya main yang direkam (sub = transkode 480p, sama seperti v2).
            await mediamtx.patch_path(
                f"stream_{stream_id}", {"record": data.recording_enabled})
        except Exception as e:  # noqa: BLE001
            log.warning("patch record MediaMTX stream %s gagal: %s", stream_id, e)
    if data.retention_days is not None:
        stream.retention_days = data.retention_days
    await db.commit()
    await db.refresh(stream)
    return stream_to_out(stream, get_settings())


@router.delete("/admin/streams/{stream_id}", dependencies=[Depends(super_admin_only)])
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
        select(UserStreamAccess).where(
            UserStreamAccess.stream_id == stream_id,
            UserStreamAccess.can_view.is_(True),
        )
    )
    rows = result.scalars().all()
    shares = [
        {"user_id": r.user_id, "can_playback": bool(r.can_playback)} for r in rows
    ]
    return {
        "user_ids": [s["user_id"] for s in shares],
        "shares": shares,
    }


@router.post("/admin/streams/{stream_id}/sharing")
async def set_sharing(
    stream_id: int,
    data: SharingIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _get_stream_or_404(db, stream_id)
    # Normalisasi: bentuk baru (shares) menang; bentuk lama (user_ids)
    # dianggap can_playback=True.
    shares = list(data.shares)
    if not shares and data.user_ids:
        shares = [ShareIn(user_id=uid) for uid in data.user_ids]
    # Admin yang membagikan wajib punya can_reshare atas kameranya;
    # bila share mencakup playback, wajib punya can_playback juga.
    for s in shares:
        await require_reshare(me, db, stream_id, need_playback=s.can_playback)
    user_ids = [s.user_id for s in shares]
    if user_ids:
        result = await db.execute(select(User.id).where(User.id.in_(user_ids)))
        found = set(result.scalars().all())
        missing = set(user_ids) - found
        if missing:
            raise HTTPException(status_code=400, detail=f"user tidak ada: {sorted(missing)}")
    # Cakupan admin biasa: hanya boleh membagikan ke user/guest di
    # grupnya sendiri, bukan ke diri sendiri. Admin dikelola oleh
    # superadmin (lewat grant), bukan lewat Bagikan. Superadmin boleh
    # ke semua dan tetap mengganti semua baris (perilaku lama).
    if is_super_admin(me):
        await db.execute(delete(UserStreamAccess).where(UserStreamAccess.stream_id == stream_id))
    else:
        grup = (me.admin_group or "").strip()
        manageable: set[int] = set()
        if grup:
            result = await db.execute(
                select(User.id).where(
                    User.admin_group == grup,
                    User.role.in_(["user", "guest"]),
                    User.id != me.id,
                )
            )
            manageable = set(result.scalars().all())
        for s in shares:
            if s.user_id not in manageable:
                raise HTTPException(
                    status_code=400,
                    detail="hanya boleh membagikan ke user di grup Anda",
                )
        # Hapus hanya baris yang boleh dikelola actor; baris superadmin,
        # admin lain, user grup lain, dan diri sendiri dipertahankan.
        if manageable:
            await db.execute(
                delete(UserStreamAccess).where(
                    UserStreamAccess.stream_id == stream_id,
                    UserStreamAccess.user_id.in_(manageable),
                )
            )
    for s in shares:
        db.add(
            UserStreamAccess(
                user_id=s.user_id,
                stream_id=stream_id,
                can_view=True,
                can_playback=s.can_playback,
            )
        )
    await db.commit()
    return {"ok": True, "user_ids": user_ids}


@router.get("/admin/streams/{stream_id}/grants")
async def get_stream_grants(stream_id: int, db: AsyncSession = Depends(get_db)):
    """Grant admin untuk satu kamera (dipakai modal Bagikan)."""
    await _get_stream_or_404(db, stream_id)
    result = await db.execute(
        select(StreamAdminGrant).where(StreamAdminGrant.stream_id == stream_id)
    )
    return {
        "grants": [
            {
                "admin_id": g.admin_id,
                "can_view": bool(g.can_view),
                "can_playback": bool(g.can_playback),
                "can_reshare": bool(g.can_reshare),
            }
            for g in result.scalars().all()
        ]
    }


class StreamGrantIn(BaseModel):
    admin_id: int
    can_view: bool = True
    can_playback: bool = False
    can_reshare: bool = False


class StreamGrantsIn(BaseModel):
    grants: list[StreamGrantIn] = []


@router.post("/admin/streams/{stream_id}/grants", dependencies=[Depends(super_admin_only)])
async def set_stream_grants(
    stream_id: int, data: StreamGrantsIn, db: AsyncSession = Depends(get_db)
):
    """Upsert grant admin untuk satu kamera (dipakai modal Bagikan).

    Baris yang belum ada dibuat; yang sudah ada hanya diubah flag-nya.
    can_reshare=True memaksa can_view=True (membagikan butuh live).
    """
    await _get_stream_or_404(db, stream_id)
    for g in data.grants:
        user = await db.get(User, g.admin_id)
        if user is None:
            raise HTTPException(
                status_code=400, detail=f"user tidak ada: {g.admin_id}"
            )
        row = (
            (
                await db.execute(
                    select(StreamAdminGrant).where(
                        StreamAdminGrant.stream_id == stream_id,
                        StreamAdminGrant.admin_id == g.admin_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        can_view = g.can_view or g.can_reshare
        if not can_view and not g.can_playback:
            # Kamera tanpa live maupun rekaman berarti tidak diberikan
            # sama sekali (paritas v2.0): hapus barisnya bila ada.
            if row is not None:
                await db.delete(row)
            continue
        if row is None:
            db.add(
                StreamAdminGrant(
                    admin_id=g.admin_id,
                    stream_id=stream_id,
                    can_manage=True,
                    can_view=can_view,
                    can_playback=g.can_playback,
                    can_reshare=g.can_reshare,
                )
            )
        else:
            row.can_view = can_view
            row.can_playback = g.can_playback
            row.can_reshare = g.can_reshare
    await db.commit()
    return {"ok": True}


@router.post("/admin/streams/{stream_id}/owner", dependencies=[Depends(super_admin_only)])
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


@router.put("/admin/streams/{stream_id}/role-access", dependencies=[Depends(super_admin_only)])
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


@router.put("/admin/groups/{nama_grup}", response_model=GroupOut, dependencies=[Depends(super_admin_only)])
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


@router.post("/admin/groups/{nama_grup}/camera-grants", dependencies=[Depends(super_admin_only)])
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


def _to_scan_path(p: rtsp_discovery.PathResult, role: str | None) -> ScanPath:
    return ScanPath(
        path=p.path, url=p.url, status=p.status, codec=p.codec,
        width=p.width, height=p.height, fps=p.fps,
        gop_seconds=p.gop_seconds, role=role,
    )


@router.post(
    "/admin/scan",
    response_model=ScanResult,
    dependencies=[Depends(rate_limited(10, 60))],
)
async def scan_camera(data: ScanRequest):
    """Scan kamera dengan verifikasi video (ffprobe), bukan sekadar port/401.

    - rtsp_url diisi: verifikasi URL itu langsung.
    - host diisi: discovery path RTSP umum + template brand, tiap path yang
      DESCRIBE-nya OK diverifikasi benar-benar mengirim video, lalu main/sub
      dipilih otomatis (resolusi terbesar / terkecil).
    Field lama (candidates/main_ok/sub_ok/probe_status) tetap dikembalikan.
    """
    candidates: list[ScanCandidate] = []
    paths: list[ScanPath] = []
    best_main: str | None = None
    best_sub: str | None = None

    if data.rtsp_url and data.rtsp_url.strip():
        url = data.rtsp_url.strip()
        res = await resolve_stream(brand=None, rtsp_url=url)
        cand = ScanCandidate(
            main_url=res.main_url, sub_url=res.sub_url,
            brand=res.brand, method=res.method,
        )
        candidates.append(cand)
        if data.probe:
            vp = await rtsp_discovery.verify_url(url)
            path = urlparse(url).path or "/"
            if urlparse(url).query:
                path += "?" + urlparse(url).query
            pr = rtsp_discovery.PathResult(
                path=path, url=url, status=vp.status, codec=vp.codec,
                width=vp.width, height=vp.height, fps=vp.fps,
                gop_seconds=vp.gop_seconds,
            )
            role = "main" if vp.status == "video" else None
            paths.append(_to_scan_path(pr, role))
            cand.main_ok = vp.status == "video"
            cand.probe_status = vp.status
            best_main = url if vp.status == "video" else None
        return ScanResult(
            candidates=candidates, paths=paths,
            best_main=best_main, best_sub=None,
        )

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
        disc = await rtsp_discovery.discover_host(
            data.host, data.port, data.user, data.password, data.channel
        )
        best_main, best_sub = disc.best_main, disc.best_sub
        by_path = {p.path: p for p in disc.paths}
        paths = [
            _to_scan_path(
                p,
                "main" if p.url == best_main
                else ("sub" if p.url == best_sub else None),
            )
            for p in disc.paths
        ]
        for c in candidates:
            for url, is_main in ((c.main_url, True), (c.sub_url, False)):
                if not url:
                    continue
                u = urlparse(url)
                key = u.path + (f"?{u.query}" if u.query else "")
                pr = by_path.get(key)
                if pr is None:
                    continue
                if is_main:
                    c.main_ok = pr.status == "video"
                    c.probe_status = pr.status
                else:
                    c.sub_ok = pr.status == "video"
    return ScanResult(
        candidates=candidates, paths=paths,
        best_main=best_main, best_sub=best_sub,
    )


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
