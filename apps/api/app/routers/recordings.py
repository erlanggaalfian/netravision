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
