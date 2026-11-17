"""Router admin: CRUD stream, sharing, owner, grup, scan, disk.

Semua endpoint butuh peran admin. Path /api/* persis v2.0.
"""

import asyncio
import logging
import os
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.core.rbac import get_current_user, is_super_admin, require_reshare, require_roles
from app.core.security import redact_url_credentials
from app.db.session import get_db
from app.services import scan_vault
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
from app.services.mediamtx import MediaMTXClient, get_mediamtx_dep
from app.services.stream_resolver import StreamResolution, resolve_stream

router = APIRouter(
    tags=["admin-streams"],
    # 4.7: seluruh router ini sebelumnya tanpa rate limit (kecuali
    # /admin/scan): daftar kamera, sharing, grants, groups, dan
    # disk-summary bisa dibanjiri. 20/menit per IP seperti router admin
    # lain; endpoint scan yang mahal tetap punya batas sendiri (10/menit).
    dependencies=[Depends(require_roles("admin")), Depends(rate_limited(20, 60))],
)
log = logging.getLogger("netravision.admin_streams")

# Tambah/ubah/hapus kamera dan pengaturannya hanya superadmin. Admin
# biasa hanya boleh membagikan kamera yang diizinkan (can_reshare)
# ke user di grupnya, lewat endpoint sharing.
super_admin_only = require_roles("super_admin")

# Brand yang dicoba saat scan "auto" (semua terdaftar di app/services/brands.py).
_AUTO_BRANDS = ["hikvision", "dahua", "uniview_ipc", "tplink_vigi", "reolink"]


async def _admin_may_see_stream(me: User, db: AsyncSession, stream_id: int) -> bool:
    """Bolehkah admin biasa membaca sharing/grant/role-access satu kamera?

    A-S7: super_admin boleh semua; admin biasa hanya bila punya grant
    atas kamera itu atau kamera itu miliknya (dipasang/dimiliki).
    """
    if is_super_admin(me):
        return True
    grant = (
        (await db.execute(
            select(StreamAdminGrant).where(
                StreamAdminGrant.stream_id == stream_id,
                StreamAdminGrant.admin_id == me.id,
            )
        ))
        .scalars()
        .first()
    )
    if grant is not None:
        return True
    stream = await db.get(Stream, stream_id)
    if stream is None:
        return False
    # Pemilik = pemasang ATAU pemilik, periksa terpisah (pola
    # `created_by or owner_id` salah bila created_by orang lain).
    return (
        getattr(stream, "created_by", None) == me.id
        or getattr(stream, "owner_id", None) == me.id
    )


async def _register_paths(
    mediamtx: MediaMTXClient, stream_id: int, main_url: str, sub_url: str | None,
    record: bool = False, stream: Stream | None = None,
    retention_days: int | None = None,
) -> tuple[bool, str | None]:
    """Daftarkan path ke MediaMTX. Return (ok, pesan_error).

    Kamera tetap disimpan ke DB walau gagal, dengan sync berkala (poin 3
    laporan staging), path akan terdaftar sendiri begitu MediaMTX pulih.
    Bila `stream` diberikan, recordPath multi-disk (record_path_for) dan
    retention_days diambil dari stream itu.
    """
    from app.services.disks import record_path_for
    from app.services.stream_paths import register_stream

    try:
        # Sub HANYA dari sub_url asli kamera (native). Bila tidak ada
        # sub_url, register_stream tidak membuat path sub sama sekali
        # (transcoder mati total, perintah user 2026-11-14).
        record_path = (
            record_path_for(stream, get_settings().recordings_dir)
            if stream is not None
            else None
        )
        days = retention_days
        if days is None and stream is not None:
            days = stream.retention_days
        await register_stream(
            mediamtx, stream_id, main_url, record,
            retention_days=days, record_path=record_path,
            sub_source=sub_url,
        )
        return True, None
    except Exception as e:  # noqa: BLE001 - best-effort, jangan gagalkan tambah kamera
        msg = f"MediaMTX tidak terjangkau (stream {stream_id}): {e}"
        log.warning(msg)
        return False, str(e)


async def _refresh_stream_group_names(
    db: AsyncSession, stream_ids: set[int] | list[int],
) -> None:
    """Set stream.group_name = nama grup pertama (alfabet) tiap stream.

    Dipakai setelah keanggotaan grup berubah. group_name dipakai sebagai
    bagian path rekaman multi-disk (camera_rec_base), jadi harus selaras
    dengan tabel group_streams; None bila stream tidak punya grup.
    """
    for sid in sorted(set(stream_ids)):
        stream = await db.get(Stream, sid)
        if stream is None:
            continue
        res = await db.execute(
            select(StreamGroup.name)
            .join(GroupStream, GroupStream.group_id == StreamGroup.id)
            .where(GroupStream.stream_id == sid)
            .order_by(StreamGroup.name)
        )
        names = res.scalars().all()
        stream.group_name = names[0] if names else None


async def _admin_visible_stream_ids(me: User, db: AsyncSession) -> set[int] | None:
    """Id kamera yang boleh dilihat admin biasa (milik + grant).

    None = tanpa filter (super_admin melihat semua). Dipakai konsisten
    di daftar kamera, daftar grup, dan grant grup, supaya admin tidak
    bisa mengenumerasi kamera/grup milik grup lain lewat endpoint
    daftar sekalipun detail per kamera sudah digerbangi
    _admin_may_see_stream.
    """
    if is_super_admin(me):
        return None
    allowed: set[int] = set()
    rows = await db.execute(
        select(Stream.id, Stream.created_by, Stream.owner_id)
    )
    for sid, created_by, owner_id in rows.all():
        if created_by == me.id or owner_id == me.id:
            allowed.add(sid)
    grant_rows = await db.execute(
        select(StreamAdminGrant.stream_id).where(
            StreamAdminGrant.admin_id == me.id
        )
    )
    allowed.update(grant_rows.scalars().all())
    return allowed


async def _mask_rtsp_urls(
    streams: list[Stream], admin: User, db: AsyncSession
) -> dict[int, str]:
    """Batch dari mask_rtsp_url (rbac): rtsp_url per kamera, "" bila
    admin tidak berhak melihatnya.

    A-1.12: satu query grant (IN admin) untuk semua kamera, bukan
    satu query per kamera di loop daftar. Semantik sama: super_admin
    melihat semua; admin hanya kamera miliknya (created_by/owner_id)
    atau yang di-grant can_view; peran lain tidak melihat apa pun.
    """
    if is_super_admin(admin):
        return {s.id: (getattr(s, "rtsp_url", "") or "") for s in streams}
    if (getattr(admin, "role", "") or "") != "admin":
        return {s.id: "" for s in streams}
    granted = set(
        (
            await db.execute(
                select(StreamAdminGrant.stream_id).where(
                    StreamAdminGrant.admin_id == admin.id,
                    StreamAdminGrant.can_view.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    out: dict[int, str] = {}
    for s in streams:
        if (
            getattr(s, "created_by", None) == admin.id
            or getattr(s, "owner_id", None) == admin.id
            or s.id in granted
        ):
            out[s.id] = getattr(s, "rtsp_url", "") or ""
        else:
            out[s.id] = ""
    return out


@router.get("/admin/streams", response_model=list[StreamOut])
async def admin_list_streams(
    response: Response,
    limit: int | None = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """Daftar kamera (admin).

    6.11: paginasi SQL opsional (?limit=&offset=, total di header
    X-Total-Count seperti admin_keys). Tanpa limit, perilaku lama
    (daftar penuh) dipertahankan. Untuk super_admin (tanpa filter
    visibilitas) paginasi terjadi di SQL; untuk admin biasa filter
    visibilitas tetap di Python (grant) lalu dipotong di Python,
    supaya tidak ada kamera yang hilang dari halaman.
    """
    settings = get_settings()
    visible = await _admin_visible_stream_ids(admin, db)
    if visible is None and limit is not None:
        # super_admin: paginasi di SQL (tanpa muat seluruh tabel).
        total = (
            await db.execute(select(func.count()).select_from(Stream))
        ).scalar() or 0
        response.headers["X-Total-Count"] = str(total)
        result = await db.execute(
            select(Stream).order_by(Stream.id).limit(limit).offset(offset)
        )
        streams = result.scalars().all()
    else:
        result = await db.execute(select(Stream).order_by(Stream.id))
        streams = result.scalars().all()
        if visible is not None:
            # Admin biasa: filter visibilitas (grant) di Python lalu
            # potong di Python, supaya tidak ada kamera yang hilang
            # dari halaman karena LIMIT diterapkan sebelum filter.
            streams = [s for s in streams if s.id in visible]
        if limit is not None:
            response.headers["X-Total-Count"] = str(len(streams))
            streams = streams[offset : offset + limit]
    # A-1.12: mask RTSP diambil sekali (batch), bukan satu query
    # grant per kamera di loop.
    masked = await _mask_rtsp_urls(streams, admin, db)
    out = []
    for s in streams:
        o = stream_to_out(s, settings)
        o.rtsp_url = masked.get(s.id, "")
        # T-4: URL RTSP dikembalikan dengan password teredaksi (****),
        # bukan mentah. Frontend menampilkan **** dan mengirim ****
        # kembali; backend memulihkan password tersimpan
        # (resolve_url_password), jadi alur Ubah Kamera tetap jalan
        # tanpa password mentah di respons, log akses, atau riwayat.
        if o.rtsp_url:
            o.rtsp_url = redact_url_credentials(o.rtsp_url)
            o.main_url = redact_url_credentials(s.main_url) or None
            o.sub_url = redact_url_credentials(s.sub_url) or None
        out.append(o)
    return out


def _validate_record_disk(value: str | None) -> str | None:
    """Normalisasi + validasi record_disk: "" sama dengan None (default).

    Bila terisi, harus path absolut ke direktori yang ada; bila tidak,
    400 dengan pesan jelas."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not os.path.isabs(value):
        raise HTTPException(
            status_code=400,
            detail=f"record_disk harus path absolut, bukan {value!r}",
        )
    if not os.path.isdir(value):
        raise HTTPException(
            status_code=400,
            detail=f"direktori record_disk tidak ada: {value}",
        )
    return value


def _resolve_scan_url(url: str | None, scan_ref: str | None) -> str | None:
    """Pulihkan URL asli dari URL teredaksi hasil scan (4.6).

    URL dengan password **** hanya sah bila scan_ref menunjuk ke
    brankas yang masih menyimpan URL aslinya; tanpa itu, 400 (password
    **** tidak boleh tersimpan secara harfiah sebagai password kamera).
    URL tanpa mask diteruskan apa adanya.
    """
    if not url or ":****@" not in url:
        return url
    real = scan_vault.resolve(scan_ref, url)
    if real is None:
        raise HTTPException(
            status_code=400,
            detail="URL hasil scan kedaluwarsa atau tidak dikenal, scan ulang",
        )
    return real


@router.post("/admin/streams", response_model=StreamOut, status_code=201, dependencies=[Depends(super_admin_only)])
async def admin_create_stream(
    data: StreamCreate,
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_dep),
    admin: User = Depends(get_current_user),
):
    record_disk = _validate_record_disk(data.record_disk)
    # 4.6: URL teredaksi (****) dari hasil scan dipulihkan dari brankas
    # server lewat scan_ref; tanpa scan_ref yang sah, 400 di sini.
    rtsp_url = _resolve_scan_url(data.rtsp_url, data.scan_ref)
    sub_url = _resolve_scan_url(data.sub_url, data.scan_ref)
    if rtsp_url:
        # URL langsung: verifikasi video dulu (kecuali force).
        try:
            res = await resolve_stream(
                brand=data.brand, rtsp_url=rtsp_url, user=data.user,
                password=data.password, host=data.host, port=data.port,
                channel=data.channel,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not data.force:
            vp = await rtsp_discovery.verify_url(rtsp_url)
            if vp.status != "video":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"URL tidak mengirim video ({vp.status}). Perbaiki URL, "
                        "atau kirim force=true untuk tetap mendaftar."
                    ),
                )
            # A-1.27: sub_url eksplisit juga diverifikasi bila
            # force=False; sebelumnya hanya rtsp_url yang dicek
            # sehingga kamera bisa tersimpan dengan sub mati tanpa
            # peringatan (sub hasil Scanner umumnya sudah terverifikasi,
            # tapi sub yang diketik manual belum tentu).
            if sub_url:
                vs = await rtsp_discovery.verify_url(sub_url)
                if vs.status != "video":
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Substream tidak mengirim video "
                            f"({vs.status}). Perbaiki URL sub, atau kirim "
                            "force=true untuk tetap mendaftar."
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
                brand=data.brand, rtsp_url=rtsp_url, user=data.user,
                password=data.password, host=data.host, port=data.port,
                channel=data.channel,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    # TODO Fase 2: simpan data.onvif (profile token) ke streams.onvif_profile
    # bila resolver sudah mengembalikannya.
    # sub_url eksplisit (best_sub terverifikasi dari Scanner) lebih
    # diutamakan daripada turunan resolver; bila tidak diisi, pakai
    # turunan resolver seperti biasa.
    effective_sub = sub_url or res.sub_url
    stream = Stream(
        name=data.name,
        rtsp_url=rtsp_url or res.main_url,
        brand=res.brand,
        main_url=res.main_url,
        sub_url=effective_sub,
        storage_mode=data.storage_mode,
        recording_enabled=data.recording_enabled,
        is_active=data.is_active,
        retention_days=data.retention_days,
        record_disk=record_disk,
        latitude=data.latitude,
        longitude=data.longitude,
        created_by=admin.id,
    )
    db.add(stream)
    await db.commit()
    await db.refresh(stream)
    # Kamera nonaktif: path MediaMTX sengaja tidak didaftarkan (sync
    # berkala hanya mendaftarkan kamera aktif); mediamtx_registered
    # tetap True supaya UI tidak menampilkan peringatan gagal yang
    # menyesatkan, karena ini bukan kegagalan.
    if data.is_active:
        ok, err = await _register_paths(mediamtx, stream.id, res.main_url, effective_sub,
                                        record=data.recording_enabled, stream=stream)
    else:
        ok, err = True, None
    out = stream_to_out(stream, get_settings())
    # Status registrasi MediaMTX dikembalikan ke UI (bukan 500, bukan diam).
    # A-S2: field ini bagian dari StreamOut supaya tidak dipangkas response_model.
    out.mediamtx_registered = ok
    out.mediamtx_error = err
    return out


@router.put("/admin/streams/{stream_id}", response_model=StreamOut, dependencies=[Depends(super_admin_only)])
async def admin_update_stream(
    stream_id: int, data: StreamUpdate,
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_dep),
):
    stream = await _get_stream_or_404(db, stream_id, require_active=False)
    was_active = stream.is_active
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
    # A-1.20: null eksplisit dihormati (hapus koordinat), pola yang
    # sama seperti drive_account_id/drive_folder_id di atas; sebelumnya
    # `if ... is not None` mengabaikan null diam-diam.
    if "latitude" in data.model_fields_set:
        stream.latitude = data.latitude
    if "longitude" in data.model_fields_set:
        stream.longitude = data.longitude
    if data.recording_enabled is not None:
        recording_changed = data.recording_enabled != stream.recording_enabled
        stream.recording_enabled = data.recording_enabled
    else:
        recording_changed = False
    retention_changed = (
        data.retention_days is not None
        and data.retention_days != stream.retention_days
    )
    if data.retention_days is not None:
        stream.retention_days = data.retention_days
    disk_changed = "record_disk" in data.model_fields_set
    if disk_changed:
        stream.record_disk = _validate_record_disk(data.record_disk)
    # Ubah Kamera: mainstream/substream bisa diedit (perintah user
    # 2026-11-14). main_url kosong tidak diizinkan; sub_url kosong
    # berarti hapus substream (tanpa sub, frontend fallback ke main).
    # Aturan password (perintah user 2026-11-14): password TIDAK BOLEH
    # berubah kecuali user eksplisit menggantinya — URL baru yang tak
    # membawa password atau membawa mask **** memakai password
    # tersimpan (resolve_url_password, allow_change=True: password
    # baru yang benar-benar berbeda dan bukan mask saja yang dipakai).
    # Bila URL berubah dan kamera aktif, daftarkan ulang path MediaMTX
    # supaya sumber baru langsung dipakai.
    urls_changed = False
    if "main_url" in data.model_fields_set and data.main_url is not None:
        new_main = data.main_url.strip()
        if not new_main:
            raise HTTPException(
                status_code=422, detail="mainstream tidak boleh kosong"
            )
        new_main = rtsp_discovery.resolve_url_password(
            new_main, stream.main_url or stream.rtsp_url,
            allow_change=True,
        )
        if new_main != (stream.main_url or ""):
            stream.main_url = new_main
            stream.rtsp_url = new_main
            urls_changed = True
    if "sub_url" in data.model_fields_set:
        new_sub = (data.sub_url or "").strip() or None
        if new_sub is not None:
            new_sub = rtsp_discovery.resolve_url_password(
                new_sub,
                stream.sub_url or stream.main_url or stream.rtsp_url,
                allow_change=True,
            )
        if new_sub != stream.sub_url:
            stream.sub_url = new_sub
            urls_changed = True
    await db.commit()
    await db.refresh(stream)
    # Nonaktif (aktif -> nonaktif): hapus path MediaMTX langsung, jangan
    # tunggu sync berkala 60 detik (kamera nonaktif tidak boleh tetap
    # bisa diputar sampai sync berikutnya).
    if was_active and not stream.is_active:
        try:
            await mediamtx.delete_path(f"stream_{stream_id}")
            await mediamtx.delete_path(f"stream_{stream_id}_sub")
        except Exception as e:  # noqa: BLE001
            log.warning(
                "hapus path MediaMTX stream %s gagal: %s", stream_id, e
            )
    # URL berubah dan kamera aktif: hapus path lama lalu daftarkan ulang
    # dengan sumber baru (best-effort; sync berkala mendaftarkan sendiri
    # bila MediaMTX sedang mati).
    if urls_changed and stream.is_active:
        source = stream.main_url or stream.rtsp_url
        if source:
            try:
                await mediamtx.delete_path(f"stream_{stream_id}")
                await mediamtx.delete_path(f"stream_{stream_id}_sub")
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "hapus path lama MediaMTX stream %s gagal: %s", stream_id, e
                )
            await _register_paths(
                mediamtx, stream.id, source, stream.sub_url,
                record=stream.recording_enabled, stream=stream)
    # Reaktivasi (nonaktif -> aktif) atau perubahan setelan rekaman
    # (recording on/off, retensi, record_disk): daftarkan ulang lewat
    # _register_paths, BUKAN patch_path main saja. register_stream
    # memutuskan sumber rekaman yang benar (sub merekam bila ada sub,
    # main hanya bila tanpa sub); patch lama salah menandai main
    # record=True untuk kamera bersub dan tidak pernah menyentuh sub,
    # retensi, maupun recordPath, sehingga toggle rekaman di UI tidak
    # berpengaruh pada rekaman sub yang sebenarnya.
    elif stream.is_active and (
        (not was_active)
        or recording_changed
        or retention_changed
        or disk_changed
    ):
        source = stream.main_url or stream.rtsp_url
        if source:
            await _register_paths(
                mediamtx, stream.id, source, stream.sub_url,
                record=stream.recording_enabled, stream=stream)
    out = stream_to_out(stream, get_settings())
    # T-4: PUT ini super_admin-only, tetapi main/sub tetap dikembalikan
    # dengan password teredaksi (****). Frontend mengirim **** kembali
    # dan backend memulihkan password tersimpan, jadi tidak ada password
    # mentah di respons.
    out.main_url = redact_url_credentials(stream.main_url) or None
    out.sub_url = redact_url_credentials(stream.sub_url) or None
    return out


@router.delete("/admin/streams/{stream_id}", dependencies=[Depends(super_admin_only)])
async def admin_delete_stream(
    stream_id: int,
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_dep),
):
    stream = await _get_stream_or_404(db, stream_id, require_active=False)
    try:
        await mediamtx.delete_path(f"stream_{stream_id}")
        await mediamtx.delete_path(f"stream_{stream_id}_sub")
    except Exception as e:  # noqa: BLE001 - best-effort, jangan gagalkan hapus kamera
        log.warning("hapus path MediaMTX stream %s gagal: %s", stream_id, e)
    await db.delete(stream)
    await db.commit()
    return {"ok": True}


@router.get("/admin/streams/{stream_id}/sharing")
async def get_sharing(
    stream_id: int,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _get_stream_or_404(db, stream_id, require_active=False)
    if not await _admin_may_see_stream(me, db, stream_id):
        raise HTTPException(status_code=403, detail="tidak punya akses ke kamera ini")
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
    await _get_stream_or_404(db, stream_id, require_active=False)
    # Normalisasi: bentuk baru (shares) menang; bentuk lama (user_ids)
    # dianggap can_playback=True.
    shares = list(data.shares)
    if not shares and data.user_ids:
        shares = [ShareIn(user_id=uid) for uid in data.user_ids]
    # A-S6: dedup per user_id (jaga urutan) supaya tidak menabrak
    # UniqueConstraint user_stream_access.
    seen: set[int] = set()
    deduped: list[ShareIn] = []
    for s in shares:
        if s.user_id not in seen:
            seen.add(s.user_id)
            deduped.append(s)
    shares = deduped
    # Validasi keberadaan user dulu (400 bila fiktif), sebelum cek reshare.
    user_ids = [s.user_id for s in shares]
    if user_ids:
        result = await db.execute(select(User.id).where(User.id.in_(user_ids)))
        found = set(result.scalars().all())
        missing = set(user_ids) - found
        if missing:
            raise HTTPException(status_code=400, detail=f"user tidak ada: {sorted(missing)}")
    # Admin yang membagikan wajib punya can_reshare atas kameranya;
    # bila share mencakup playback, wajib punya can_playback juga.
    for s in shares:
        await require_reshare(me, db, stream_id, need_playback=s.can_playback)
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
async def get_stream_grants(
    stream_id: int,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Grant admin untuk satu kamera (dipakai modal Bagikan)."""
    await _get_stream_or_404(db, stream_id, require_active=False)
    if not await _admin_may_see_stream(me, db, stream_id):
        raise HTTPException(status_code=403, detail="tidak punya akses ke kamera ini")
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
    await _get_stream_or_404(db, stream_id, require_active=False)
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
    stream = await _get_stream_or_404(db, stream_id, require_active=False)
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
    await _get_stream_or_404(db, stream_id, require_active=False)
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
async def get_role_access(
    stream_id: int,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _get_stream_or_404(db, stream_id, require_active=False)
    if not await _admin_may_see_stream(me, db, stream_id):
        raise HTTPException(status_code=403, detail="tidak punya akses ke kamera ini")
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
async def list_groups(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Daftar semua grup wilayah (tambahan v3.0 untuk halaman admin).

    Admin biasa hanya melihat grup yang berisi minimal satu kamera
    milik/grant-nya; grup milik grup lain tidak ikut terdaftar.
    """
    visible = await _admin_visible_stream_ids(me, db)
    result = await db.execute(select(StreamGroup).order_by(StreamGroup.name))
    groups = list(result.scalars().all())
    if visible is not None:
        member_ids: set[int] = set()
        if visible:
            member_ids = set(
                (
                    await db.execute(
                        select(GroupStream.group_id).where(
                            GroupStream.stream_id.in_(visible)
                        )
                    )
                )
                .scalars()
                .all()
            )
        groups = [g for g in groups if g.id in member_ids]
    return [
        GroupOut(id=g.id, name=g.name, description=g.description)
        for g in groups
    ]


@router.put("/admin/groups/{nama_grup}", response_model=GroupOut, dependencies=[Depends(super_admin_only)])
async def upsert_group(nama_grup: str, data: GroupCreate, db: AsyncSession = Depends(get_db)):
    # Cari berdasarkan NAMA DI PATH (grup yang diubah), bukan nama di
    # body: body.name yang berbeda berarti GANTI NAMA grup itu, bukan
    # membuat grup baru dan membiarkan grup lama tetap ada. Bila nama
    # baru sudah dipakai grup lain, tolak 409 supaya tidak ada dua
    # grup bernama sama.
    name = (data.name or nama_grup).strip()
    result = await db.execute(select(StreamGroup).where(StreamGroup.name == nama_grup))
    group = result.scalars().first()
    if group is None:
        clash = (
            await db.execute(select(StreamGroup).where(StreamGroup.name == name))
        ).scalars().first()
        if clash is not None:
            raise HTTPException(status_code=409, detail="nama grup sudah dipakai")
        group = StreamGroup(name=name, description=data.description)
        db.add(group)
    else:
        if name != group.name:
            clash = (
                await db.execute(select(StreamGroup).where(StreamGroup.name == name))
            ).scalars().first()
            if clash is not None:
                raise HTTPException(status_code=409, detail="nama grup sudah dipakai")
            group.name = name
        if data.description is not None:
            group.description = data.description
    await db.commit()
    await db.refresh(group)
    # Ganti nama grup mengubah group_name cache di stream anggotanya
    # (dipakai path rekaman multi-disk), jadi hitung ulang.
    member_ids = list(
        (
            await db.execute(
                select(GroupStream.stream_id).where(
                    GroupStream.group_id == group.id
                )
            )
        )
        .scalars()
        .all()
    )
    if member_ids:
        await _refresh_stream_group_names(db, member_ids)
        await db.commit()
    return GroupOut(id=group.id, name=group.name, description=group.description)


@router.get("/admin/groups/{nama_grup}/camera-grants")
async def get_group_grants(
    nama_grup: str,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    group = await _get_group_or_404(db, nama_grup)
    result = await db.execute(
        select(GroupStream.stream_id).where(GroupStream.group_id == group.id)
    )
    stream_ids = list(result.scalars().all())
    visible = await _admin_visible_stream_ids(me, db)
    if visible is not None:
        # Admin hanya boleh melihat grant grup bila punya minimal satu
        # kamera milik/grant di grup itu; dan yang dikembalikan hanya
        # kamera milik/grant-nya, bukan semua kamera grup itu (kamera
        # admin lain di grup yang sama tetap tersembunyi).
        if not (set(stream_ids) & visible):
            raise HTTPException(
                status_code=403, detail="tidak punya akses ke grup ini"
            )
        stream_ids = [sid for sid in stream_ids if sid in visible]
    return {"stream_ids": stream_ids}


@router.post("/admin/groups/{nama_grup}/camera-grants", dependencies=[Depends(super_admin_only)])
async def set_group_grants(nama_grup: str, data: StreamIdsIn, db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, nama_grup)
    if data.stream_ids:
        result = await db.execute(select(Stream.id).where(Stream.id.in_(data.stream_ids)))
        found = set(result.scalars().all())
        missing = set(data.stream_ids) - found
        if missing:
            raise HTTPException(status_code=400, detail=f"stream tidak ada: {sorted(missing)}")
    # Anggota lama grup ini ikut terpengaruh (kehilangan grup ini),
    # jadi group_name mereka juga harus dihitung ulang.
    old_ids = set(
        (
            await db.execute(
                select(GroupStream.stream_id).where(
                    GroupStream.group_id == group.id
                )
            )
        )
        .scalars()
        .all()
    )
    await db.execute(delete(GroupStream).where(GroupStream.group_id == group.id))
    for sid in data.stream_ids:
        db.add(GroupStream(group_id=group.id, stream_id=sid))
    await _refresh_stream_group_names(db, old_ids | set(data.stream_ids))
    await db.commit()
    return {"ok": True, "stream_ids": data.stream_ids}


@router.get("/admin/disk-summary", dependencies=[Depends(rate_limited(20, 60))])
async def disk_info(db: AsyncSession = Depends(get_db)):
    # Ringkasan disk agregat (bukan inventaris per kamera/grup):
    # tetap bisa dibaca admin biasa, dikunci test_disks. Folder
    # Drive di dalamnya hanya nama/URL folder, bukan isi rekaman.
    # A-1.10: hasil di-cache 60 dtk (sebelumnya tiap panggilan
    # os.walk seluruh staging) + rate limit; pemindaian jalan di
    # thread (asyncio.to_thread) supaya tidak memblokir event loop.
    now = time.monotonic()
    if _disk_cache["body"] is not None and now - _disk_cache["at"] < _DISK_CACHE_TTL:
        return dict(_disk_cache["body"])
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
        # B-R1: GET tidak boleh berefek samping (dulu os.makedirs di sini)
        # dan jangan memindai staging bila path tidak ada/bukan direktori.
        # Kuota adalah asumsi dari konfigurasi (gdrive_quota_tb), bukan
        # kuota nyata Google Drive; ditandai quota_source agar tidak
        # menyesatkan.
        if not gdrive_path or not os.path.isdir(gdrive_path):
            gdrive_entries.append({
                "folder_id": fol.id,
                "mount": gdrive_path,
                "label": f"Google Drive — {fol.folder_name or fol.folder_id}",
                "drive_folder_id": fol.folder_id,
                "drive_folder_name": fol.folder_name or "",
                "drive_folder_url": fol.folder_url or "",
                "storage_type": "google_drive",
                "size_bytes": int(settings.gdrive_quota_tb * (1024**4)),
                "avail_bytes": int(settings.gdrive_quota_tb * (1024**4)),
                "size_human": f"{settings.gdrive_quota_tb:g}TB",
                "avail_human": f"{settings.gdrive_quota_tb:g}TB",
                "fstype": "gdrive",
                "usage_pct": 0,
                "mounted": False,
                "quota_source": "configured",
            })
            continue
        try:
            quota_tb = settings.gdrive_quota_tb
            total = int(quota_tb * (1024**4))
            # A-1.10: os.walk sinkron dipindah ke thread.
            used = await asyncio.to_thread(_walk_used_bytes, gdrive_path)
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
                "mounted": True,
                "quota_source": "configured",
            })
        except Exception as e:  # noqa: BLE001
            log.warning("disk Google Drive gagal: %s", e)
    if gdrive_entries:
        out["google_drive"] = gdrive_entries[0]  # kompatibel lama: satu entri
        out["google_drive_folders"] = gdrive_entries
    _disk_cache["at"] = now
    _disk_cache["body"] = out
    return out


def _walk_used_bytes(path: str) -> int:
    """Jumlah byte seluruh file di bawah `path` (sinkron; dipanggil
    lewat asyncio.to_thread supaya tidak memblokir event loop)."""
    used = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                used += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return used


# A-1.10: cache ringkasan disk 60 dtk (in-process, satu nilai).
_DISK_CACHE_TTL = 60.0
_disk_cache: dict = {"at": 0.0, "body": None}


def reset_disk_cache() -> None:
    """Kosongkan cache disk-summary (dipakai test)."""
    _disk_cache["at"] = 0.0
    _disk_cache["body"] = None


def _to_scan_path(p: rtsp_discovery.PathResult, role: str | None) -> ScanPath:
    return ScanPath(
        path=p.path, url=p.url, status=p.status, codec=p.codec,
        width=p.width, height=p.height, fps=p.fps,
        gop_seconds=p.gop_seconds, role=role,
    )


def _redact_scan_result(
    candidates: list[ScanCandidate],
    paths: list[ScanPath],
    best_main: str | None,
    best_sub: str | None,
    auth_mode: str | None = None,
) -> ScanResult:
    """4.6: hasil scan dikembalikan dengan password TEREDAKSI.

    URL asli (termasuk password yang diisi super_admin dan password
    default pabrik hasil discovery) disimpan di brankas server di
    bawah scan_id; POST /admin/streams memulihkannya dengan
    scan_ref=scan_id. Tanpa ini password tersebar ke body respons,
    state frontend, dan log.
    """
    scan_id = secrets.token_hex(16)
    scan_vault.register(
        scan_id,
        [c.main_url for c in candidates]
        + [c.sub_url for c in candidates]
        + [p.url for p in paths]
        + [best_main, best_sub],
    )
    return ScanResult(
        candidates=[
            c.model_copy(
                update={
                    "main_url": redact_url_credentials(c.main_url),
                    "sub_url": redact_url_credentials(c.sub_url)
                    if c.sub_url
                    else None,
                }
            )
            for c in candidates
        ],
        paths=[
            p.model_copy(update={"url": redact_url_credentials(p.url)})
            for p in paths
        ],
        best_main=redact_url_credentials(best_main) if best_main else None,
        best_sub=redact_url_credentials(best_sub) if best_sub else None,
        auth_mode=auth_mode,
        scan_id=scan_id,
    )


@router.post(
    "/admin/scan",
    response_model=ScanResult,
    dependencies=[Depends(super_admin_only), Depends(rate_limited(10, 60))],
)
async def scan_camera(data: ScanRequest):
    """Scan kamera dengan verifikasi video (ffprobe), bukan sekadar port/401.

    A-1.4: super_admin-only seperti /admin/scan-subnet (admin_scan,
    E-K1). Sebelumnya admin biasa bisa memindai URL/host RTSP arbitrer
    dengan kredensial isiannya (ffprobe/DESCRIBE ke jaringan internal).

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
        # A-S4: URL tidak valid harus 400, bukan 500.
        try:
            res = await resolve_stream(brand=None, rtsp_url=url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
        return _redact_scan_result(
            candidates, paths, best_main, None
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
    auth_mode: str | None = None  # None bila tanpa probe (disc tak ada)
    if data.probe:
        disc = await rtsp_discovery.discover_host(
            data.host, data.port, data.user, data.password, data.channel
        )
        best_main, best_sub = disc.best_main, disc.best_sub
        auth_mode = disc.auth_mode
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
    return _redact_scan_result(
        candidates, paths, best_main, best_sub, auth_mode
    )


@router.post(
    "/admin/scan/preview",
    dependencies=[Depends(super_admin_only), Depends(rate_limited(10, 60))],
)
async def scan_preview(data: PreviewIn):
    # A-1.4: super_admin-only, sama seperti /admin/scan di atas.
    # TODO Fase 2: frontend memutar URL hasil resolve untuk preview visual
    # sebelum kamera disimpan.
    try:
        res = await resolve_stream(brand=None, rtsp_url=data.rtsp_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 4.6: URL preview dikembalikan teredaksi seperti hasil scan lain.
    return {
        "main_url": redact_url_credentials(res.main_url),
        "sub_url": redact_url_credentials(res.sub_url)
        if res.sub_url
        else None,
        "method": res.method,
    }
