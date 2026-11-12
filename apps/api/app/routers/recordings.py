"""Router recordings: 8 endpoint persis kontrak (MIGRATION-MAP §3).

Sumber segmen: lokal (pola deploy/mediamtx.yml) + Google Drive bila
storage_mode stream = drive/both dan drive_enabled (proxy via backend).
"""

import asyncio
import logging
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rbac import require_camera_playback_access, require_roles
from app.db.session import get_db
from app.models.streams import Stream
from app.models.users import User
from app.schemas.recording import (
    DatesOut,
    NextPlayableOut,
    PlaybackUrlOut,
    SegmentOut,
    TimelineOut,
)
from app.schemas.stream import StreamOut
from app.services.drive import CHUNK
from app.services.recording import (
    Segment,
    _assign_ends,
    find_next_playable,
    list_segments,
    parse_segment_name,
)

log = logging.getLogger("netravision.recordings")

router = APIRouter()
user_or_above = require_roles("admin", "user", "guest")

_ONE_DAY = timedelta(days=1)


async def _get_stream(stream_id: int, db: AsyncSession) -> Stream:
    result = await db.execute(select(Stream).where(Stream.id == stream_id))
    stream = result.scalars().first()
    if stream is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kamera tidak ditemukan")
    return stream


async def _folder_link_segments(
    stream: Stream, day: date | None, db: AsyncSession
) -> list[Segment]:
    """Segmen dari staging lokal folder-link (local_path tiap tautan Drive).

    B-T1: jalur upload folder-link (mirror/uploader rclone) menulis ke
    {local_path}/stream_{id}/, staging ini harus dibaca playback, bukan
    hanya segmen lokal recordings_dir + folder OAuth.
    """
    settings = get_settings()
    out: list[Segment] = []
    try:
        from app.models.drive import GoogleDriveFolder

        rows = (
            await db.execute(select(GoogleDriveFolder).order_by(GoogleDriveFolder.id))
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        log.warning("drive folder-link list gagal: %s", e)
        return out
    for row in rows:
        base = (row.local_path or "").rstrip("/") or (
            settings.gdrive_record_path or ""
        ).rstrip("/")
        if not base:
            continue
        d = os.path.join(base, f"stream_{stream.id}")
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".mp4"):
                continue
            start = parse_segment_name(name)
            if start is None or (day is not None and start.date() != day):
                continue
            path = os.path.join(d, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            out.append(Segment(start=start, path=path, size=size, name=name))
    return out


async def _rclone_segments(
    stream: Stream, day: date | None, db: AsyncSession
) -> list[Segment]:
    """Segmen dari folder Drive rclone kamera ini (akun disk1 dsb.).

    Uploader rclone menulis ke `{remote}:{folder_id}/{nama_kamera}/nama-segmen.mp4`,
    jadi daftar dibaca dari jalur itu via `rclone lsjson`. Hanya folder yang
    punya remote_name (folder akun) yang bisa dibaca cara ini; tautan folder
    manual tanpa remote dilewati.
    """
    from app.models.drive import GoogleDriveFolder
    from app.services import gdrive_rclone as gr

    out: list[Segment] = []
    try:
        if stream.drive_folder_id:
            row = await db.get(GoogleDriveFolder, stream.drive_folder_id)
        else:
            row = (
                await db.execute(
                    select(GoogleDriveFolder).order_by(GoogleDriveFolder.id)
                )
            ).scalars().first()
    except Exception as e:  # noqa: BLE001
        log.warning("rclone folder kamera %s gagal: %s", stream.name, e)
        return out
    if row is None or not row.folder_name or not row.remote_name:
        return out
    cam_name = stream.name or f"Kamera {stream.id}"
    base = f"{row.folder_name}/{cam_name}"
    try:
        items = await gr.list_rclone_files(row.remote_name, base)
    except Exception as e:  # noqa: BLE001 - Drive opsional, jangan gagalkan timeline
        log.warning("rclone list %s gagal: %s", stream.name, e)
        return out
    for f in items:
        name = f.get("name", "")
        if not name.endswith(".mp4"):
            continue
        start = parse_segment_name(name)
        if start is None or (day is not None and start.date() != day):
            continue
        out.append(
            Segment(
                start=start,
                path="",
                size=int(f.get("size") or 0),
                name=name,
                rclone_remote=row.remote_name,
                rclone_path=f"{base}/{name}",
            )
        )
    return out


async def _all_segments(
    stream: Stream, day: date | None, db: AsyncSession
) -> list[Segment]:
    """Gabungan segmen lokal + folder-link + Drive akun kamera ini.

    Lokal menang bila nama sama, lalu folder-link, lalu folder OAuth.
    """
    settings = get_settings()
    segs = list_segments(stream.id, day, settings.recordings_dir)
    if stream.storage_mode in ("drive", "both"):
        names = {s.name for s in segs}
        # B-T1: staging lokal folder-link (mirror rclone).
        try:
            for s in await _folder_link_segments(stream, day, db):
                if s.name not in names:
                    names.add(s.name)
                    segs.append(s)
        except Exception as e:  # noqa: BLE001
            log.warning("drive folder-link %s gagal: %s", stream.name, e)
        # Drive rclone (akun disk1 dsb.): lokal menang bila nama sama.
        try:
            for s in await _rclone_segments(stream, day, db):
                if s.name not in names:
                    names.add(s.name)
                    segs.append(s)
        except Exception as e:  # noqa: BLE001
            log.warning("drive rclone %s gagal: %s", stream.name, e)
    if stream.storage_mode in ("drive", "both") and settings.drive_enabled:
        try:
            from app.services.drive_accounts import uploader_for_stream

            up = await uploader_for_stream(db, stream)
            if up is None:
                return _finish(segs)
            folder_id = await up.ensure_folder(stream.name, stream.id)
            for f in await up.list_files(folder_id):
                name = f.get("name", "")
                if name in names or not name.endswith(".mp4"):
                    continue
                start = parse_segment_name(name)
                if start is None or (day is not None and start.date() != day):
                    continue
                segs.append(
                    Segment(
                        start=start,
                        path="",
                        size=int(f.get("size") or 0),
                        name=name,
                        drive_file_id=f.get("id"),
                    )
                )
        except Exception as e:  # noqa: BLE001, Drive opsional, jangan gagalkan
            log.warning("drive list %s gagal: %s", stream.name, e)
    return _finish(segs)


def _finish(segs: list[Segment]) -> list[Segment]:
    segs.sort(key=lambda s: s.start)
    _assign_ends(segs)
    return segs


async def _containing(
    stream: Stream, at: datetime, db: AsyncSession
) -> Segment | None:
    """Segmen (lokal/Drive) yang memuat waktu `at`."""
    if at.tzinfo is not None:
        at = at.replace(tzinfo=None)
    for seg in await _all_segments(stream, None, db):
        if seg.start > at + _ONE_DAY:
            break
        end = seg.end or seg.start
        if seg.start <= at < end:
            return seg
    return None


def _parse_range(header: str | None, total: int) -> tuple[int, int, bool]:
    """Header `Range: bytes=a-b` -> (start, end, valid)."""
    if not header or total <= 0:
        return 0, total - 1, False
    m = re.match(r"bytes=(\d+)-(\d*)$", header.strip())
    if not m:
        return 0, total - 1, False
    start = int(m.group(1))
    if start >= total:
        return 0, total - 1, False
    end = int(m.group(2)) if m.group(2) else total - 1
    return start, min(end, total - 1), True


def _cleanup(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


async def _trimmed_segment_file(
    stream: Stream, seg: Segment, start: datetime | None,
    end: datetime | None, db: AsyncSession,
) -> str | None:
    """Potong segmen ke rentang [start, end] via ffmpeg (stream-copy).

    B-S3: kembalikan potongan yang diminta, bukan seluruh file segmen.
    Return path file temp, atau None bila tak perlu dipotong / ffmpeg tak ada
    / gagal (pemanggil memakai segmen utuh dan mencatat warning).
    """
    seg_end = seg.end or seg.start
    if (start is None or start <= seg.start) and (end is None or end >= seg_end):
        return None
    if not shutil.which("ffmpeg"):
        log.warning("trim segmen %s dilewati: ffmpeg tidak ada", seg.name)
        return None
    cut_start = max(start, seg.start) if start is not None else seg.start
    cut_end = min(end, seg_end) if end is not None else seg_end
    duration = (cut_end - cut_start).total_seconds()
    if duration <= 0:
        return None
    offset = max(0.0, (cut_start - seg.start).total_seconds())
    tmp_in = tmp_out = None
    try:
        if seg.path and os.path.exists(seg.path):
            src = seg.path
        elif seg.rclone_remote and seg.rclone_path:
            # Segmen Drive rclone: unduh dulu ke temp, lalu potong.
            from app.services import gdrive_rclone as gr

            fd, tmp_in = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            try:
                data = await gr.download_rclone_file(
                    seg.rclone_remote, seg.rclone_path
                )
                with open(tmp_in, "wb") as f:
                    f.write(data)
            except Exception as e:  # noqa: BLE001
                log.warning("rclone unduh segmen %s gagal: %s", seg.name, e)
                _cleanup(tmp_in)
                return None
            src = tmp_in
        else:
            # Segmen Drive: unduh dulu ke temp, lalu potong.
            from app.services.drive_accounts import uploader_for_stream

            up = await uploader_for_stream(db, stream)
            if up is None:
                return None
            file_id = seg.drive_file_id
            if not file_id:
                folder_id = await up.ensure_folder(stream.name, stream.id)
                file_id = await up.find_file(folder_id, seg.name)
            if not file_id:
                return None
            fd, tmp_in = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            pos = 0
            with open(tmp_in, "wb") as f:
                while True:
                    chunk = await up.stream_drive_file(
                        file_id, pos, pos + CHUNK - 1
                    )
                    if not chunk:
                        break
                    f.write(chunk)
                    if len(chunk) < CHUNK:
                        break
                    pos += CHUNK
            src = tmp_in
        fd, tmp_out = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(offset), "-i", src,
            "-t", str(duration), "-c", "copy",
            "-movflags", "+faststart", tmp_out,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            log.warning(
                "trim segmen %s gagal: %s",
                seg.name, err.decode(errors="replace").strip()[:200],
            )
            _cleanup(tmp_out)
            return None
        return tmp_out
    except Exception as e:  # noqa: BLE001
        log.warning("trim segmen %s gagal: %s", seg.name, e)
        if tmp_out:
            _cleanup(tmp_out)
        return None
    finally:
        if tmp_in:
            _cleanup(tmp_in)


def _cleanup_many(paths: list[str]) -> None:
    for p in paths:
        _cleanup(p)


async def _segment_part_file(
    stream: Stream, seg: Segment, part_start: datetime, part_end: datetime,
    db: AsyncSession,
) -> tuple[str | None, bool]:
    """File lokal untuk bagian segmen [part_start, part_end].

    Return (path, is_temp). None bila segmen tidak bisa disiapkan.
    Dipakai unduh rentang: bagian utuh dari file lokal dipakai langsung,
    sisanya dipotong via ffmpeg (Drive diunduh dulu ke temp).
    """
    seg_end = seg.end or seg.start
    if (
        part_start <= seg.start
        and part_end >= seg_end
        and seg.path
        and os.path.exists(seg.path)
    ):
        return seg.path, False
    trimmed = await _trimmed_segment_file(stream, seg, part_start, part_end, db)
    if trimmed is not None:
        return trimmed, True
    # _trimmed_segment_file mengembalikan None bila tidak perlu dipotong.
    if seg.path and os.path.exists(seg.path):
        return seg.path, False
    # Segmen Drive tanpa potong: unduh utuh ke temp.
    if seg.rclone_remote and seg.rclone_path:
        from app.services import gdrive_rclone as gr

        fd, tmp = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            data = await gr.download_rclone_file(
                seg.rclone_remote, seg.rclone_path
            )
            with open(tmp, "wb") as f:
                f.write(data)
            return tmp, True
        except Exception as e:  # noqa: BLE001
            log.warning("rclone unduh segmen %s gagal: %s", seg.name, e)
            _cleanup(tmp)
            return None, False
    from app.services.drive_accounts import uploader_for_stream

    up = await uploader_for_stream(db, stream)
    if up is None:
        return None, False
    try:
        file_id = seg.drive_file_id
        if not file_id:
            folder_id = await up.ensure_folder(stream.name, stream.id)
            file_id = await up.find_file(folder_id, seg.name)
    except Exception as e:  # noqa: BLE001
        log.warning("Drive lookup segmen %s gagal: %s", seg.name, e)
        return None, False
    if not file_id:
        return None, False
    fd, tmp = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        pos = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = await up.stream_drive_file(file_id, pos, pos + CHUNK - 1)
                if not chunk:
                    break
                f.write(chunk)
                if len(chunk) < CHUNK:
                    break
                pos += CHUNK
        return tmp, True
    except Exception as e:  # noqa: BLE001
        log.warning("Drive unduh segmen %s gagal: %s", seg.name, e)
        _cleanup(tmp)
        return None, False


async def _serve_segment(
    stream: Stream, seg: Segment, download: bool, db: AsyncSession,
    request: Request | None = None,
    start: datetime | None = None, end: datetime | None = None,
) -> FileResponse | StreamingResponse:
    if start is not None and start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    if end is not None and end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    # B-S3: hormati rentang waktu yang diminta (potong via ffmpeg).
    trimmed = await _trimmed_segment_file(stream, seg, start, end, db)
    if trimmed is not None:
        return FileResponse(
            trimmed,
            media_type="application/octet-stream" if download else "video/mp4",
            filename=seg.name if download else None,
            background=BackgroundTask(_cleanup, trimmed),
        )
    if seg.path and os.path.exists(seg.path):
        if download:
            return FileResponse(
                seg.path,
                media_type="application/octet-stream",
                filename=seg.name,
            )
        return FileResponse(seg.path, media_type="video/mp4")
    # Segmen Drive rclone (akun disk1 dsb.): stream via rclone cat.
    if seg.rclone_remote and seg.rclone_path:
        from app.services import gdrive_rclone as gr

        total = seg.size or 0
        r_start, r_end, has_range = _parse_range(
            request.headers.get("range") if request is not None else None, total
        )
        headers = {"Accept-Ranges": "bytes"}
        status_code = 200
        if has_range:
            headers["Content-Range"] = f"bytes {r_start}-{r_end}/{total}"
            headers["Content-Length"] = str(r_end - r_start + 1)
            status_code = 206
        elif total > 0:
            headers["Content-Length"] = str(total)
        if download:
            headers["Content-Disposition"] = (
                f'attachment; filename="{seg.name}"'
            )

        async def gen_rclone():
            pos = r_start
            while True:
                if has_range and pos > r_end:
                    break
                chunk_end = pos + CHUNK - 1
                if has_range:
                    chunk_end = min(chunk_end, r_end)
                try:
                    chunk = await gr.stream_rclone_file(
                        seg.rclone_remote, seg.rclone_path, pos, chunk_end
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning(
                        "rclone stream segmen %s gagal: %s", seg.name, e
                    )
                    break
                if not chunk:
                    break
                yield chunk
                if len(chunk) < CHUNK:
                    break
                pos += CHUNK

        return StreamingResponse(
            gen_rclone(),
            media_type="application/octet-stream" if download else "video/mp4",
            headers=headers,
            status_code=status_code,
        )
    # Fallback Drive, via akun kamera ini.
    from app.services.drive_accounts import uploader_for_stream

    up = await uploader_for_stream(db, stream)
    if up is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "segmen tidak ditemukan")
    try:
        file_id = seg.drive_file_id
        if not file_id:
            folder_id = await up.ensure_folder(stream.name, stream.id)
            file_id = await up.find_file(folder_id, seg.name)
    except Exception as e:  # noqa: BLE001 - Drive API bisa HttpError/timeout -> 502, bukan 500
        # A-S5: Segment tidak punya field id, pakai seg.name.
        log.warning("Drive lookup segmen %s gagal: %s", seg.name, e)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Google Drive tidak terjangkau: {e}"
        ) from e
    if not file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "segmen tidak ditemukan")

    # B-S1: dukung HTTP Range seperti segmen lokal (seek pemutar video).
    total = seg.size or 0
    r_start, r_end, has_range = _parse_range(
        request.headers.get("range") if request is not None else None, total
    )
    headers = {"Accept-Ranges": "bytes"}
    status_code = 200
    if has_range:
        headers["Content-Range"] = f"bytes {r_start}-{r_end}/{total}"
        headers["Content-Length"] = str(r_end - r_start + 1)
        status_code = 206
    elif total > 0:
        headers["Content-Length"] = str(total)
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{seg.name}"'

    async def gen():
        pos = r_start
        while True:
            if has_range and pos > r_end:
                break
            chunk_end = pos + CHUNK - 1
            if has_range:
                chunk_end = min(chunk_end, r_end)
            try:
                chunk = await up.stream_drive_file(file_id, pos, chunk_end)
            except Exception as e:  # noqa: BLE001 - streaming Drive gagal di tengah jalan
                # A-S5: Segment tidak punya field id, pakai seg.name.
                log.warning("Drive stream segmen %s gagal: %s", seg.name, e)
                break
            if not chunk:
                break
            yield chunk
            if len(chunk) < CHUNK:
                break
            pos += CHUNK

    return StreamingResponse(
        gen(),
        media_type="application/octet-stream" if download else "video/mp4",
        headers=headers,
        status_code=status_code,
    )


def _file_url(stream_id: int, seg: Segment) -> str:
    end = (seg.end or seg.start).isoformat()
    return (
        f"/api/recordings/{stream_id}/file"
        f"?start={seg.start.isoformat()}&end={end}"
    )


@router.get("/recordings/cameras", response_model=list[StreamOut])
async def recording_cameras(
    user: User = Depends(user_or_above),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Kamera yang boleh diakses user dan punya rekaman aktif."""
    from app.routers.streams import _visible_streams, stream_to_out

    streams = await _visible_streams(user, db)
    return [
        stream_to_out(s, settings)
        for s in streams
        if s.recording_enabled
    ]


@router.get("/recordings/{stream_id}/timeline", response_model=TimelineOut)
async def timeline(
    stream_id: int,
    day: date | None = Query(None, alias="date"),
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    day = day or date.today()
    segs = await _all_segments(stream, day, db)
    return {
        "date": day.isoformat(),
        "entries": [
            {
                "start": s.start.isoformat(),
                "end": (s.end or s.start).isoformat(),
                "has_event": False,
            }
            for s in segs
        ],
        "events": [],
    }


@router.get("/recordings/{stream_id}/segments", response_model=list[SegmentOut])
async def segments(
    stream_id: int,
    day: date | None = Query(None, alias="date"),
    hour: int | None = Query(None, ge=0, le=23),
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    segs = await _all_segments(stream, day, db)
    if hour is not None:
        segs = [s for s in segs if s.start.hour == hour]
    return [
        SegmentOut(
            start=s.start.isoformat(),
            end=(s.end or s.start).isoformat(),
            duration_sec=int(((s.end or s.start) - s.start).total_seconds()),
            size_bytes=s.size,
            url=_file_url(stream_id, s),
        )
        for s in segs
    ]


@router.get("/recordings/{stream_id}/dates", response_model=DatesOut)
async def dates(
    stream_id: int,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    segs = await _all_segments(stream, None, db)
    return {"dates": sorted({s.start.date().isoformat() for s in segs})}


@router.get("/recordings/{stream_id}/stream")
async def stream_range(
    stream_id: int,
    start: datetime,
    end: datetime | None = None,
    request: Request = None,  # noqa: B008 - FastAPI mengisi Request
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    """Stream video rentang waktu (inline, video/mp4)."""
    # B-S3: seragamkan timezone sebelum membandingkan (campur naive/aware
    # sebelumnya bisa TypeError -> 500).
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    if end is not None and end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    if end is not None and end < start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end < start")
    stream = await _get_stream(stream_id, db)
    seg = await _containing(stream, start, db)
    if seg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
    return await _serve_segment(
        stream, seg, download=False, db=db, request=request, start=start, end=end
    )


@router.get("/recordings/{stream_id}/file")
async def download_file(
    stream_id: int,
    start: datetime,
    end: datetime,
    request: Request = None,  # noqa: B008 - FastAPI mengisi Request
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    """Unduh potongan rekaman (attachment). Rentang harus milik stream ini."""
    # B-S3: seragamkan timezone sebelum membandingkan.
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    if end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    if end < start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end < start")
    stream = await _get_stream(stream_id, db)
    seg = await _containing(stream, start, db)
    if seg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
    seg_end = seg.end or seg.start
    if end > seg_end:
        # Rentang melintasi beberapa segmen: tolak dengan jelas daripada
        # memotong diam-diam (minta per segmen).
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "rentang melewati batas segmen, unduh per segmen",
        )
    return await _serve_segment(
        stream, seg, download=True, db=db, request=request, start=start, end=end
    )


MAX_DOWNLOAD_RANGE = timedelta(hours=2)


@router.get("/recordings/{stream_id}/download-range")
async def download_range(
    stream_id: int,
    start: datetime,
    end: datetime,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    """Unduh rekaman rentang [start, end] sebagai satu file MP4.

    Segmen yang tumpang tindih dengan rentang dipotong ke rentang lalu
    digabung via ffmpeg (stream copy, tanpa re-encode). Maksimal 2 jam
    per unduhan; celah antar segmen (kamera mati) tidak diisi, video
    langsung melompat ke segmen berikutnya.
    """
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    if end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    if end <= start:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "end harus setelah start"
        )
    if end - start > MAX_DOWNLOAD_RANGE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "rentang maksimal 2 jam per unduhan",
        )
    if not shutil.which("ffmpeg"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ffmpeg tidak tersedia di server",
        )
    stream = await _get_stream(stream_id, db)
    segs = [
        s
        for s in await _all_segments(stream, None, db)
        if s.start < end and (s.end or s.start) > start
    ]
    if not segs:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "tidak ada rekaman pada rentang itu"
        )
    parts: list[str] = []
    temps: list[str] = []
    try:
        for seg in segs:
            seg_end = seg.end or seg.start
            p_start = max(seg.start, start)
            p_end = min(seg_end, end)
            if p_end <= p_start:
                continue
            path, is_temp = await _segment_part_file(
                stream, seg, p_start, p_end, db
            )
            if path is None:
                log.warning(
                    "download-range: segmen %s dilewati (tidak bisa disiapkan)",
                    seg.name,
                )
                continue
            parts.append(path)
            if is_temp:
                temps.append(path)
        if not parts:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "tidak ada rekaman pada rentang itu"
            )
        fd, list_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        temps.append(list_path)
        with open(list_path, "w") as f:
            for p in parts:
                # Jalur harus absolut: concat demuxer membaca jalur relatif
                # terhadap lokasi file list (di /tmp), bukan cwd API,
                # jadi jalur relatif data/recordings/... tidak ketemu.
                safe = os.path.abspath(p).replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        fd, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        temps.append(out_path)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", "-movflags", "+faststart", out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            log.warning(
                "download-range gabung gagal: %s",
                err.decode(errors="replace").strip()[:200],
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "gagal menggabung rekaman",
            )
        name = (
            f"rekaman-{stream_id}-"
            f"{start.strftime('%Y%m%d-%H%M')}-sd-{end.strftime('%Y%m%d-%H%M')}.mp4"
        )
        return FileResponse(
            out_path,
            media_type="video/mp4",
            filename=name,
            background=BackgroundTask(_cleanup_many, temps),
        )
    except HTTPException:
        _cleanup_many(temps)
        raise
    except Exception as e:  # noqa: BLE001
        _cleanup_many(temps)
        log.warning("download-range gagal: %s", e)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "gagal mengunduh rentang",
        ) from e


async def _find_next_drive_aware(
    stream: Stream, after: datetime, db: AsyncSession
) -> tuple[Segment, datetime] | None:
    """Segmen yang memuat `after`, atau segmen berikutnya (lokal + Drive).

    B-S2: dipakai playback-url dan next-playable agar konsisten, fallback
    tidak lagi lokal saja.
    """
    if after.tzinfo is not None:
        after = after.replace(tzinfo=None)
    res = find_next_playable(stream.id, after, get_settings().recordings_dir)
    if res is not None:
        return res
    if stream.storage_mode in ("drive", "both"):
        for seg in await _all_segments(stream, None, db):
            end = seg.end or seg.start
            if seg.start <= after < end:
                return seg, after
            if seg.start >= after:
                return seg, seg.start
    return None


@router.get("/recordings/{stream_id}/playback-url", response_model=PlaybackUrlOut)
async def playback_url(
    stream_id: int,
    time: datetime,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    if time.tzinfo is not None:
        time = time.replace(tzinfo=None)
    seg = await _containing(stream, time, db)
    if seg is None:
        # B-S2: cari berikutnya dengan pencarian Drive-aware (seperti
        # next-playable), bukan hanya lokal.
        nxt = await _find_next_drive_aware(stream, time, db)
        if nxt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
        seg = nxt[0]
    return {"url": _file_url(stream_id, seg), "expires_at": None}


@router.get("/recordings/{stream_id}/next-playable", response_model=NextPlayableOut)
async def next_playable(
    stream_id: int,
    after: datetime | None = None,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    after = after or datetime.now()
    if after.tzinfo is not None:
        after = after.replace(tzinfo=None)
    res = await _find_next_drive_aware(stream, after, db)
    if res is None:
        return {"available": False, "time": None}
    return {"available": True, "time": res[1].isoformat()}
