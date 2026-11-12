"""Background mirror copier: mode folder-link + rclone (ala fieriindra).

Untuk kamera dengan recording_enabled=True dan storage_mode "both"/"drive",
segmen rekaman yang sudah stabil (tidak berubah 20 detik terakhir) disalin
dari {recordings_dir}/stream_{id}/ ke {local_path}/stream_{id}/ tiap folder
, folder staging lokal yang di-mount ke Google Drive via `rclone mount`.

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
from app.services.disks import camera_rec_dir

log = logging.getLogger("netravision.drive_mirror")

_STABLE_SEC = 20
_INTERVAL_SEC = 30
# Backoff antar percobaan saat staging/Drive mati: 5s, 15s, 30s, maks 60s.
_BACKOFF_SEC = (5, 15, 30, 60)


def _backoff_delay(failures: int) -> int:
    """Penundaan retry setelah `failures` kegagalan berturut-turut."""
    idx = min(max(failures - 1, 0), len(_BACKOFF_SEC) - 1)
    return _BACKOFF_SEC[idx]
_MOUNT_SENTINEL = ".netravision-mount-ok"
_warned_dead: set[str] = set()  # path staging yang sudah diperingatkan mati


def _staging_alive(path: str) -> bool:
    """True bila path staging adalah mount rclone yang masih hidup.

    B-S6: mount rclone yang mati meninggalkan direktori lokal biasa, tanpa
    cek ini file menumpuk di disk lokal dan pengguna mengira sudah di Drive.
    Hidup = mountpoint aktif, atau berisi sentinel yang ditaruh operator.
    """
    if os.path.ismount(path):
        return True
    return os.path.isfile(os.path.join(path, _MOUNT_SENTINEL))


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


async def _mirror_candidates() -> list[tuple[int, str, int | None, str]]:
    """Daftar (stream_id, name, drive_folder_id, rec_dir) kamera yang perlu
    dicerminkan. rec_dir dihitung di dalam sesi via camera_rec_dir
    (rekaman multi-disk) supaya pemakaian di thread latar aman."""
    settings = get_settings()
    async with get_session_factory()() as db:
        res = await db.execute(
            select(Stream).where(
                Stream.recording_enabled.is_(True),
                Stream.storage_mode.in_(["both", "drive"]),
            )
        )
        return [
            (
                s.id,
                s.name,
                s.drive_folder_id,
                camera_rec_dir(s, settings.recordings_dir),
            )
            for s in res.scalars().all()
        ]


def _prune_staging(src_dir: str, dst_base: str, stream_id: int) -> None:
    """Bersihkan staging lama: file yang sumbernya sudah tak ada, atau lebih
    tua dari drive_retention_days. Hanya jalan bila mount hidup dan sumber ada.
    src_dir = direktori segmen sebenarnya (camera_rec_dir); tujuan staging
    tetap {dst_base}/stream_{id}.
    """
    from datetime import datetime as _dt

    settings = get_settings()
    src = src_dir
    dst = os.path.join(dst_base, f"stream_{stream_id}")
    if not os.path.isdir(src) or not os.path.isdir(dst):
        return
    try:
        src_names = set(os.listdir(src))
        cutoff = _dt.now().timestamp() - settings.drive_retention_days * 86400
    except OSError:
        return
    for fn in os.listdir(dst):
        tpath = os.path.join(dst, fn)
        try:
            if not os.path.isfile(tpath):
                continue
            if fn not in src_names or os.path.getmtime(tpath) < cutoff:
                os.remove(tpath)
                log.info("mirror: staging lama dihapus %s", tpath)
        except OSError as e:  # noqa: BLE001
            log.warning("mirror: gagal bersihkan staging %s: %s", tpath, e)


def _mirror_one(src_dir: str, dst_base: str, stream_id: int) -> None:
    """Salin segmen stabil satu kamera ke satu folder tujuan.

    src_dir = direktori segmen sebenarnya (camera_rec_dir, multi-disk);
    tujuan staging tetap {dst_base}/stream_{id}.
    """
    settings = get_settings()
    # B-S6: jangan menulis buta ke staging yang mount-nya mati.
    if settings.drive_mirror_require_mount and not _staging_alive(dst_base):
        if dst_base not in _warned_dead:
            _warned_dead.add(dst_base)
            log.warning(
                "mirror: staging %s bukan mount aktif (rclone mount mati?), "
                "penyalinan dilewati sampai mount hidup lagi",
                dst_base,
            )
        return
    _warned_dead.discard(dst_base)
    src = src_dir
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
                continue  # masih ditulis, lewati
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
    _prune_staging(src_dir, dst_base, stream_id)


def _mirror_tick(
    candidates: list[tuple[int, str, int | None, str] | tuple[int, str, int | None]],
    folders: list[tuple[int, str, str]],
) -> None:
    """Satu putaran penyalinan segmen stabil ke tiap folder tujuan.

    Kandidat 4-elemen (stream_id, name, drive_folder_id, rec_dir) dari
    _mirror_candidates; 3-elemen lama tetap diterima (rec_dir diturunkan
    dari settings.recordings_dir, perilaku legacy).
    """
    if not folders:
        return
    settings = get_settings()
    by_id = {fid: path for fid, _name, path in folders}
    default_path = folders[0][2]
    for cand in candidates:
        if len(cand) == 4:
            stream_id, _name, drive_folder_id, rec_dir = cand
        else:
            stream_id, _name, drive_folder_id = cand
            rec_dir = os.path.join(settings.recordings_dir, f"stream_{stream_id}")
        dst_base = by_id.get(drive_folder_id) if drive_folder_id else default_path
        if not dst_base:
            continue
        _mirror_one(rec_dir, dst_base, stream_id)


async def mirror_loop() -> None:
    """Loop latar: tiap 30 detik salin segmen stabil ke folder-folder Drive.

    Staging/Drive mati tidak mematikan loop: kegagalan satu putaran
    dicatat, lalu retry dengan backoff yang membesar (5s, 15s, 30s,
    maks 60s), direset setelah satu putaran sukses. Segmen lokal sumber
    TIDAK pernah dihapus di sini; yang dibersihkan hanya salinan di
    staging (_prune_staging), jadi segmen yang gagal tersalin tetap
    dicoba lagi putaran berikut."""
    failures = 0
    try:
        while True:
            try:
                folders = await _folders()
                if folders:
                    candidates = await _mirror_candidates()
                    if candidates:
                        await asyncio.to_thread(_mirror_tick, candidates, folders)
                failures = 0
            except Exception as e:  # noqa: BLE001
                failures += 1
                delay = _backoff_delay(failures)
                log.warning(
                    "mirror loop gagal (%d kali berturut-turut), "
                    "coba lagi dalam %ds: %s",
                    failures,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)
                continue
            await asyncio.sleep(_INTERVAL_SEC)
    except asyncio.CancelledError:
        pass
