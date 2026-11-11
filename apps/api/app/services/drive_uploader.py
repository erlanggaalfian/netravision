"""Background uploader: segmen rekaman -> Google Drive via rclone copyto.

Untuk tiap kamera (recording_enabled=True, storage_mode drive/both),
segmen yang sudah stabil (tidak berubah 20 detik) dan belum tercatat di
drive_uploads di-upload ke folder Drive kamera
(streams.drive_folder_id atau folder pertama).

Berjalan berdampingan dengan drive_mirror (jalur rclone mount): bila
kamera sudah ter-upload via API, mirror melewatinya agar tidak dobel.
"""

import asyncio
import logging
import os
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.drive import GoogleDriveFolder
from app.models.streams import Stream
from app.services import gdrive_rclone as gr
from app.services.recording import parse_segment_name

log = logging.getLogger("netravision.drive_uploader")

_STABLE_SEC = 20
_INTERVAL_SEC = 60


async def _uploaded_names(stream_id: int, folder_id: str | None = None) -> set[str]:
    """Nama segmen yang sudah ter-upload untuk satu kamera.

    B-S5: dikunci per folder tujuan (kolom drive_uploads.folder_id). Segmen
    yang ter-upload ke folder lama TIDAK dianggap sudah ter-upload ke folder
    baru, sehingga ganti folder memicu re-upload.
    """
    from app.models.drive import DriveUpload  # noqa: PLC0415

    async with get_session_factory()() as db:
        q = select(DriveUpload.segment_name).where(
            DriveUpload.stream_id == stream_id
        )
        if folder_id is not None:
            q = q.where(DriveUpload.folder_id == folder_id)
        res = await db.execute(q)
        return {r[0] for r in res.all()}


async def _mark_uploaded(stream_id: int, segment_name: str, folder_id: str) -> None:
    from app.models.drive import DriveUpload  # noqa: PLC0415

    async with get_session_factory()() as db:
        db.add(
            DriveUpload(
                stream_id=stream_id,
                segment_name=segment_name,
                folder_id=folder_id,
            )
        )
        await db.commit()


async def _camera_targets() -> list[tuple[int, str, str]]:
    """(stream_id, nama_kamera, folder_drive_id) untuk kamera mode drive/both."""
    async with get_session_factory()() as db:
        folders = (
            (await db.execute(select(GoogleDriveFolder).order_by(GoogleDriveFolder.id)))
            .scalars()
            .all()
        )
        if not folders:
            return []
        by_id = {f.id: f.folder_id for f in folders}
        default_fid = folders[0].folder_id
        res = await db.execute(
            select(Stream.id, Stream.name, Stream.drive_folder_id).where(
                Stream.recording_enabled.is_(True),
                Stream.storage_mode.in_(["both", "drive"]),
            )
        )
        out = []
        for sid, name, fid in res.all():
            drive_fid = by_id.get(fid) if fid else None
            out.append((sid, name or f"Kamera {sid}", drive_fid or default_fid))
        return out


def _stable_segments(stream_id: int, recordings_dir: str) -> list[tuple[str, str]]:
    """[(nama_file, path)] segmen stabil di stream dir."""
    sdir = os.path.join(recordings_dir, f"stream_{stream_id}")
    if not os.path.isdir(sdir):
        return []
    now = time.time()
    out = []
    for name in sorted(os.listdir(sdir)):
        if not name.endswith(".mp4"):
            continue
        if parse_segment_name(name) is None:
            continue
        path = os.path.join(sdir, name)
        try:
            if now - os.path.getmtime(path) < _STABLE_SEC:
                continue
            if os.path.getsize(path) == 0:
                continue
        except OSError:
            continue
        out.append((name, path))
    return out


async def _upload_once() -> None:
    status = await gr.connection_status()
    if not status.get("connected"):
        return
    settings = get_settings()
    recordings_dir = settings.recordings_dir
    for sid, cam_name, folder_id in await _camera_targets():
        try:
            done = await _uploaded_names(sid, folder_id)
        except Exception as e:  # noqa: BLE001
            log.warning("uploader: baca drive_uploads gagal: %s", e)
            continue
        for seg_name, seg_path in _stable_segments(sid, recordings_dir):
            if seg_name in done:
                continue
            remote = f"{cam_name}/{seg_name}"
            try:
                await gr.upload_segment(seg_path, folder_id, remote)
                await _mark_uploaded(sid, seg_name, folder_id)
                log.info("uploader: %s -> drive (%s)", seg_name, cam_name)
            except Exception as e:  # noqa: BLE001
                log.warning("uploader: gagal %s: %s", seg_name, e)
                break  # coba lagi putaran berikutnya


async def upload_loop() -> None:
    log.info("drive_uploader: mulai")
    while True:
        try:
            await _upload_once()
        except Exception as e:  # noqa: BLE001
            log.warning("drive_uploader: %s", e)
        await asyncio.sleep(_INTERVAL_SEC)
