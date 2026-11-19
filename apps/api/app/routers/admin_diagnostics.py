"""Router admin: halaman Diagnostik tambah kamera.

GET /api/admin/diagnostics/camera-add
    Tiga seksi: control API MediaMTX (versi + akses), status
    registrasi path MediaMTX per kamera, hasil probe RTSP terakhir
    per kamera, ditambah riwayat 20 kegagalan terakhir.

POST /api/admin/diagnostics/camera-add/probe
    Probe ulang RTSP satu kamera (main + sub bila ada), klasifikasikan
    hasilnya, simpan ke riwayat probe dan riwayat kegagalan.

Hanya super_admin. Tidak pernah mengembalikan kredensial kamera:
path RTSP tidak ditampilkan, hanya status probe dan envelope
kegagalan yang sudah di-redact.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rbac import require_roles
from app.db.session import get_db
from app.models.diagnostics import CameraAddFailure, CameraProbeResult
from app.models.streams import Stream
from app.schemas.diagnostics import (
    CameraFailureOut,
    DiagnosticsOut,
    FailureRowOut,
    MediamtxStatusOut,
    PathStatusOut,
    ProbeOut,
    ProbeRequest,
    ProbeRoleOut,
    ProbeRowOut,
)
from app.services import rtsp_discovery
from app.services.camera_diagnostics import (
    classify_mediamtx_error,
    classify_probe,
    record_failure,
    record_probe_result,
)
from app.services.mediamtx import MediaMTXClient, get_mediamtx_dep
from app.services.stream_paths import main_path, sub_path

router = APIRouter(
    tags=["admin-diagnostics"],
    dependencies=[Depends(require_roles("super_admin"))],
)
log = logging.getLogger("netravision.admin_diagnostics")

# Batas riwayat kegagalan yang ditampilkan di halaman Diagnostik.
HISTORY_LIMIT = 20

# Status MediaMTX per status HTTP control API.
_STATUS_BY_KIND = {
    "redirect": "redirect",
    "auth": "auth",
    "unreachable": "unreachable",
}


@router.get("/admin/diagnostics/camera-add", response_model=DiagnosticsOut)
async def get_camera_add_diagnostics(
    db: AsyncSession = Depends(get_db),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_dep),
):
    settings = get_settings()
    api_url = settings.mediamtx_api_url
    # Seksi 1: control API MediaMTX (versi + akses). get_config
    # menembak /v3/config/global/get; bila API melaporkan versi,
    # dipakai, bila tidak, versi dilaporkan tidak diketahui.
    mediamtx_section = MediamtxStatusOut(
        api_url=api_url, reachable=False, status="unreachable"
    )
    try:
        config = await mediamtx.get_config()
        mediamtx_section.reachable = True
        mediamtx_section.status = "ok"
        if config:
            version = config.get("version")
            if version:
                mediamtx_section.version = str(version)
    except Exception as e:  # noqa: BLE001 - klasifikasikan, jangan 500
        failure = classify_mediamtx_error(e)
        mediamtx_section.status = _STATUS_BY_KIND.get(
            failure["code"].removeprefix("mediamtx_"), "error"
        )
        mediamtx_section.failure = CameraFailureOut(**failure)

    # Seksi 2: registrasi path MediaMTX. Satu get_paths (bukan
    # per kamera) lalu cocokkan dengan nama path tiap kamera aktif.
    paths_hilang: list[PathStatusOut] = []
    paths_terdaftar = 0
    paths_total = 0
    try:
        registered = await mediamtx.get_paths()
    except Exception as e:  # noqa: BLE001 - halaman tetap tampil
        log.warning("diagnostik: get_paths gagal: %s", e)
        registered = set()
    streams = (
        (await db.execute(
            select(Stream).where(Stream.is_active.is_(True)).order_by(Stream.id)
        ))
        .scalars()
        .all()
    )
    for stream in streams:
        # Path sub hanya didaftarkan bila kamera punya sub_url asli.
        names = [main_path(stream.id)]
        if stream.sub_url:
            names.append(sub_path(stream.id))
        for name in names:
            paths_total += 1
            if name in registered:
                paths_terdaftar += 1
            else:
                paths_hilang.append(
                    PathStatusOut(
                        stream_id=stream.id,
                        name=stream.name,
                        path=name,
                        terdaftar=False,
                    )
                )

    # Seksi 3: hasil probe RTSP terakhir per kamera aktif.
    probe_rows = (
        (await db.execute(
            select(CameraProbeResult).order_by(CameraProbeResult.stream_id)
        ))
        .scalars()
        .all()
    )
    probe_by_id = {row.stream_id: row for row in probe_rows}
    rtsp = [
        ProbeRowOut(
            stream_id=stream.id,
            name=stream.name,
            main_status=(
                probe_by_id[stream.id].main_status
                if stream.id in probe_by_id
                else None
            ),
            sub_status=(
                probe_by_id[stream.id].sub_status
                if stream.id in probe_by_id
                else None
            ),
            checked_at=(
                probe_by_id[stream.id].checked_at
                if stream.id in probe_by_id
                else None
            ),
        )
        for stream in streams
    ]

    # Riwayat: 20 kegagalan terakhir, terbaru dulu.
    failures = (
        (await db.execute(
            select(CameraAddFailure)
            .order_by(CameraAddFailure.created_at.desc())
            .limit(HISTORY_LIMIT)
        ))
        .scalars()
        .all()
    )
    riwayat = [
        FailureRowOut(
            id=row.id,
            stream_id=row.stream_id,
            camera_name=row.camera_name,
            code=row.code,
            judul=row.judul,
            penyebab=row.penyebab,
            langkah=row.langkah or [],
            created_at=row.created_at,
        )
        for row in failures
    ]

    return DiagnosticsOut(
        mediamtx=mediamtx_section,
        paths_total=paths_total,
        paths_terdaftar=paths_terdaftar,
        paths_hilang=paths_hilang,
        rtsp=rtsp,
        riwayat=riwayat,
    )


@router.post(
    "/admin/diagnostics/camera-add/probe", response_model=ProbeOut
)
async def probe_camera(
    payload: ProbeRequest,
    db: AsyncSession = Depends(get_db),
):
    stream = await db.get(Stream, payload.stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="kamera tidak ditemukan")

    main_url = stream.main_url or stream.rtsp_url
    sub_url = stream.sub_url
    if not main_url:
        raise HTTPException(
            status_code=400, detail="kamera ini tidak punya URL RTSP"
        )

    # Probe main dan sub lewat verify_url (tidak pernah memutar
    # kredensial ke respons). verify_url sendiri tidak melempar untuk
    # kegagalan RTSP biasa; statusnya diklasifikasikan di sini.
    vp_main = await rtsp_discovery.verify_url(main_url)
    main_failure = classify_probe(vp_main.status, "main")
    main = ProbeRoleOut(
        status=vp_main.status,
        failure=CameraFailureOut(**main_failure) if main_failure else None,
    )

    sub = None
    sub_failure: dict | None = None
    sub_status: str | None = None
    if sub_url:
        vp_sub = await rtsp_discovery.verify_url(sub_url)
        sub_status = vp_sub.status
        sub_failure = classify_probe(vp_sub.status, "sub")
        sub = ProbeRoleOut(
            status=vp_sub.status,
            failure=CameraFailureOut(**sub_failure) if sub_failure else None,
        )

    await record_probe_result(
        db, stream_id=stream.id, camera_name=stream.name,
        main_status=vp_main.status, sub_status=sub_status,
    )
    if main_failure is not None:
        await record_failure(
            db, stream_id=stream.id, camera_name=stream.name,
            failure=main_failure,
        )
    if sub_failure is not None:
        await record_failure(
            db, stream_id=stream.id, camera_name=stream.name,
            failure=sub_failure,
        )

    return ProbeOut(
        stream_id=stream.id,
        name=stream.name,
        main=main,
        sub=sub,
    )
