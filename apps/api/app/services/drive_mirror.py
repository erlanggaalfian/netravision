"""Background mirror copier: mode folder-link + rclone (ala fieriindra).

Untuk kamera dengan recording_enabled=True dan storage_mode="both",
segmen rekaman yang sudah stabil (tidak berubah 20 detik terakhir) disalin
dari {recordings_dir}/stream_{id}/ ke {gdrive_record_path}/stream_{id}/
— folder staging lokal yang di-mount ke Google Drive via `rclone mount`.

Berbeda dari uploader OAuth multi-akun (app/services/drive.py): mode ini
tidak memakai API Drive sama sekali, hanya penyalinan file lokal.

Hanya berjalan bila env GDRIVE_RECORD_PATH diset (lihat lifespan app/main.py).
"""

import asyncio
import logging
import os
import shutil
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.streams import Stream

log = logging.getLogger("netravision.drive_mirror")

_STABLE_SEC = 20
_INTERVAL_SEC = 30


async def _mirror_candidates() -> list[tuple[int, str]]:
    """Daftar (stream_id, name) kamera yang perlu dicerminkan."""
    async with get_session_factory()() as db:
        res = await db.execute(
            select(Stream.id, Stream.name).where(
                Stream.recording_enabled.is_(True),
                Stream.storage_mode == "both",
            )
        )
        return [(sid, name) for sid, name in res.all()]


def _mirror_tick(candidates: list[tuple[int, str]]) -> None:
    """Satu putaran penyalinan segmen stabil ke staging rclone."""
    settings = get_settings()
    src_base = settings.recordings_dir
    dst_base = (settings.gdrive_record_path or "").rstrip("/")
    if not dst_base:
        return
    for stream_id, _name in candidates:
        src = os.path.join(src_base, f"stream_{stream_id}")
        if not os.path.isdir(src):
            continue
        dst = os.path.join(dst_base, f"stream_{stream_id}")
        try:
            entries = os.listdir(src)
        except OSError:
            continue
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
                log.info("mirror stream_%s: %s tersalin", stream_id, fn)
            except OSError as e:  # noqa: BLE001
                log.warning("mirror stream_%s gagal menyalin %s: %s", stream_id, fn, e)


async def mirror_loop() -> None:
    """Loop latar: tiap 30 detik salin segmen stabil ke staging rclone."""
    try:
        while True:
            try:
                candidates = await _mirror_candidates()
                if candidates:
                    await asyncio.to_thread(_mirror_tick, candidates)
            except Exception as e:  # noqa: BLE001
                log.warning("mirror loop gagal: %s", e)
            await asyncio.sleep(_INTERVAL_SEC)
    except asyncio.CancelledError:
        pass
