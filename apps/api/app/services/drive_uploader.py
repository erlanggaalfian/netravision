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
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.drive import GoogleDriveFolder
from app.models.streams import Stream
from app.services import gdrive_rclone as gr
from app.services.disks import camera_rec_dirs
from app.services.recording import parse_segment_name

log = logging.getLogger("netravision.drive_uploader")

_STABLE_SEC = 20
_INTERVAL_SEC = 60
# Backoff antar percobaan saat Drive mati: membesar 5s, 15s, 30s, maks 60s.
_BACKOFF_SEC = (5, 15, 30, 60)

# Temuan 3.16: kestabilan segmen tidak cukup dari mtime saja. Catat
# (mtime, size) saat pertama terlihat; segmen baru dianggap stabil bila
# pada putaran berikut (masih) punya mtime+size yang sama DAN umurnya
# sudah >= _STABLE_SEC. Penulis MediaMTX yang stall >20 dtk tidak lagi
# membuat segmen setengah jadi ter-upload lalu terhapus.
_SEEN_STABLE: dict[str, tuple[float, int, float]] = {}


def _is_stable(path: str, now: float) -> bool:
    """True bila file tidak berubah sejak pengecekan putaran sebelumnya.

    Return False pada pandangan pertama (baru dicatat), True bila
    (mtime, size) sama seperti yang dicatat sebelumnya dan umur file
    sudah >= _STABLE_SEC.
    """
    try:
        st = os.stat(path)
    except OSError:
        return False
    if st.st_size == 0:
        return False
    if now - st.st_mtime < _STABLE_SEC:
        return False
    prev = _SEEN_STABLE.get(path)
    if prev is None or prev[0] != st.st_mtime or prev[1] != st.st_size:
        _SEEN_STABLE[path] = (st.st_mtime, st.st_size, now)
        if len(_SEEN_STABLE) > 10000:
            cutoff = now - 3600
            for k, v in list(_SEEN_STABLE.items()):
                if v[2] < cutoff:
                    del _SEEN_STABLE[k]
        return False
    return True


def _backoff_delay(failures: int) -> int:
    """Penundaan retry setelah `failures` kegagalan berturut-turut."""
    idx = min(max(failures - 1, 0), len(_BACKOFF_SEC) - 1)
    return _BACKOFF_SEC[idx]


async def _uploaded_names(
    stream_id: int, folder_name: str | None = None, names: list[str] | None = None
) -> set[str]:
    """Nama segmen yang sudah ter-upload untuk satu kamera.

    B-S5: dikunci per folder tujuan (kolom drive_uploads.folder_name).
    Segmen yang ter-upload ke folder lama TIDAK dianggap sudah
    ter-upload ke folder baru, sehingga ganti folder memicu re-upload.

    2.3: bila `names` diisi, query dibatasi ke nama-nama itu
    (WHERE segment_name IN (...)), bukan memuat seluruh jejak kamera
    ke RAM tiap putaran. Tanpa `names`, perilaku lama dipertahankan
    untuk pemanggil yang memang butuh seluruh jejak.
    """
    from app.models.drive import DriveUpload  # noqa: PLC0415

    async with get_session_factory()() as db:
        q = select(DriveUpload.segment_name).where(
            DriveUpload.stream_id == stream_id
        )
        if folder_name is not None:
            q = q.where(DriveUpload.folder_name == folder_name)
        if names is not None:
            if not names:
                return set()
            q = q.where(DriveUpload.segment_name.in_(names))
        res = await db.execute(q)
        return {r[0] for r in res.all()}


async def _mark_uploaded(stream_id: int, segment_name: str, folder_name: str) -> None:
    """Catat jejak upload. 2.1: INSERT ... ON CONFLICT DO NOTHING
    (unique (stream_id, folder_name, segment_name)) supaya dua loop
    yang balapan tidak membuat jejak ganda. on_conflict_do_nothing
    hanya ada di insert dialek-spesifik, jadi konstruktor dipilih
    dari dialek engine (postgresql di produksi, sqlite di tes)."""
    from app.models.drive import DriveUpload  # noqa: PLC0415
    from sqlalchemy.dialects import postgresql as _pg
    from sqlalchemy.dialects import sqlite as _lite

    async with get_session_factory()() as db:
        dialect = (db.bind.dialect.name if db.bind is not None else "postgresql")
        _insert = _pg.insert if dialect == "postgresql" else _lite.insert
        stmt = (
            _insert(DriveUpload)
            .values(
                stream_id=stream_id,
                segment_name=segment_name,
                folder_name=folder_name,
            )
            .on_conflict_do_nothing()
        )
        await db.execute(stmt)
        await db.commit()


async def prune_drive_upload_traces(db, days: int = 90) -> int:
    """2.2: hapus jejak upload lebih tua dari `days` hari.

    Jejak hanya dipakai untuk (a) mencegah upload ganda segmen lokal
    yang masih ada, dan (b) EXISTS di daftar kamera Putar Ulang.
    Segmen lokal dihapus setelah ter-upload (perintah user 2026-11-17)
    dan segmen Drive ikut retensi drive_retention_days (default 30
    hari), jadi jejak lebih tua dari 90 hari tidak lagi berguna untuk
    keduanya. Default 90 hari memberi margin 3x dari retensi Drive.
    Dipanggil harian dari _retention_loop (main.py).
    """
    from app.models.drive import DriveUpload  # noqa: PLC0415

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # synchronize_session=False: jangan evaluasi WHERE di Python untuk
    # objek di sesi (di SQLite datetime kembali naive sehingga
    # perbandingan naive vs aware melempar TypeError); sesi ini
    # langsung di-commit dan dibuang sesudahnya.
    res = await db.execute(
        delete(DriveUpload)
        .where(DriveUpload.uploaded_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    n = res.rowcount or 0
    if n:
        log.info("retensi jejak upload: %d baris drive_uploads dihapus", n)
    return n


async def _camera_targets() -> list[tuple[int, str, str, list[str]]]:
    """(stream_id, nama_kamera, folder_drive_nama, rec_dirs) untuk kamera
    mode drive/both. rec_dirs dihitung di dalam sesi via camera_rec_dirs
    (rekaman multi-disk): direktori main stream_{id} + sub
    stream_{id}_sub, supaya segmen baru dari substream ikut ter-upload
    (perintah user 2026-11-14: rekaman dari substream) dan segmen lama
    dari main tetap ter-upload.

    folder_drive_nama adalah NAMA folder (mis. netravision), BUKAN ID Drive.
    rclone membaca jalur sebagai nama folder; ID Drive yang dipakai sebagai
    jalur justru membuat rclone membuat folder baru bernama ID itu.
    Nama yang sama dipakai sebagai kunci jejak di drive_uploads.folder_name
    (2.9: kolom itu dulu bernama folder_id), supaya ganti folder memicu
    re-upload ke folder yang benar.
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
                    camera_rec_dirs(s, settings.recordings_dir),
                )
            )
        return out


def _stable_segments(sdir: str) -> list[tuple[str, str]]:
    """[(nama_file, path)] segmen stabil di direktori segmen kamera.

    sdir = direktori segmen sebenarnya (camera_rec_dir, multi-disk).
    Dipanggil sekali per direktori (main + sub) oleh _upload_once.
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
        # Temuan 3.16: stabil = umur >= 20 dtk DAN (mtime, size) sama
        # seperti putaran sebelumnya (bukan hanya mtime).
        if not _is_stable(path, now):
            continue
        out.append((name, path))
    return out


async def _upload_once() -> int:
    """Satu putaran upload. Return jumlah segmen yang gagal di-upload.

    Temuan 3.7: sebelumnya kegagalan per segmen ditelan (`break` lalu
    return normal) sehingga `failures` di loop luar selalu 0 dan
    backoff tidak pernah jalan. Kini kegagalan dihitung dan
    dikembalikan; satu segmen gagal tidak lagi memblokir segmen lain
    (`continue`, bukan `break`).
    """
    from app.services.upload_claims import is_claimed, release_claim, try_claim

    status = await gr.connection_status()
    if not status.get("connected"):
        return 1
    failures = 0
    for sid, cam_name, folder_name, rec_dirs in await _camera_targets():
        # Gabungkan segmen stabil dari direktori main + sub; bila nama
        # segmen yang sama ada di keduanya (masa peralihan), yang dari
        # sub yang dipakai (ditulis belakangan).
        pending: dict[str, str] = {}
        for rec_dir in rec_dirs:
            # P1: _stable_segments memindai direktori (os.listdir +
            # os.stat per file), jalankan di thread supaya tidak
            # memblokir event loop. Fungsi sync-nya sendiri dibiarkan
            # sync (dipakai dari konteks sync lewat to_thread).
            for seg_name, seg_path in await asyncio.to_thread(
                _stable_segments, rec_dir
            ):
                pending[seg_name] = seg_path
        if not pending:
            continue
        try:
            # 2.3: cek jejak HANYA untuk segmen lokal yang ada
            # (WHERE segment_name IN (...)), bukan seluruh riwayat
            # upload kamera (11 ribu baris untuk satu kamera).
            done = await _uploaded_names(sid, folder_name, list(pending))
        except Exception as e:  # noqa: BLE001
            log.warning("uploader: baca drive_uploads gagal: %s", e)
            continue
        for seg_name in done:
            pending.pop(seg_name, None)
        for seg_name, seg_path in pending.items():
            # Temuan 3.2: segmen yang sedang diproses jalur mirror /
            # OAuth dilewati putaran ini.
            if is_claimed(sid, seg_name):
                continue
            remote = f"{cam_name}/{seg_name}"
            if not try_claim(sid, seg_name, "uploader"):
                continue
            try:
                await gr.upload_segment(seg_path, folder_name, remote)
                await _mark_uploaded(sid, seg_name, folder_name)
                log.info("uploader: %s -> drive (%s)", seg_name, cam_name)
            except Exception as e:  # noqa: BLE001
                log.warning("uploader: gagal %s: %s", seg_name, e)
                failures += 1
                continue
            finally:
                release_claim(sid, seg_name, "uploader")
            # Hapus lokal setelah ter-upload (perintah user 2026-11-17):
            # segmen yang sama bisa ada di main dan sub, hapus di semua
            # direktori rekaman kamera ini. Gagal hapus hanya dicatat,
            # bukan kegagalan upload (upload sudah tercatat di
            # drive_uploads).
            for rec_dir in rec_dirs:
                try:
                    p = os.path.join(rec_dir, seg_name)
                    if os.path.isfile(p):
                        os.remove(p)
                        log.info("uploader: lokal dihapus %s", p)
                except OSError as e:  # noqa: BLE001
                    log.warning("uploader: gagal hapus lokal %s: %s", p, e)
    return failures


async def upload_loop(initial_delay: float = 0) -> None:
    """Loop latar: tiap 60 detik coba upload segmen stabil.

    Drive mati tidak mematikan loop: kegagalan satu putaran dicatat,
    lalu retry dengan backoff yang membesar (5s, 15s, 30s, maks 60s),
    direset ke interval normal setelah satu putaran sukses. Segmen lokal
    DIHAPUS setelah ter-upload dan tercatat di drive_uploads (perintah
    user 2026-11-17), jadi segmen yang gagal tetap dicoba lagi putaran
    berikut karena jejaknya belum tercatat.

    Area 5, 5.11: `initial_delay` menunda putaran pertama supaya tidak
    semua loop start bersamaan saat API baru naik.
    """
    from app.services.loop_health import (
        record_failure,
        record_success,
        record_tick,
    )

    log.info("drive_uploader: mulai")
    failures = 0
    try:
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            started = time.monotonic()
            record_tick("drive_uploader")
            try:
                n_failed = await _upload_once()
                if n_failed:
                    # Temuan 3.7: kegagalan segmen kini dihitung, bukan
                    # ditelan, supaya backoff benar-benar jalan.
                    failures += 1
                    delay = _backoff_delay(failures)
                    log.warning(
                        "drive_uploader: %d segmen gagal, backoff %ds "
                        "(%d putaran gagal berturut-turut)",
                        n_failed, delay, failures,
                    )
                    record_failure(
                        "drive_uploader",
                        RuntimeError(f"{n_failed} segmen gagal di-upload"),
                    )
                    await asyncio.sleep(delay)
                    continue
                failures = 0
                record_success(
                    "drive_uploader", (time.monotonic() - started) * 1000
                )
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
                record_failure("drive_uploader", e)
                await asyncio.sleep(delay)
                continue
            await asyncio.sleep(_INTERVAL_SEC)
    except asyncio.CancelledError:
        pass
