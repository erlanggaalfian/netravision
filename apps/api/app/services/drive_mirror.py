"""Background mirror copier: mode folder-link + rclone (ala fieriindra).

Untuk kamera dengan recording_enabled=True dan storage_mode "both"/"drive",
segmen rekaman yang sudah stabil (tidak berubah 20 detik terakhir) disalin
dari {recordings_dir}/stream_{id}/ ke {local_path}/stream_{id}/ tiap folder
— folder staging lokal yang di-mount ke Google Drive via `rclone mount`.

Multi-tautan: tiap folder punya local_path sendiri. Kamera memilih folder
via streams.drive_folder_id; NULL = folder pertama (default).

Berbeda dari uploader OAuth multi-akun (app/services/drive.py): mode ini
tidak memakai API Drive sama sekali, hanya penyalinan file lokal.

Hanya berjalan bila ada folder terkonfigurasi dengan path lokal
(lihat lifespan app/main.py).
"""

import asyncio
import logging
import os
import shutil
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.drive import GoogleDriveFolder
from app.models.streams import Stream

log = logging.getLogger("netravision.drive_mirror")

_STABLE_SEC = 20
_INTERVAL_SEC = 30


async def _folders() -> list[tuple[int, str, str]]:
    """Daftar (id, nama, local_path) folder tujuan yang punya path lokal."""
    settings = get_settings()
    default_path = (settings.gdrive_record_path or "").rstrip("/")
    async with get_session_factory()() as db:
        res = await db.execute(select(GoogleDriveFolder).order_by(GoogleDriveFolder.id))
        out = []
        for f in res.scalars().all():
            path = (f.local_path or "").rstrip("/") or default_path
            if path:
                out.append((f.id, f.folder_name or f"Folder {f.id}", path))
        return out


async def _mirror_candidates() -> list[tuple[int, str, int | None]]:
    """Daftar (stream_id, name, drive_folder_id) kamera yang perlu dicerminkan."""
    async with get_session_factory()() as db:
        res = await db.execute(
            select(Stream.id, Stream.name, Stream.drive_folder_id).where(
                Stream.recording_enabled.is_(True),
                Stream.storage_mode.in_(["both", "drive"]),
            )
        )
        return [(sid, name, fid) for sid, name, fid in res.all()]


def _mirror_one(src_base: str, dst_base: str, stream_id: int) -> None:
    """Salin segmen stabil satu kamera ke satu folder tujuan."""
    src = os.path.join(src_base, f"stream_{stream_id}")
    if not os.path.isdir(src):
        return
    dst = os.path.join(dst_base, f"stream_{stream_id}")
    try:
        entries = os.listdir(src)
    except OSError:
        return
    for fn in entries:
        spath = os.path.join(src, fn)
        try:
            if not os.path.isfile(spath):
                continue
            if time.time() - os.path.getmtime(spath) < _STABLE_SEC:
                continue  # masih ditulis — lewati
            tpath = os.path.join(dst, fn)
            if os.path.exists(tpath) and os.path.getsize(tpath) == os.path.getsize(
                spath
            ):
                continue  # sudah tercermin
            os.makedirs(dst, exist_ok=True)
            shutil.copy2(spath, tpath)
            log.info("mirror stream_%s -> %s: %s tersalin", stream_id, dst_base, fn)
        except OSError as e:  # noqa: BLE001
            log.warning("mirror stream_%s gagal menyalin %s: %s", stream_id, fn, e)


def _mirror_tick(
    candidates: list[tuple[int, str, int | None]],
    folders: list[tuple[int, str, str]],
) -> None:
    """Satu putaran penyalinan segmen stabil ke tiap folder tujuan."""
    if not folders:
        return
    settings = get_settings()
    src_base = settings.recordings_dir
    by_id = {fid: path for fid, _name, path in folders}
    default_path = folders[0][2]
    for stream_id, _name, drive_folder_id in candidates:
        dst_base = by_id.get(drive_folder_id) if drive_folder_id else default_path
        if not dst_base:
            continue
        _mirror_one(src_base, dst_base, stream_id)


async def mirror_loop() -> None:
    """Loop latar: tiap 30 detik salin segmen stabil ke folder-folder Drive."""
    try:
        while True:
            try:
                folders = await _folders()
                if folders:
                    candidates = await _mirror_candidates()
                    if candidates:
                        await asyncio.to_thread(_mirror_tick, candidates, folders)
            except Exception as e:  # noqa: BLE001
                log.warning("mirror loop gagal: %s", e)
            await asyncio.sleep(_INTERVAL_SEC)
    except asyncio.CancelledError:
        pass
