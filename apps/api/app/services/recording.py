"""Service rekaman: pindai segmen MediaMTX, linimasa, next-playable, retensi.

Layout segmen, SUMBER KEBENARAN: deploy/mediamtx.yml (recordPath):
    {recordings_dir}/stream_{stream_id}/YYYY-MM-DD_HH-MM-SS-%f.mp4

`recordings_dir` HARUS menunjuk ke volume yang sama dengan yang ditulis
MediaMTX (di deploy: volume recordings di-mount ke path ini di container api).
Hanya path `stream_{id}` (main) yang direkam; sub stream tidak direkam.

Waktu pada nama file = waktu lokal server; perbandingan dilakukan konsisten
dalam zona yang sama (naive).
"""

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.streams import Stream

log = logging.getLogger("netravision.recording")

SEGMENT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})-(\d{1,6})\.mp4$")
SEGMENT_FALLBACK_SEC = 600  # recordSegmentDuration MediaMTX
SCAN_AHEAD_DAYS = 8


@dataclass
class Segment:
    start: datetime
    path: str
    size: int
    name: str = ""
    end: datetime | None = field(default=None)
    drive_file_id: str | None = field(default=None)  # terisi bila dari Drive


def _recordings_dir(explicit: str | None = None) -> str:
    return explicit or get_settings().recordings_dir


def _stream_dir(stream_id: int, recordings_dir: str) -> str:
    return os.path.join(recordings_dir, f"stream_{stream_id}")


def _segment_dir(
    stream_id: int, recordings_dir: str, stream: Stream | None = None
) -> str:
    """Direktori segmen: via camera_rec_dir bila stream diberikan
    (rekaman multi-disk), bila tidak legacy {recordings_dir}/stream_{id}.

    Impor camera_rec_dir dilakukan di sini (bukan di atas) untuk
    menghindari impor sirkular: disks memakai SEGMENT_RE dari modul ini.
    """
    if stream is not None:
        from app.services.disks import camera_rec_dir  # noqa: PLC0415

        return camera_rec_dir(stream, recordings_dir)
    return _stream_dir(stream_id, recordings_dir)


def parse_segment_name(name: str) -> datetime | None:
    """'2026-11-02_10-00-00-000000.mp4' -> datetime, atau None bila tak cocok."""
    m = SEGMENT_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(
            f"{m.group(1)}_{m.group(2)}-{m.group(3)}", "%Y-%m-%d_%H-%M-%S-%f"
        )
    except ValueError:
        return None


def _assign_ends(segments: list[Segment]) -> None:
    for i, seg in enumerate(segments):
        if i + 1 < len(segments):
            nxt = segments[i + 1].start
            seg.end = min(nxt, seg.start + timedelta(seconds=SEGMENT_FALLBACK_SEC))
        else:
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(seg.path))
            except OSError:
                # B-T5: segmen Drive punya path="" (mtime tak terbaca), jangan
                # end=start (durasi 0, tak bisa diputar). Pakai durasi segmen
                # yang wajar (recordSegmentDuration MediaMTX).
                mtime = seg.start + timedelta(seconds=SEGMENT_FALLBACK_SEC)
            seg.end = max(seg.start, mtime)


def list_segments(
    stream_id: int,
    day: date | None = None,
    recordings_dir: str | None = None,
    stream: Stream | None = None,
) -> list[Segment]:
    """Pindai segmen stream; bila `day` diisi hanya tanggal itu (waktu lokal).

    Bila `stream` diberikan, direktori dibaca via camera_rec_dir (rekaman
    multi-disk); bila tidak, legacy {recordings_dir}/stream_{id}.
    """
    root = _recordings_dir(recordings_dir)
    d = _segment_dir(stream_id, root, stream)
    out: list[Segment] = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for name in names:
        start = parse_segment_name(name)
        if start is None:
            continue
        if day is not None and start.date() != day:
            continue
        path = os.path.join(d, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        out.append(Segment(start=start, path=path, size=size, name=name))
    out.sort(key=lambda s: s.start)
    _assign_ends(out)
    return out


def build_timeline(
    stream_id: int,
    day: date,
    recordings_dir: str | None = None,
    stream: Stream | None = None,
) -> dict:
    """Linimasa satu hari. `events` diisi modul AI (Fase 6); sekarang []."""
    segments = list_segments(stream_id, day, recordings_dir, stream=stream)
    return {
        "date": day.isoformat(),
        "entries": [
            {
                "start": s.start.isoformat(),
                "end": s.end.isoformat() if s.end else s.start.isoformat(),
                "has_event": False,
            }
            for s in segments
        ],
        "events": [],
    }


def find_next_playable(
    stream_id: int,
    after: datetime,
    recordings_dir: str | None = None,
    stream: Stream | None = None,
) -> tuple[Segment, datetime] | None:
    """Segmen yang memuat `after`, atau segmen berikutnya. None bila tak ada."""
    if after.tzinfo is not None:
        after = after.replace(tzinfo=None)  # samakan dengan waktu lokal file
    for delta in range(SCAN_AHEAD_DAYS):
        day = (after + timedelta(days=delta)).date()
        for seg in list_segments(stream_id, day, recordings_dir, stream=stream):
            end = seg.end or seg.start
            if seg.start <= after < end:
                return seg, after
            if seg.start >= after:
                return seg, seg.start
    return None


async def apply_retention(db: AsyncSession, recordings_dir: str | None = None) -> int:
    """Hapus segmen lokal lebih tua dari retention_days per stream.

    Memakai kolom `retention_days` yang sudah ada di model Stream
    (default 7 hari = 168 jam, selaras recordDeleteAfter MediaMTX).

    B-T2: kamera mode drive/both HANYA dihapus bila segmen sudah tercatat
    ter-upload di drive_uploads. Tanpa bukti upload, salinan lokal adalah
    satu-satunya salinan, dipertahankan walau kedaluwarsa.
    """
    from app.models.drive import DriveUpload

    root = _recordings_dir(recordings_dir)
    now = datetime.now()
    result = await db.execute(
        select(Stream).where(Stream.is_active.is_(True), Stream.recording_enabled.is_(True))
    )
    deleted = 0
    kept_unuploaded = 0
    for stream in result.scalars().all():
        cutoff = now - timedelta(days=stream.retention_days or 7)
        uploaded: set[str] | None = None
        if stream.storage_mode in ("drive", "both"):
            res = await db.execute(
                select(DriveUpload.segment_name).where(
                    DriveUpload.stream_id == stream.id
                )
            )
            uploaded = {r[0] for r in res.all()}
        for seg in list_segments(stream.id, None, root, stream=stream):
            if seg.start < cutoff:
                if uploaded is not None and seg.name not in uploaded:
                    kept_unuploaded += 1
                    continue
                try:
                    os.remove(seg.path)
                    deleted += 1
                except OSError as e:
                    log.warning("gagal hapus segmen %s: %s", seg.path, e)
    if deleted:
        log.info("retensi: %d segmen lama dihapus", deleted)
    if kept_unuploaded:
        log.info(
            "retensi: %d segmen kedaluwarsa dipertahankan (belum ter-upload ke Drive)",
            kept_unuploaded,
        )
    return deleted


def list_dates(
    stream_id: int,
    recordings_dir: str | None = None,
    stream: Stream | None = None,
) -> list[str]:
    """Tanggal-tanggal (ISO) yang punya segmen, menaik."""
    days = {s.start.date().isoformat() for s in list_segments(stream_id, None, recordings_dir, stream=stream)}
    return sorted(days)
