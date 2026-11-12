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
from app.services.disks import camera_rec_dir
from app.services.recording import parse_segment_name

log = logging.getLogger("netravision.drive_uploader")

_STABLE_SEC = 20
_INTERVAL_SEC = 60
# Backoff antar percobaan saat Drive mati: membesar 5s, 15s, 30s, maks 60s.
_BACKOFF_SEC = (5, 15, 30, 60)


def _backoff_delay(failures: int) -> int:
    """Penundaan retry setelah `failures` kegagalan berturut-turut."""
    idx = min(max(failures - 1, 0), len(_BACKOFF_SEC) - 1)
    return _BACKOFF_SEC[idx]


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


async def _camera_targets() -> list[tuple[int, str, str, str]]:
    """(stream_id, nama_kamera, folder_drive_nama, rec_dir) untuk kamera
    mode drive/both. rec_dir dihitung di dalam sesi via camera_rec_dir
    (rekaman multi-disk).

    folder_drive_nama adalah NAMA folder (mis. netravision), BUKAN ID Drive.
    rclone membaca jalur sebagai nama folder; ID Drive yang dipakai sebagai
    jalur justru membuat rclone membuat folder baru bernama ID itu.
    Nama yang sama dipakai sebagai kunci jejak di drive_uploads, supaya
    ganti folder memicu re-upload ke folder yang benar.
    """
    settings = get_settings()
    async with get_session_factory()() as db:
        folders = (
            (await db.execute(select(GoogleDriveFolder).order_by(GoogleDriveFolder.id)))
            .scalars()
            .all()
        )
        if not folders:
            return []
        by_id = {f.id: (f.folder_name or "") for f in folders}
        default_name = folders[0].folder_name or ""
        res = await db.execute(
            select(Stream).where(
                Stream.recording_enabled.is_(True),
                Stream.storage_mode.in_(["both", "drive"]),
            )
        )
        out = []
        for s in res.scalars().all():
            drive_name = by_id.get(s.drive_folder_id) if s.drive_folder_id else None
            drive_name = drive_name or default_name
            if not drive_name:
                log.warning(
                    "uploader: kamera %s tanpa nama folder Drive, dilewati",
                    s.name,
                )
                continue
            out.append(
                (
                    s.id,
                    s.name or f"Kamera {s.id}",
                    drive_name,
                    camera_rec_dir(s, settings.recordings_dir),
                )
            )
        return out


def _stable_segments(sdir: str) -> list[tuple[str, str]]:
    """[(nama_file, path)] segmen stabil di direktori segmen kamera.

    sdir = direktori segmen sebenarnya (camera_rec_dir, multi-disk).
    """
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
    for sid, cam_name, folder_name, rec_dir in await _camera_targets():
        try:
            done = await _uploaded_names(sid, folder_name)
        except Exception as e:  # noqa: BLE001
            log.warning("uploader: baca drive_uploads gagal: %s", e)
            continue
        for seg_name, seg_path in _stable_segments(rec_dir):
            if seg_name in done:
                continue
            remote = f"{cam_name}/{seg_name}"
            try:
                await gr.upload_segment(seg_path, folder_name, remote)
                await _mark_uploaded(sid, seg_name, folder_name)
                log.info("uploader: %s -> drive (%s)", seg_name, cam_name)
            except Exception as e:  # noqa: BLE001
                log.warning("uploader: gagal %s: %s", seg_name, e)
                break  # coba lagi putaran berikutnya


async def upload_loop() -> None:
    """Loop latar: tiap 60 detik coba upload segmen stabil.

    Drive mati tidak mematikan loop: kegagalan satu putaran dicatat,
    lalu retry dengan backoff yang membesar (5s, 15s, 30s, maks 60s),
    direset ke interval normal setelah satu putaran sukses. Segmen lokal
    TIDAK pernah dihapus di sini; yang dicatat hanya jejak ter-upload di
    drive_uploads, jadi segmen yang gagal tetap dicoba lagi putaran
    berikut."""
    log.info("drive_uploader: mulai")
    failures = 0
    while True:
        try:
            await _upload_once()
            failures = 0
        except Exception as e:  # noqa: BLE001
            failures += 1
            delay = _backoff_delay(failures)
            log.warning(
                "drive_uploader: putaran gagal (%d kali berturut-turut), "
                "coba lagi dalam %ds: %s",
                failures,
                delay,
                e,
            )
            await asyncio.sleep(delay)
            continue
        await asyncio.sleep(_INTERVAL_SEC)
