"""Router recordings: 8 endpoint persis kontrak (MIGRATION-MAP §3).

Sumber segmen: lokal (pola deploy/mediamtx.yml) + Google Drive bila
storage_mode stream = drive/both dan drive_enabled (proxy via backend).
"""

import logging
import os
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rbac import require_camera_access, require_roles
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
from app.services.drive import CHUNK, DriveUploader
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


async def _all_segments(
    stream: Stream, day: date | None = None
) -> list[Segment]:
    """Gabungan segmen lokal + Drive (lokal menang bila nama sama)."""
    settings = get_settings()
    segs = list_segments(stream.id, day, settings.recordings_dir)
    if stream.storage_mode in ("drive", "both") and settings.drive_enabled:
        names = {s.name for s in segs}
        try:
            up = DriveUploader(settings)
            folder_id = await up.ensure_folder(stream.name)
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
        except Exception as e:  # noqa: BLE001 — Drive opsional, jangan gagalkan
            log.warning("drive list %s gagal: %s", stream.name, e)
    segs.sort(key=lambda s: s.start)
    _assign_ends(segs)
    return segs


async def _containing(
    stream: Stream, at: datetime
) -> Segment | None:
    """Segmen (lokal/Drive) yang memuat waktu `at`."""
    if at.tzinfo is not None:
        at = at.replace(tzinfo=None)
    for seg in await _all_segments(stream):
        if seg.start > at + _ONE_DAY:
            break
        end = seg.end or seg.start
        if seg.start <= at < end:
            return seg
    return None


async def _serve_segment(
    stream: Stream, seg: Segment, download: bool
) -> FileResponse | StreamingResponse:
    if seg.path and os.path.exists(seg.path):
        if download:
            return FileResponse(
                seg.path,
                media_type="application/octet-stream",
                filename=seg.name,
            )
        return FileResponse(seg.path, media_type="video/mp4")
    # Fallback Drive
    settings = get_settings()
    if not settings.drive_enabled or stream.storage_mode not in ("drive", "both"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "segmen tidak ditemukan")
    up = DriveUploader(settings)
    file_id = seg.drive_file_id
    if not file_id:
        folder_id = await up.ensure_folder(stream.name)
        file_id = await up.find_file(folder_id, seg.name)
    if not file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "segmen tidak ditemukan")

    async def gen():
        start = 0
        while True:
            chunk = await up.stream_drive_file(file_id, start, start + CHUNK - 1)
            if not chunk:
                break
            yield chunk
            if len(chunk) < CHUNK:
                break
            start += CHUNK

    return StreamingResponse(gen(), media_type="video/mp4")


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
    _access: User = Depends(require_camera_access),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    day = day or date.today()
    segs = await _all_segments(stream, day)
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
    _access: User = Depends(require_camera_access),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    segs = await _all_segments(stream, day)
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
    _access: User = Depends(require_camera_access),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    segs = await _all_segments(stream, None)
    return {"dates": sorted({s.start.date().isoformat() for s in segs})}


@router.get("/recordings/{stream_id}/stream")
async def stream_range(
    stream_id: int,
    start: datetime,
    end: datetime | None = None,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_access),
    db: AsyncSession = Depends(get_db),
):
    """Stream video rentang waktu (inline, video/mp4)."""
    stream = await _get_stream(stream_id, db)
    seg = await _containing(stream, start)
    if seg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
    return await _serve_segment(stream, seg, download=False)


@router.get("/recordings/{stream_id}/file")
async def download_file(
    stream_id: int,
    start: datetime,
    end: datetime,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_access),
    db: AsyncSession = Depends(get_db),
):
    """Unduh potongan rekaman (attachment). Rentang harus milik stream ini."""
    if end < start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end < start")
    stream = await _get_stream(stream_id, db)
    seg = await _containing(stream, start)
    if seg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
    return await _serve_segment(stream, seg, download=True)


@router.get("/recordings/{stream_id}/playback-url", response_model=PlaybackUrlOut)
async def playback_url(
    stream_id: int,
    time: datetime,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_access),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    if time.tzinfo is not None:
        time = time.replace(tzinfo=None)
    seg = await _containing(stream, time)
    if seg is None:
        # cari berikutnya
        nxt = find_next_playable(stream.id, time, get_settings().recordings_dir)
        if nxt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
        seg = nxt[0]
    return {"url": _file_url(stream_id, seg), "expires_at": None}


@router.get("/recordings/{stream_id}/next-playable", response_model=NextPlayableOut)
async def next_playable(
    stream_id: int,
    after: datetime | None = None,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_access),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    after = after or datetime.now()
    if after.tzinfo is not None:
        after = after.replace(tzinfo=None)
    # lokal dulu (cepat), lalu gabungan bila drive aktif
    res = find_next_playable(stream.id, after, get_settings().recordings_dir)
    if res is None and stream.storage_mode in ("drive", "both"):
        for seg in await _all_segments(stream, None):
            end = seg.end or seg.start
            if seg.start <= after < end:
                res = (seg, after)
                break
            if seg.start >= after:
                res = (seg, seg.start)
                break
    if res is None:
        return {"available": False, "time": None}
    return {"available": True, "time": res[1].isoformat()}
