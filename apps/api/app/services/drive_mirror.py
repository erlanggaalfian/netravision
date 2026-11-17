"""Background mirror copier: mode folder-link + rclone (ala fieriindra).

Untuk kamera dengan recording_enabled=True dan storage_mode "both"/"drive",
segmen rekaman yang sudah stabil (tidak berubah 20 detik terakhir) disalin
dari {recordings_dir}/stream_{id}/ ke {local_path}/stream_{id}/ tiap folder
, folder staging lokal yang di-mount ke Google Drive via `rclone mount`.

Multi-tautan: tiap folder punya local_path sendiri. Kamera memilih folder
via streams.drive_folder_id; NULL = folder pertama (default).

Berbeda dari uploader OAuth multi-akun (app/services/drive.py): mode ini
tidak memakai API Drive untuk menyalin, hanya penyalinan file lokal.
Satu-satunya panggilan Drive adalah `rclone lsjson` untuk verifikasi
(temuan 3.1): sumber lokal baru dihapus setelah salinannya terkonfirmasi
ada di Drive, atau setelah grace 15 menit.

Hanya berjalan bila ada folder terkonfigurasi dengan path lokal
(lihat lifespan app/main.py).
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.drive import GoogleDriveFolder
from app.models.streams import Stream
from app.services.disks import camera_rec_dirs
from app.services.drive_uploader import _is_stable
from app.services.upload_claims import (
    is_claimed,
    release_claim,
    touch_claim,
    try_claim,
)

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

# Area 5, 5.9: prune staging paling sering 1 jam sekali per direktori
# (dulu tiap putaran 30 detik memindai seluruh staging tiap kamera,
# ratusan ribu stat untuk file yang umurnya 30 hari).
_PRUNE_INTERVAL_SEC = 3600
_last_prune: dict[str, float] = {}


def _prune_due(dst: str) -> bool:
    """True bila prune untuk direktori staging ini sudah jatuh tempo."""
    now = time.time()
    if now - _last_prune.get(dst, 0.0) < _PRUNE_INTERVAL_SEC:
        return False
    _last_prune[dst] = now
    return True


def _staging_alive(path: str) -> bool:
    """True bila path staging adalah mount rclone yang masih hidup.

    B-S6: mount rclone yang mati meninggalkan direktori lokal biasa, tanpa
    cek ini file menumpuk di disk lokal dan pengguna mengira sudah di Drive.
    Hidup = mountpoint aktif, atau berisi sentinel yang ditaruh operator.
    """
    if os.path.ismount(path):
        return True
    return os.path.isfile(os.path.join(path, _MOUNT_SENTINEL))


# ---------------------------------------------------------------------------
# Temuan 3.1: sumber lokal JANGAN dihapus hanya karena salinan staging
# ukurannya sama. `rclone mount` meng-upload secara asinkron; `copy2`
# kembali hanya berarti byte tertulis ke mount/cache lokal, bukan sampai
# di Google Drive. Sumber baru dihapus bila SALAH SATU terpenuhi:
#   (a) terverifikasi di Drive remote (`rclone lsjson` menemukan file
#       dengan ukuran sama di `gdrive:stream_{id}`), atau
#   (b) salinan staging sudah stabil selama _VERIFY_GRACE_SEC (mount
#       diberi waktu meng-upload; tetap dicatat di log sebagai
#       penghapusan tanpa bukti remote, supaya terlihat bila mount
#       bermasalah).
# Sambil menunggu, segmen tercatat di _PENDING_DELETE dan klaimnya
# dipegang (temuan 3.2) supaya uploader/OAuth tidak memprosesnya.
# ---------------------------------------------------------------------------
_VERIFY_MIN_AGE_SEC = 60
_VERIFY_GRACE_SEC = 900
_PENDING_DELETE: dict[tuple[str, int, str], tuple[int, float]] = {}
# Cache daftar file remote per (remote, stream_id): (monotonic, {nama: size}).
_REMOTE_LS_CACHE: dict[tuple[str, int], tuple[float, dict[str, int]]] = {}
_REMOTE_LS_TTL_SEC = 60.0


def _remote_files(remote_name: str, stream_id: int) -> dict[str, int] | None:
    """{nama: size} file di `remote:stream_{id}` via `rclone lsjson`.

    Return None bila remote tidak bisa diperiksa (rclone hilang, remote
    mati, lsjson gagal/timeout). Hasil di-cache 60 dtk per stream supaya
    satu putaran tidak menjalankan lsjson berkali-kali.
    """
    from app.services import gdrive_rclone as gr

    key = (remote_name, stream_id)
    now = time.monotonic()
    hit = _REMOTE_LS_CACHE.get(key)
    if hit is not None and now - hit[0] < _REMOTE_LS_TTL_SEC:
        return dict(hit[1])
    binary = gr.find_rclone()
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [
                binary, "--config", gr.conf_path(), "lsjson",
                f"{remote_name}:stream_{stream_id}",
                "--files-only", "--no-mimetype",
            ],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("mirror: lsjson verifikasi stream_%s gagal: %s", stream_id, e)
        return None
    if proc.returncode != 0:
        return None
    try:
        items = json.loads(proc.stdout)
    except ValueError:
        return None
    out: dict[str, int] = {}
    if isinstance(items, list):
        for e in items:
            name = e.get("Name") or ""
            size = e.get("Size")
            if name and isinstance(size, int):
                out[name] = size
    _REMOTE_LS_CACHE[key] = (now, dict(out))
    return out


def _resolve_pending(dst_base: str, stream_id: int, src_dirs: list[str]) -> None:
    """Coba hapus sumber untuk segmen yang menunggu verifikasi (3.1).

    Salinan staging harus masih ada dengan ukuran sama; bila tidak,
    entri dibuang (disalin ulang putaran berikut). Sumber dihapus bila
    terverifikasi di Drive, atau bila sudah melewati grace.
    """
    from app.services import gdrive_rclone as gr

    now = time.monotonic()
    remote: dict[str, int] | None = None
    remote_checked = False
    dst = os.path.join(dst_base, f"stream_{stream_id}")
    for key in [k for k in _PENDING_DELETE if k[0] == dst_base and k[1] == stream_id]:
        _base, _sid, fn = key
        size, staged_at = _PENDING_DELETE[key]
        spath = None
        for src in src_dirs:
            p = os.path.join(src, fn)
            if os.path.isfile(p):
                spath = p
                break
        tpath = os.path.join(dst, fn)
        if spath is None:
            # Sumber sudah tidak ada (dihapus jalur lain / manual).
            del _PENDING_DELETE[key]
            release_claim(stream_id, fn, "mirror")
            continue
        try:
            staging_ok = os.path.exists(tpath) and os.path.getsize(tpath) == size
        except OSError:
            staging_ok = False
        if not staging_ok:
            # Salinan staging hilang/berubah: batalkan pending, salin
            # ulang putaran berikut.
            del _PENDING_DELETE[key]
            release_claim(stream_id, fn, "mirror")
            continue
        age = now - staged_at
        verified = False
        if age >= _VERIFY_MIN_AGE_SEC and not remote_checked:
            remote = _remote_files(gr.REMOTE_NAME, stream_id)
            remote_checked = True
        if remote is not None:
            verified = remote.get(fn) == size
        grace_ok = age >= _VERIFY_GRACE_SEC
        if not verified and not grace_ok:
            continue
        try:
            os.remove(spath)
        except OSError as e:  # noqa: BLE001
            log.warning(
                "mirror stream_%s gagal hapus lokal %s: %s", stream_id, spath, e
            )
            continue
        log.info(
            "mirror stream_%s: lokal dihapus %s (%s)",
            stream_id,
            spath,
            "terverifikasi di Drive" if verified else "grace staging tanpa bukti remote",
        )
        del _PENDING_DELETE[key]
        release_claim(stream_id, fn, "mirror")


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


async def _mirror_candidates() -> list[tuple[int, str, int | None, list[str]]]:
    """Daftar (stream_id, name, drive_folder_id, rec_dirs) kamera yang perlu
    dicerminkan. rec_dirs dihitung di dalam sesi via camera_rec_dirs
    (rekaman multi-disk) supaya pemakaian di thread latar aman: direktori
    main stream_{id} + sub stream_{id}_sub (rekaman dari substream bila
    kamera punya sub, perintah user 2026-11-14)."""
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
                camera_rec_dirs(s, settings.recordings_dir),
            )
            for s in res.scalars().all()
        ]


def _prune_staging(src_dirs: list[str], dst_base: str, stream_id: int) -> None:
    """Bersihkan staging lama: hanya yang lebih tua dari
    drive_retention_days. Sengaja TIDAK lagi menghapus file yang
    sumbernya sudah tak ada: sejak perintah user 2026-11-17, sumber
    lokal dihapus begitu tersalin ke staging, jadi "sumber tak ada"
    justru berarti file sudah ter-upload dan staging-nya masih
    dibutuhkan rclone sampai retensi habis. src_dirs dipertahankan
    sebagai parameter supaya pemanggil lama tidak berubah.
    """
    from datetime import datetime as _dt

    settings = get_settings()
    dst = os.path.join(dst_base, f"stream_{stream_id}")
    if not os.path.isdir(dst):
        return
    try:
        cutoff = _dt.now().timestamp() - settings.drive_retention_days * 86400
    except OSError:
        return
    for fn in os.listdir(dst):
        tpath = os.path.join(dst, fn)
        try:
            if not os.path.isfile(tpath):
                continue
            if os.path.getmtime(tpath) < cutoff:
                os.remove(tpath)
                log.info("mirror: staging lama dihapus %s", tpath)
        except OSError as e:  # noqa: BLE001
            log.warning("mirror: gagal bersihkan staging %s: %s", tpath, e)


def _mirror_one(
    src_dirs: list[str], dst_base: str, stream_id: int,
    uploaded: set[str] | None = None,
) -> int:
    """Salin segmen stabil satu kamera ke satu folder tujuan.

    src_dirs = direktori segmen sebenarnya (camera_rec_dirs, multi-disk:
    main + sub); tujuan staging tetap {dst_base}/stream_{id}, jadi
    segmen sub dan main lama tercermin ke satu direktori staging yang
    sama dan dibaca playback lewat _folder_link_segments.

    `uploaded` = nama segmen yang sudah ter-upload via API rclone
    (temuan 3.2): segmen itu dilewati supaya tidak dobel ke Drive.
    Return jumlah kegagalan (salin gagal / mount mati) untuk backoff
    (temuan 3.7). Sumber lokal TIDAK langsung dihapus setelah salin;
    lihat _resolve_pending (temuan 3.1).
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
        return 1
    _warned_dead.discard(dst_base)
    failures = 0
    now = time.time()
    dst = os.path.join(dst_base, f"stream_{stream_id}")
    for src in src_dirs:
        if not os.path.isdir(src):
            continue
        try:
            entries = os.listdir(src)
        except OSError:
            continue
        for fn in entries:
            spath = os.path.join(src, fn)
            try:
                if not os.path.isfile(spath):
                    continue
                # Temuan 3.16: stabil = umur >= 20 dtk DAN (mtime, size)
                # sama seperti putaran sebelumnya.
                if not _is_stable(spath, now):
                    continue
                # Temuan 3.2: sudah ter-upload via API -> jangan mirror.
                if uploaded is not None and fn in uploaded:
                    continue
                # Temuan 3.2: sedang diproses jalur lain -> lewati.
                if is_claimed(stream_id, fn):
                    continue
                try:
                    size = os.path.getsize(spath)
                except OSError:
                    continue
                tpath = os.path.join(dst, fn)
                try:
                    mirrored = os.path.exists(tpath) and os.path.getsize(tpath) == size
                except OSError:
                    mirrored = False
                if not mirrored:
                    if not try_claim(stream_id, fn, "mirror"):
                        continue
                    try:
                        os.makedirs(dst, exist_ok=True)
                        shutil.copy2(spath, tpath)
                    except OSError as e:  # noqa: BLE001
                        failures += 1
                        log.warning(
                            "mirror stream_%s gagal menyalin %s: %s",
                            stream_id, fn, e,
                        )
                        release_claim(stream_id, fn, "mirror")
                        continue
                    try:
                        mirrored = os.path.exists(tpath) and os.path.getsize(tpath) == size
                    except OSError:
                        mirrored = False
                    if not mirrored:
                        failures += 1
                        log.warning(
                            "mirror stream_%s salinan %s tidak cocok ukuran",
                            stream_id, fn,
                        )
                        release_claim(stream_id, fn, "mirror")
                        continue
                    log.info(
                        "mirror stream_%s -> %s: %s tersalin",
                        stream_id,
                        dst_base,
                        fn,
                    )
                # Tersalin ke staging: daftarkan pending verifikasi dan
                # pegang klaim sampai sumber dihapus (temuan 3.1, 3.2).
                key = (dst_base, stream_id, fn)
                if key not in _PENDING_DELETE:
                    _PENDING_DELETE[key] = (size, time.monotonic())
                    try_claim(stream_id, fn, "mirror")
                else:
                    touch_claim(stream_id, fn, "mirror")
            except OSError as e:  # noqa: BLE001
                failures += 1
                log.warning("mirror stream_%s gagal menyalin %s: %s", stream_id, fn, e)
    _resolve_pending(dst_base, stream_id, src_dirs)
    # Area 5, 5.9: prune staging paling sering 1 jam sekali, bukan tiap
    # putaran 30 detik.
    if _prune_due(dst):
        _prune_staging(src_dirs, dst_base, stream_id)
    return failures


def _mirror_tick(
    candidates: list[tuple[int, str, int | None, list[str]] | tuple[int, str, int | None]],
    folders: list[tuple[int, str, str]],
    uploaded: dict[int, set[str]] | None = None,
) -> int:
    """Satu putaran penyalinan segmen stabil ke tiap folder tujuan.

    Kandidat 4-elemen (stream_id, name, drive_folder_id, rec_dirs) dari
    _mirror_candidates; 3-elemen lama tetap diterima (rec_dirs diturunkan
    dari settings.recordings_dir, perilaku legacy). `uploaded` memetakan
    stream_id -> nama segmen yang sudah ter-upload via API (temuan 3.2).
    Return jumlah kegagalan untuk backoff (temuan 3.7).
    """
    if not folders:
        return 0
    settings = get_settings()
    by_id = {fid: path for fid, _name, path in folders}
    default_path = folders[0][2]
    failures = 0
    for cand in candidates:
        if len(cand) == 4:
            stream_id, _name, drive_folder_id, rec_dirs = cand
        else:
            stream_id, _name, drive_folder_id = cand
            rec_dirs = [os.path.join(settings.recordings_dir, f"stream_{stream_id}")]
        dst_base = by_id.get(drive_folder_id) if drive_folder_id else default_path
        if not dst_base:
            continue
        failures += _mirror_one(
            rec_dirs, dst_base, stream_id,
            uploaded.get(stream_id) if uploaded else None,
        )
    return failures


async def _uploaded_by_camera(stream_ids: list[int]) -> dict[int, set[str]]:
    """Nama segmen yang sudah ter-upload via API, per kamera (temuan 3.2).

    Satu query `IN (...)` untuk semua kamera kandidat, bukan satu query
    per kamera. Mirror memakai ini untuk melewati segmen yang sudah
    ter-upload, supaya tidak dobel ke Drive.
    """
    from app.models.drive import DriveUpload

    if not stream_ids:
        return {}
    async with get_session_factory()() as db:
        res = await db.execute(
            select(DriveUpload.stream_id, DriveUpload.segment_name).where(
                DriveUpload.stream_id.in_(stream_ids)
            )
        )
        out: dict[int, set[str]] = {}
        for sid, name in res.all():
            out.setdefault(sid, set()).add(name)
        return out


async def mirror_loop(initial_delay: float = 0) -> None:
    """Loop latar: tiap 30 detik salin segmen stabil ke folder-folder Drive.

    Staging/Drive mati tidak mematikan loop: kegagalan satu putaran
    dicatat, lalu retry dengan backoff yang membesar (5s, 15s, 30s,
    maks 60s), direset setelah satu putaran sukses. Segmen lokal sumber
    DIHAPUS setelah salinannya di staging terverifikasi di Drive
    (perintah user 2026-11-17, diperkuat temuan 3.1); yang dibersihkan
    di staging hanya file lebih tua dari drive_retention_days
    (_prune_staging), jadi segmen yang gagal tersalin tetap dicoba lagi
    putaran berikut.

    Area 5, 5.11: `initial_delay` menunda putaran pertama supaya tidak
    semua loop start bersamaan saat API baru naik.
    """
    from app.services.loop_health import (
        record_failure,
        record_success,
        record_tick,
    )

    failures = 0
    try:
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            started = time.monotonic()
            record_tick("mirror")
            try:
                folders = await _folders()
                if folders:
                    candidates = await _mirror_candidates()
                    if candidates:
                        uploaded = await _uploaded_by_camera(
                            [c[0] for c in candidates]
                        )
                        n_failed = await asyncio.to_thread(
                            _mirror_tick, candidates, folders, uploaded
                        )
                        if n_failed:
                            # Temuan 3.7: kegagalan salin kini dihitung,
                            # bukan ditelan, supaya backoff benar-benar jalan.
                            failures += 1
                            delay = _backoff_delay(failures)
                            log.warning(
                                "mirror loop: %d salinan gagal, backoff %ds "
                                "(%d putaran gagal berturut-turut)",
                                n_failed, delay, failures,
                            )
                            record_failure(
                                "mirror",
                                RuntimeError(f"{n_failed} salinan gagal"),
                            )
                            await asyncio.sleep(delay)
                            continue
                failures = 0
                record_success("mirror", (time.monotonic() - started) * 1000)
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
                record_failure("mirror", e)
                await asyncio.sleep(delay)
                continue
            await asyncio.sleep(_INTERVAL_SEC)
    except asyncio.CancelledError:
        pass
