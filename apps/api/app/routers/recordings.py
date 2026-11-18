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
import time
from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.rate_limit import rate_limited
from app.core.rbac import (
    is_super_admin,
    require_camera_playback_access,
    require_roles,
)
from app.db.session import get_db
from app.models.access import StreamAdminGrant, StreamPermission, UserStreamAccess
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


def _session_factory_for(
    db: AsyncSession,
) -> async_sessionmaker[AsyncSession] | None:
    """Factory sesi baru dari engine sesi pemanggil, atau None.

    6.6/6.12: satu AsyncSession TIDAK aman dipakai paralel antar
    task asyncio, jadi tiap sumber/tugas paralel membuka sesi
    sendiri dari engine yang sama (pola yang sama dipakai
    recording_cameras untuk fallback Drive). Di produksi db.bind
    adalah engine Postgres; di tes itu engine sqlite per-test,
    jadi factory turunan ini selalu menunjuk DB yang benar,
    tidak seperti get_session_factory() global yang menunjuk
    engine dari settings. None bila sesi tidak punya bind
    (pemanggil memakai sesi lama), pemanggil lalu jalan berurutan
    di sesi yang sama seperti sebelumnya.
    """
    bind = getattr(db, "bind", None)
    if bind is None:
        return None
    return async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)


def _to_server_naive(dt: datetime | None) -> datetime | None:
    """Datetime aware -> waktu lokal server (naive); naive dibiarkan.

    A-1.7: sebelumnya hanya `replace(tzinfo=None)`, jadi jam 10 WIB
    (`+07:00`) diperlakukan sebagai jam 10 waktu server dan putar/unduh
    meleset sampai 7 jam. Waktu segmen memang naive waktu lokal server,
    jadi konversi harus ke zona lokal proses (`astimezone()` tanpa
    argumen), baru tzinfo dibuang.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone().replace(tzinfo=None)


class TrimFailedError(Exception):
    """Pemotongan ffmpeg wajib tapi gagal (ffmpeg hilang / error /
    sumber tidak bisa diunduh). Pemanggil TIDAK boleh menyajikan
    segmen utuh sebagai gantinya (A-1.8)."""


# Unduhan Drive OAuth (2026-11-18, integrasi): segmen diunduh langsung
# ke file via DriveUploader.download_drive_file_to (streaming per chunk
# 1 MB, batas 2 GiB, semaphore 4 di dalam DriveUploader), bytes utuh
# TIDAK PERNAH menumpuk di RAM. Catatan test 6.1
# (test_playback_oauth_satu_unduhan): download_drive_file_to memakai
# SATU get_media per segmen, bila googleapiclient tidak terinstal
# (venv/CI saat ini) lewat fallback get_media().execute() sekali;
# bila terinstal, lewat satu request MediaIoBaseDownload yang sama.
async def _download_drive_file_to_file(
    up, file_id: str, dest_path: str
) -> int:
    """Unduh satu file Drive OAuth langsung ke `dest_path`.

    Return ukuran byte yang tertulis. `up` adalah DriveUploader
    (punya download_drive_file_to); file sebagian dihapus bila gagal.
    """
    return await up.download_drive_file_to(file_id, dest_path)


async def _kill_and_wait(proc: asyncio.subprocess.Process, timeout: float = 5.0) -> None:
    """Matikan proses anak lalu tunggu sampai benar-benar mati.

    Salinan pola app/services/gdrive_rclone.py::_kill_and_wait:
    `proc.kill()` saja tanpa `wait()` meninggalkan zombie dan pipe
    yang menggantung bila proses menulis banyak ke stderr.
    """
    try:
        proc.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()


async def _acleanup(path: str | None) -> None:
    """Hapus file temp tanpa memblokir event loop (os.remove via thread)."""
    if not path:
        return
    try:
        await asyncio.to_thread(os.remove, path)
    except OSError:
        pass


async def _acleanup_many(paths: list[str]) -> None:
    for p in paths:
        await _acleanup(p)


# 6.6/6.13: cache daftar folder Drive (GoogleDriveFolder) in-process
# TTL 60 dtk. Tabel ini jarang berubah tapi dibaca di tiap _all_segments
# (tiap timeline/segments/dates/playback). Disimpan sebagai tuple polos
# (bukan objek ORM) supaya aman dipakai lintas request/session.
_FOLDERS_CACHE_TTL_SEC = 60.0
_FOLDERS_CACHE_AT = 0.0
_FOLDERS_CACHE: list[tuple[int, str, str, str | None, str]] | None = None


def invalidate_drive_folders_cache() -> None:
    """Buang cache daftar folder Drive (dipakai setelah admin ubah folder)."""
    global _FOLDERS_CACHE_AT, _FOLDERS_CACHE
    _FOLDERS_CACHE_AT = 0.0
    _FOLDERS_CACHE = None


async def _drive_folders(
    db: AsyncSession,
) -> list[tuple[int, str, str, str | None, str]]:
    """Baris GoogleDriveFolder sebagai tuple
    (id, folder_id, folder_name, remote_name, local_path)."""
    global _FOLDERS_CACHE_AT, _FOLDERS_CACHE
    now = time.monotonic()
    if _FOLDERS_CACHE is not None and now - _FOLDERS_CACHE_AT < _FOLDERS_CACHE_TTL_SEC:
        return list(_FOLDERS_CACHE)
    from app.models.drive import GoogleDriveFolder

    try:
        rows = (
            await db.execute(
                select(GoogleDriveFolder)
                .order_by(GoogleDriveFolder.id)
                .limit(1000)  # tabel konfigurasi admin; batas pengaman saja
            )
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        log.warning("drive folder-link list gagal: %s", e)
        return list(_FOLDERS_CACHE or [])
    out = [
        (r.id, r.folder_id or "", r.folder_name or "", r.remote_name, r.local_path or "")
        for r in rows
    ]
    _FOLDERS_CACHE = out
    _FOLDERS_CACHE_AT = now
    return list(out)


async def _cheap_segment_dates(
    stream: Stream, db: AsyncSession
) -> tuple[dict[str, int], bool]:
    """Jumlah segmen per tanggal dari sumber murah + perlu fallback?

    Murah: listdir lokal + jejak drive_uploads (pola 1ce30a2). Nama
    segmen didedup lintas sumber supaya jumlah per tanggal tidak
    ganda. Return (counts, needs_full_scan): needs_full_scan True
    bila storage Drive dan drive_uploads kosong, karena segmen bisa
    saja hanya ada di folder OAuth / staging folder-link tanpa jejak
    upload; pemanggil lalu fallback ke _all_segments penuh.
    """
    from app.models.drive import DriveUpload

    settings = get_settings()
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    for s in await asyncio.to_thread(
        list_segments, stream.id, None, settings.recordings_dir, stream=stream
    ):
        seen.add(s.name)
        counts[s.start.date().isoformat()] += 1
    needs_full = False
    if stream.storage_mode in ("drive", "both"):
        # 2.3: hitung per tanggal di SQL (GROUP BY 10 karakter pertama
        # nama segmen = tanggal), bukan memuat seluruh nama jejak ke
        # RAM. Nama yang sudah ada lokal dikurangi lewat agregasi
        # kedua yang dibatasi nama lokal (IN (...)), supaya jumlah
        # per tanggal tetap dedup lintas sumber seperti sebelumnya.
        # substr() ada di PostgreSQL maupun SQLite.
        day_col = func.substr(DriveUpload.segment_name, 1, 10)
        up_rows = (
            await db.execute(
                select(day_col, func.count())
                .where(DriveUpload.stream_id == stream.id)
                .group_by(day_col)
            )
        ).all()
        overlap: dict[str, int] = {}
        if seen:
            overlap = {
                d: c
                for d, c in (
                    await db.execute(
                        select(day_col, func.count())
                        .where(
                            DriveUpload.stream_id == stream.id,
                            DriveUpload.segment_name.in_(sorted(seen)),
                        )
                        .group_by(day_col)
                    )
                ).all()
            }
        total_uploaded = 0
        for day_str, c in up_rows:
            total_uploaded += c
            try:
                date.fromisoformat(day_str)
            except ValueError:
                continue
            counts[day_str] += c - overlap.get(day_str, 0)
        if not total_uploaded:
            needs_full = True
    return dict(counts), needs_full


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
    rows = await _drive_folders(db)
    for _fid, _folder_id, _folder_name, _remote, local_path in rows:
        base = (local_path or "").rstrip("/") or (
            settings.gdrive_record_path or ""
        ).rstrip("/")
        if not base:
            continue
        d = os.path.join(base, f"stream_{stream.id}")
        try:
            names = await asyncio.to_thread(os.listdir, d)
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
                size = await asyncio.to_thread(os.path.getsize, path)
            except OSError:
                continue
            out.append(Segment(start=start, path=path, size=size, name=name))
    return out


async def _rclone_segments(
    stream: Stream, day: date | None, db: AsyncSession
) -> list[Segment]:
    """Segmen dari folder Drive rclone kamera ini (akun disk1 dsb.).

    Uploader rclone menulis ke `{remote}:{folder_id}/{nama_kamera}/nama-segmen.mp4`,
    jadi daftar dibaca dari jalur itu via `rclone lsjson`. Hanya folder yang
    punya remote_name (folder akun) yang bisa dibaca cara ini; tautan folder
    manual tanpa remote dilewati.
    """
    from app.services import gdrive_rclone as gr

    out: list[Segment] = []
    row: tuple[int, str, str, str | None, str] | None = None
    try:
        rows = await _drive_folders(db)
        if stream.drive_folder_id:
            row = next((r for r in rows if r[0] == stream.drive_folder_id), None)
            if row is None:
                # Folder baru dibuat setelah cache terisi: baca ulang
                # sekali dari DB (bukan pakai cache basi).
                invalidate_drive_folders_cache()
                rows = await _drive_folders(db)
                row = next(
                    (r for r in rows if r[0] == stream.drive_folder_id), None
                )
        else:
            row = rows[0] if rows else None
    except Exception as e:  # noqa: BLE001
        log.warning("rclone folder kamera %s gagal: %s", stream.name, e)
        return out
    if row is None or not row[2] or not row[3]:
        return out
    remote_name = row[3]
    cam_name = stream.name or f"Kamera {stream.id}"
    base = f"{row[2]}/{cam_name}"
    try:
        items = await gr.list_rclone_files(remote_name, base)
    except Exception as e:  # noqa: BLE001 - Drive opsional, jangan gagalkan timeline
        log.warning("rclone list %s gagal: %s", stream.name, e)
        return out
    for f in items:
        name = f.get("name", "")
        if not name.endswith(".mp4"):
            continue
        start = parse_segment_name(name)
        if start is None or (day is not None and start.date() != day):
            continue
        out.append(
            Segment(
                start=start,
                path="",
                size=int(f.get("size") or 0),
                name=name,
                rclone_remote=remote_name,
                rclone_path=f"{base}/{name}",
            )
        )
    return out


async def _oauth_segments(
    stream: Stream, day: date | None, db: AsyncSession
) -> list[Segment]:
    """Segmen dari folder Drive OAuth akun kamera ini."""
    from app.services.drive_accounts import uploader_for_stream

    settings = get_settings()
    if not settings.drive_enabled:
        return []
    up = await uploader_for_stream(db, stream)
    if up is None:
        return []
    folder_id = await up.ensure_folder(stream.name, stream.id)
    out: list[Segment] = []
    for f in await up.list_files(folder_id):
        name = f.get("name", "")
        if not name.endswith(".mp4"):
            continue
        start = parse_segment_name(name)
        if start is None or (day is not None and start.date() != day):
            continue
        out.append(
            Segment(
                start=start,
                path="",
                size=int(f.get("size") or 0),
                name=name,
                drive_file_id=f.get("id"),
            )
        )
    return out


async def _all_segments(
    stream: Stream, day: date | None, db: AsyncSession
) -> list[Segment]:
    """Gabungan segmen lokal + folder-link + Drive akun kamera ini.

    Lokal menang bila nama sama, lalu folder-link, lalu folder OAuth.
    6.6: tiga sumber Drive (folder-link, rclone lsjson, OAuth
    list_files) independen dan kini jalan PARALEL dengan
    asyncio.gather, bukan berurutan. Satu AsyncSession tidak aman
    dipakai paralel, jadi tiap sumber membuka sesi sendiri dari
    factory turunan engine sesi pemanggil (lihat
    _session_factory_for). Bila factory tidak tersedia, jatuh ke
    jalur berurutan lama di sesi yang sama. Lokal tetap dihitung
    dulu (sinkron, tanpa DB) dan prioritas dedup tidak berubah.
    Atribut stream yang dipakai sumber paralel dimuat dulu di sini
    supaya task paralel hanya membaca nilai yang sudah ada di
    memori, bukan memicu refresh lewat sesi pemanggil.
    """
    settings = get_settings()
    # Rekaman multi-disk: list_segments harus diberi stream supaya
    # direktori record_disk kamera itu dipakai, bukan recordings_dir
    # default (tanpa ini rekaman kamera multi-disk tidak terlihat di
    # Putar Ulang sama sekali). list_segments sinkron (listdir/getsize/
    # getmtime) jadi dijalankan via to_thread supaya tidak memblokir
    # event loop.
    segs = await asyncio.to_thread(
        list_segments, stream.id, day, settings.recordings_dir, stream=stream
    )
    if stream.storage_mode not in ("drive", "both"):
        return await asyncio.to_thread(_finish, segs)
    # Muat atribut yang dipakai sumber paralel sebelum gather.
    _preload = (stream.id, stream.name, stream.drive_folder_id)
    del _preload
    names = {s.name for s in segs}

    async def _run_source(label: str, coro_fn) -> list[Segment]:
        try:
            return await coro_fn()
        except Exception as e:  # noqa: BLE001
            log.warning("drive %s %s gagal: %s", label, stream.name, e)
            return []

    factory = _session_factory_for(db)
    if factory is None:
        # Tanpa bind: jalur berurutan lama di sesi pemanggil.
        try:
            for s in await _folder_link_segments(stream, day, db):
                if s.name not in names:
                    names.add(s.name)
                    segs.append(s)
        except Exception as e:  # noqa: BLE001
            log.warning("drive folder-link %s gagal: %s", stream.name, e)
        try:
            for s in await _rclone_segments(stream, day, db):
                if s.name not in names:
                    names.add(s.name)
                    segs.append(s)
        except Exception as e:  # noqa: BLE001
            log.warning("drive rclone %s gagal: %s", stream.name, e)
        if settings.drive_enabled:
            try:
                for s in await _oauth_segments(stream, day, db):
                    if s.name not in names:
                        names.add(s.name)
                        segs.append(s)
            except Exception as e:  # noqa: BLE001
                log.warning("drive list %s gagal: %s", stream.name, e)
        return _finish(segs)

    async def _folder_link_own() -> list[Segment]:
        async with factory() as sdb:
            return await _folder_link_segments(stream, day, sdb)

    async def _rclone_own() -> list[Segment]:
        async with factory() as sdb:
            return await _rclone_segments(stream, day, sdb)

    async def _oauth_own() -> list[Segment]:
        async with factory() as sdb:
            return await _oauth_segments(stream, day, sdb)

    # Urutan gather = prioritas dedup: folder-link, rclone, OAuth.
    folder_link, rclone, oauth = await asyncio.gather(
        _run_source("folder-link", _folder_link_own),
        _run_source("rclone", _rclone_own),
        _run_source("list", _oauth_own),
    )
    for src in (folder_link, rclone, oauth):
        for s in src:
            if s.name not in names:
                names.add(s.name)
                segs.append(s)
    return await asyncio.to_thread(_finish, segs)


def _finish(segs: list[Segment]) -> list[Segment]:
    segs.sort(key=lambda s: s.start)
    _assign_ends(segs)
    return segs


async def _segments_window(
    stream: Stream, at: datetime, db: AsyncSession
) -> list[Segment]:
    """Segmen di sekitar `at`: hari-1, hari itu, hari+1.

    6.3: segmen hanya 10 menit, jadi segmen yang memuat `at` pasti
    mulai di hari-1 (melewati tengah malam) atau hari itu; hari+1
    disertakan supaya playback-url yang miss bisa menemukan segmen
    berikutnya tanpa pemindaian penuh lagi. Tiap _all_segments
    ber-filter hari, dan lsjson/list_files Drive ter-cache, jadi
    3 panggilan hari ini harganya ~1 listing Drive.
    """
    at = _to_server_naive(at)
    days = sorted({(at - _ONE_DAY).date(), at.date(), (at + _ONE_DAY).date()})
    segs: list[Segment] = []
    names: set[str] = set()
    for d in days:
        for s in await _all_segments(stream, d, db):
            if s.name not in names:
                names.add(s.name)
                segs.append(s)
    return await asyncio.to_thread(_finish, segs)


async def _containing(
    stream: Stream, at: datetime, db: AsyncSession,
    segs: list[Segment] | None = None,
) -> Segment | None:
    """Segmen (lokal/Drive) yang memuat waktu `at`.

    6.3: sebelumnya memindai SELURUH riwayat (_all_segments tanpa
    filter hari) lalu berjalan dari segmen tertua; kini hanya jendela
    hari-1..hari+1 (lihat _segments_window). `segs` opsional: daftar
    yang sudah dipindai pemanggil (playback-url) supaya tidak
    dipindai ulang.
    """
    at = _to_server_naive(at)
    if segs is None:
        segs = await _segments_window(stream, at, db)
    for seg in segs:
        if seg.start > at + _ONE_DAY:
            break
        end = seg.end or seg.start
        if seg.start <= at < end:
            return seg
    return None


def _parse_range(header: str | None, total: int) -> tuple[int, int, bool]:
    """Header `Range: bytes=a-b` -> (start, end, valid).

    Mendukung suffix range (`bytes=-500` = 500 byte terakhir).
    A-1.2: `end < start` (mis. `bytes=500-100`) sebelumnya lolos dan
    menghasilkan `Content-Range: bytes 500-100/N` + `Content-Length`
    negatif dengan status 206; kini dianggap tidak valid sehingga
    dilayani 200 utuh (tanpa header Range).
    """
    if not header or total <= 0:
        return 0, total - 1, False
    h = header.strip()
    m = re.match(r"bytes=-(\d+)$", h)
    if m:
        suffix = int(m.group(1))
        if suffix <= 0:
            return 0, total - 1, False
        return max(total - suffix, 0), total - 1, True
    m = re.match(r"bytes=(\d+)-(\d*)$", h)
    if not m:
        return 0, total - 1, False
    start = int(m.group(1))
    if start >= total:
        return 0, total - 1, False
    end = int(m.group(2)) if m.group(2) else total - 1
    if end < start:
        return 0, total - 1, False
    return start, min(end, total - 1), True


def _range_unsatisfiable(header: str | None, total: int) -> bool:
    """True bila Range meminta byte di luar ukuran file (start >= total).

    Bedakan dari Range yang tidak valid/tidak ada (keduanya dilayani
    200 utuh): yang tidak bisa dipenuhi harus 416, bukan 200 diam-diam,
    supaya pemutar video tahu seek-nya gagal, konsisten di semua
    cabang Drive (rclone dan OAuth).
    """
    if not header or total <= 0:
        return False
    m = re.match(r"bytes=(\d+)-(\d*)$", header.strip())
    return bool(m) and int(m.group(1)) >= total


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
    Return path file temp, atau None bila TAK PERLU dipotong.
    A-1.8: bila potong DIPERLUKAN tapi gagal (ffmpeg tak ada / error /
    sumber tak bisa diunduh), raise TrimFailedError, pemanggil tidak
    boleh lagi menyajikan segmen utuh diam-diam sebagai gantinya.
    """
    seg_end = seg.end or seg.start
    if (start is None or start <= seg.start) and (end is None or end >= seg_end):
        return None
    if not shutil.which("ffmpeg"):
        log.warning("trim segmen %s dilewati: ffmpeg tidak ada", seg.name)
        raise TrimFailedError("ffmpeg tidak tersedia di server")
    cut_start = max(start, seg.start) if start is not None else seg.start
    cut_end = min(end, seg_end) if end is not None else seg_end
    duration = (cut_end - cut_start).total_seconds()
    if duration <= 0:
        return None
    offset = max(0.0, (cut_start - seg.start).total_seconds())
    tmp_in = tmp_out = None
    try:
        if seg.path and await asyncio.to_thread(os.path.exists, seg.path):
            src = seg.path
        elif seg.rclone_remote and seg.rclone_path:
            # Segmen Drive rclone: unduh dulu ke temp, lalu potong.
            from app.services import gdrive_rclone as gr

            fd, tmp_in = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            try:
                # Temuan 3.5: unduh langsung ke file (tanpa lewat RAM).
                await gr.download_rclone_file_to(
                    seg.rclone_remote, seg.rclone_path, tmp_in
                )
            except Exception as e:  # noqa: BLE001
                log.warning("rclone unduh segmen %s gagal: %s", seg.name, e)
                await _acleanup(tmp_in)
                raise TrimFailedError(f"unduh segmen Drive gagal: {e}") from e
            src = tmp_in
        else:
            # Segmen Drive: unduh dulu ke temp, lalu potong.
            from app.services.drive_accounts import uploader_for_stream

            up = await uploader_for_stream(db, stream)
            if up is None:
                raise TrimFailedError("akun Drive kamera tidak tersedia")
            file_id = seg.drive_file_id
            if not file_id:
                folder_id = await up.ensure_folder(stream.name, stream.id)
                file_id = await up.find_file(folder_id, seg.name)
            if not file_id:
                raise TrimFailedError("segmen tidak ditemukan di Drive")
            fd, tmp_in = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            # Unduh Drive OAuth langsung ke file (streaming, tanpa
            # bytes utuh di RAM).
            try:
                await _download_drive_file_to_file(up, file_id, tmp_in)
            except Exception as e:  # noqa: BLE001
                log.warning("Drive unduh segmen %s gagal: %s", seg.name, e)
                await _acleanup(tmp_in)
                raise TrimFailedError(f"unduh segmen Drive gagal: {e}") from e
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
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            # P0: timeout tanpa kill meninggalkan ffmpeg yatim; matikan
            # dan tunggu seperti pola gdrive_rclone._kill_and_wait.
            await _kill_and_wait(proc)
            await _acleanup(tmp_out)
            raise TrimFailedError(
                "ffmpeg timeout (120 detik) saat memotong segmen"
            ) from None
        except asyncio.CancelledError:
            # Jalur pembatalan: kill + wait langsung (tanpa wait_for,
            # yang bisa gagal di dalam handler CancelledError),
            # lalu teruskan pembatalan. _cleanup sinkron di sini
            # supaya tidak ada await yang bisa dibatalkan ulang.
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except asyncio.CancelledError:
                pass
            _cleanup(tmp_out)
            raise
        if proc.returncode != 0:
            msg = err.decode(errors="replace").strip()[:200]
            log.warning("trim segmen %s gagal: %s", seg.name, msg)
            await _acleanup(tmp_out)
            raise TrimFailedError(f"ffmpeg gagal memotong segmen: {msg}")
        return tmp_out
    except TrimFailedError:
        await _acleanup(tmp_out)
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("trim segmen %s gagal: %s", seg.name, e)
        await _acleanup(tmp_out)
        raise TrimFailedError(f"trim segmen gagal: {e}") from e
    finally:
        # Sengaja sinkron: finally juga berjalan saat CancelledError,
        # dan await di situ bisa dibatalkan ulang sebelum file terhapus.
        if tmp_in:
            _cleanup(tmp_in)


def _cleanup_many(paths: list[str]) -> None:
    for p in paths:
        _cleanup(p)


async def _segment_part_file(
    stream: Stream, seg: Segment, part_start: datetime, part_end: datetime,
    db: AsyncSession,
) -> tuple[str | None, bool]:
    """File lokal untuk bagian segmen [part_start, part_end].

    Return (path, is_temp). None bila segmen tidak bisa disiapkan.
    Dipakai unduh rentang: bagian utuh dari file lokal dipakai langsung,
    sisanya dipotong via ffmpeg (Drive diunduh dulu ke temp).
    """
    seg_end = seg.end or seg.start
    if (
        part_start <= seg.start
        and part_end >= seg_end
        and seg.path
        and await asyncio.to_thread(os.path.exists, seg.path)
    ):
        return seg.path, False
    trimmed = await _trimmed_segment_file(stream, seg, part_start, part_end, db)
    if trimmed is not None:
        return trimmed, True
    # _trimmed_segment_file mengembalikan None hanya bila tidak perlu
    # dipotong; bila potong gagal ia raise TrimFailedError yang merambat
    # ke download-range (500), bukan jatuh ke segmen utuh (A-1.8).
    if seg.path and await asyncio.to_thread(os.path.exists, seg.path):
        return seg.path, False
    # Segmen Drive tanpa potong: unduh utuh ke temp.
    if seg.rclone_remote and seg.rclone_path:
        from app.services import gdrive_rclone as gr

        fd, tmp = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            # Temuan 3.5: unduh langsung ke file (tanpa lewat RAM).
            await gr.download_rclone_file_to(
                seg.rclone_remote, seg.rclone_path, tmp
            )
            return tmp, True
        except Exception as e:  # noqa: BLE001
            log.warning("rclone unduh segmen %s gagal: %s", seg.name, e)
            await _acleanup(tmp)
            return None, False
    from app.services.drive_accounts import uploader_for_stream

    up = await uploader_for_stream(db, stream)
    if up is None:
        return None, False
    try:
        file_id = seg.drive_file_id
        if not file_id:
            folder_id = await up.ensure_folder(stream.name, stream.id)
            file_id = await up.find_file(folder_id, seg.name)
    except Exception as e:  # noqa: BLE001
        log.warning("Drive lookup segmen %s gagal: %s", seg.name, e)
        return None, False
    if not file_id:
        return None, False
    fd, tmp = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        # Unduh Drive OAuth langsung ke file (streaming).
        await _download_drive_file_to_file(up, file_id, tmp)
        return tmp, True
    except Exception as e:  # noqa: BLE001
        log.warning("Drive unduh segmen %s gagal: %s", seg.name, e)
        await _acleanup(tmp)
        return None, False


async def _serve_segment(
    stream: Stream, seg: Segment, download: bool, db: AsyncSession,
    request: Request | None = None,
    start: datetime | None = None, end: datetime | None = None,
) -> FileResponse | StreamingResponse:
    start = _to_server_naive(start)
    end = _to_server_naive(end)
    # B-S3: hormati rentang waktu yang diminta (potong via ffmpeg).
    # A-1.8: trim yang gagal (TrimFailedError) dijawab 500, bukan
    # menyajikan segmen utuh diam-diam.
    try:
        trimmed = await _trimmed_segment_file(stream, seg, start, end, db)
    except TrimFailedError as e:
        log.warning("trim segmen %s gagal: %s", seg.name, e)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "gagal memotong rekaman ke rentang yang diminta",
        ) from e
    if trimmed is not None:
        return FileResponse(
            trimmed,
            media_type="application/octet-stream" if download else "video/mp4",
            filename=seg.name if download else None,
            background=BackgroundTask(_cleanup, trimmed),
        )
    if seg.path and await asyncio.to_thread(os.path.exists, seg.path):
        if download:
            return FileResponse(
                seg.path,
                media_type="application/octet-stream",
                filename=seg.name,
            )
        return FileResponse(seg.path, media_type="video/mp4")
    # Segmen Drive rclone (akun disk1 dsb.): unduh SEKALI lalu layani
    # Range dari disk. Perintah user 2026-11-17 (Putar Ulang "Memuat
    # video..." sangat lambat): sebelumnya tiap potongan 1 MB memicu satu
    # proses `rclone cat` baru (startup + auth Drive + seek per potongan),
    # jadi segmen 20 MB berarti 20 proses berurutan sebelum video mulai.
    # Temuan 3.5: unduhan kini langsung ke file temp, bukan ke RAM, lalu
    # Range dilayani dari disk per 1 MB (satu segmen penuh di RAM diganti
    # satu potongan 1 MB).
    if seg.rclone_remote and seg.rclone_path:
        from app.services import gdrive_rclone as gr

        fd, tmp = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            await gr.download_rclone_file_to(
                seg.rclone_remote, seg.rclone_path, tmp
            )
        except Exception as e:  # noqa: BLE001
            # A-1.26: detail error (stderr rclone) hanya ke log server;
            # respons klien generik supaya path/kredensial internal
            # tidak bocor (konsisten dengan redact di reconnect_stream).
            await _acleanup(tmp)
            log.warning("rclone unduh segmen %s gagal: %s", seg.name, e)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Google Drive tidak terjangkau",
            ) from e
        total = await asyncio.to_thread(os.path.getsize, tmp)
        _range_header = request.headers.get("range") if request is not None else None
        if _range_unsatisfiable(_range_header, total):
            from fastapi.responses import Response

            await _acleanup(tmp)
            return Response(
                status_code=416,
                headers={
                    "Content-Range": f"bytes */{total}",
                    "Accept-Ranges": "bytes",
                },
            )
        r_start, r_end, has_range = _parse_range(_range_header, total)
        headers = {"Accept-Ranges": "bytes"}
        status_code = 200
        if has_range:
            headers["Content-Range"] = f"bytes {r_start}-{r_end}/{total}"
            headers["Content-Length"] = str(r_end - r_start + 1)
            status_code = 206
        elif total > 0:
            headers["Content-Length"] = str(total)
        if download:
            headers["Content-Disposition"] = (
                f'attachment; filename="{seg.name}"'
            )

        async def gen_rclone():
            with open(tmp, "rb") as f:
                f.seek(r_start)
                remaining = r_end - r_start + 1
                while remaining > 0:
                    chunk = await asyncio.to_thread(
                        f.read, min(CHUNK, remaining)
                    )
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            gen_rclone(),
            media_type="application/octet-stream" if download else "video/mp4",
            headers=headers,
            status_code=status_code,
            background=BackgroundTask(_cleanup, tmp),
        )
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
        # A-1.26: detail error hanya ke log server, respons generik.
        log.warning("Drive lookup segmen %s gagal: %s", seg.name, e)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Google Drive tidak terjangkau"
        ) from e
    if not file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "segmen tidak ditemukan")

    # B-S1: dukung HTTP Range seperti segmen lokal (seek pemutar video).
    # 6.1: samakan dengan cabang rclone (7cbf088, kini Temuan 3.5:
    # unduh SEKALI ke file temp, lalu layani Range dari disk).
    # Sebelumnya gen() memanggil stream_drive_file per potongan 1 MB
    # (satu get_media + auth + seek per MB); segmen 20 MB berarti 20
    # panggilan API berurutan.
    fd, tmp = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        # Unduh Drive OAuth langsung ke file (streaming).
        await _download_drive_file_to_file(up, file_id, tmp)
    except Exception as e:  # noqa: BLE001 - Drive API bisa HttpError/timeout -> 502, bukan 500
        # A-1.26: detail error hanya ke log server, respons generik.
        await _acleanup(tmp)
        log.warning("Drive unduh segmen %s gagal: %s", seg.name, e)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Google Drive tidak terjangkau"
        ) from e
    total = await asyncio.to_thread(os.path.getsize, tmp)
    _range_header = request.headers.get("range") if request is not None else None
    if _range_unsatisfiable(_range_header, total):
        from fastapi.responses import Response

        await _acleanup(tmp)
        return Response(
            status_code=416,
            headers={
                "Content-Range": f"bytes */{total}",
                "Accept-Ranges": "bytes",
            },
        )
    r_start, r_end, has_range = _parse_range(_range_header, total)
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
        with open(tmp, "rb") as f:
            f.seek(r_start)
            remaining = r_end - r_start + 1
            while remaining > 0:
                chunk = await asyncio.to_thread(f.read, min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        gen(),
        media_type="application/octet-stream" if download else "video/mp4",
        headers=headers,
        status_code=status_code,
        background=BackgroundTask(_cleanup, tmp),
    )


def _file_url(stream_id: int, seg: Segment) -> str:
    end = (seg.end or seg.start).isoformat()
    return (
        f"/api/recordings/{stream_id}/file"
        f"?start={seg.start.isoformat()}&end={end}"
    )


async def _playback_allowed_ids(
    user: User, db: AsyncSession, streams: list[Stream]
) -> set[int]:
    """Id kamera yang playback-nya diizinkan user ini.

    A-1.13: satu batch query per sumber izin, bukan 2-3 query per
    kamera seperti _check_camera_access di loop. Semantik sama dengan
    _check_camera_access(..., need_playback=True): super_admin semua;
    admin pemilik (created_by/owner_id) atau grant can_playback;
    user/guest butuh can_view + can_playback (akses eksplisit atau
    berbasis peran).
    """
    if is_super_admin(user):
        return {s.id for s in streams}
    allowed: set[int] = set()
    if user.role == "admin":
        allowed.update(
            s.id
            for s in streams
            if getattr(s, "created_by", None) == user.id
            or getattr(s, "owner_id", None) == user.id
        )
        rows = await db.execute(
            select(StreamAdminGrant.stream_id).where(
                StreamAdminGrant.admin_id == user.id,
                StreamAdminGrant.can_playback.is_(True),
            )
        )
        allowed.update(rows.scalars().all())
        return allowed
    rows = await db.execute(
        select(UserStreamAccess.stream_id).where(
            UserStreamAccess.user_id == user.id,
            UserStreamAccess.can_view.is_(True),
            UserStreamAccess.can_playback.is_(True),
        )
    )
    allowed.update(rows.scalars().all())
    rows = await db.execute(
        select(StreamPermission.stream_id).where(
            StreamPermission.role == user.role,
            StreamPermission.user_id.is_(None),
            StreamPermission.can_view.is_(True),
            StreamPermission.can_playback.is_(True),
        )
    )
    allowed.update(rows.scalars().all())
    return allowed


@router.get(
    "/recordings/cameras",
    response_model=list[StreamOut],
    # 4.7: endpoint ini memicu _all_segments (rclone lsjson + Drive API)
    # per kamera; tanpa batas, guest bisa membanjiri Drive API sampai
    # kuota 429. 30/menit per IP cukup untuk navigasi manusia.
    dependencies=[Depends(rate_limited(30, 60))],
)
async def recording_cameras(
    response: Response,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(user_or_above),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Kamera yang boleh diakses user dan benar-benar punya rekaman.

    Hanya kamera yang punya minimal satu segmen rekaman (lokal atau Drive)
    yang dikembalikan, supaya pemilih kamera di Putar Ulang tidak menampilkan
    kamera yang tidak bisa diputar. `recording_enabled` saja tidak cukup:
    kamera yang baru diaktifkan belum tentu punya segmen, dan kamera yang
    rekamannya sudah dimatikan masih bisa punya rekaman lama yang bisa
    diputar. Lokal dicek dulu (murah, satu listdir); Drive hanya dicek bila
    lokal kosong dan kamera memakai storage Drive.

    Perintah user 2026-11-17 (Putar Ulang sangat lambat): cek Drive memakai
    kueri EXISTS murah ke tabel drive_uploads dulu. Sebelumnya, tiap kamera
    Drive memanggil _all_segments yang menjalankan `rclone lsjson` (~2 detik
    per kamera, cache 120 detik) plus list_files Google Drive API, hanya
    untuk menjawab "ada segmen atau tidak". Fallback ke _all_segments hanya
    bila drive_uploads kosong, supaya kamera yang segmennya hanya ada di
    folder OAuth / staging folder-link tetap ketemu.

    Paginasi: limit default 50 (maks 500); total sebelum paginasi di
    header X-Total-Count. Paginasi memotong hasil akhir, bukan kerja
    pemindaian (seluruh kamera tetap dipindai untuk menentukan mana
    yang punya rekaman).
    """
    from app.models.drive import DriveUpload
    from app.routers.streams import _visible_streams, stream_to_out

    streams = await _visible_streams(user, db)
    # A-1.13: cek akses playback sekali untuk semua kamera (batch),
    # bukan _check_camera_access per kamera (2-3 query tiap kamera).
    allowed = await _playback_allowed_ids(user, db, streams)
    out: list[StreamOut] = []
    drive_fallback: list[Stream] = []
    drive_candidates: list[Stream] = []
    for s in streams:
        # Pemilih Putar Ulang hanya menampilkan kamera yang playback-nya
        # diizinkan (bukan sekadar live): user dengan can_view tapi
        # tanpa can_playback sebelumnya melihat kamera di daftar lalu
        # ditolak 403 di timeline/segmen.
        if s.id not in allowed:
            continue
        if await asyncio.to_thread(
            list_segments, s.id, None, settings.recordings_dir, stream=s
        ):
            out.append(stream_to_out(s, settings))
            continue
        if s.storage_mode in ("drive", "both"):
            drive_candidates.append(s)
    # N+1 diperbaiki: cek jejak upload Drive untuk SEMUA kandidat dalam
    # SATU query agregat (GROUP BY stream_id), bukan satu query EXISTS
    # per kamera. Semantik sama: kamera dianggap punya upload bila ada
    # minimal satu baris DriveUpload untuk stream_id itu. Kamera tanpa
    # jejak tetap masuk fallback mahal di bawah (folder OAuth / staging
    # folder-link), seperti sebelumnya.
    has_upload_ids: set[int] = set()
    if drive_candidates:
        rows = (
            await db.execute(
                select(DriveUpload.stream_id)
                .where(
                    DriveUpload.stream_id.in_([s.id for s in drive_candidates])
                )
                .group_by(DriveUpload.stream_id)
            )
        ).all()
        has_upload_ids = {r[0] for r in rows}
    for s in drive_candidates:
        if s.id in has_upload_ids:
            out.append(stream_to_out(s, settings))
        else:
            # Fallback mahal (hanya bila jejak upload kosong): segmen
            # bisa saja hanya ada di folder OAuth / staging folder-link.
            drive_fallback.append(s)
    async def _fallback_has_segments(s: Stream, sdb: AsyncSession) -> bool:
        """Apakah kamera fallback punya segmen, tanpa panggilan Drive lambat
        bila tidak perlu.

        Cek murah dulu staging folder-link (listdir lokal, ~0,01 detik).
        Bila ada, kamera punya rekaman, tidak perlu _all_segments. Bila
        tidak ada dan kamera tidak punya folder Drive, berhenti: sumber
        rclone/OAuth tidak punya folder untuk diperiksa, dan
        _rclone_segments menebak folder default + nama kamera yang
        tidak ada lalu menggantung sampai timeout 60 detik per kamera
        (9 kamera baru MIM Gudang tanpa folder: endpoint 120 detik,
        pemilih kamera Putar Ulang macet di "Memuat kamera...").
        Hanya bila ada folder Drive, jalankan _all_segments penuh.
        """
        try:
            if await _folder_link_segments(s, None, sdb):
                return True
        except Exception:  # noqa: BLE001 - staging opsional
            pass
        if not s.drive_folder_id:
            return False
        segs = await _all_segments(s, None, sdb)
        return bool(segs)

    if drive_fallback:
        # A-1.13: fallback Drive per kamera jalan bersamaan (batas 4),
        # bukan berurutan. Satu AsyncSession tidak aman dipakai
        # bersamaan antar-task, jadi tiap tugas membuka sesi sendiri
        # dari engine yang sama (db.bind; di test itu engine sqlite
        # per-test). Urutan hasil dipertahankan (gather).
        async def _fallback_one(
            s: Stream, sem: asyncio.Semaphore, factory
        ) -> tuple[Stream, bool]:
            async with sem:
                if factory is None:
                    has = await _fallback_has_segments(s, db)
                else:
                    async with factory() as sdb:
                        has = await _fallback_has_segments(s, sdb)
            return s, has

        factory = None
        if db.bind is not None:
            factory = async_sessionmaker(
                db.bind, class_=AsyncSession, expire_on_commit=False
            )
        sem = asyncio.Semaphore(4)
        results = await asyncio.gather(
            *(_fallback_one(s, sem, factory) for s in drive_fallback)
        )
        for s, has in results:
            if has:
                out.append(stream_to_out(s, settings))
        # Fallback ditambahkan belakangan: kembalikan urutan id kamera
        # seperti sebelum perubahan (daftar diurutkan _visible_streams).
        out.sort(key=lambda o: o.id)
    response.headers["X-Total-Count"] = str(len(out))
    return out[offset : offset + limit]


@router.get(
    "/recordings/{stream_id}/timeline",
    response_model=TimelineOut,
    dependencies=[Depends(rate_limited(30, 60))],
)
async def timeline(
    stream_id: int,
    response: Response,
    day: date | None = Query(None, alias="date"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    day = day or date.today()
    segs = await _all_segments(stream, day, db)
    entries = [
        {
            "start": s.start.isoformat(),
            "end": (s.end or s.start).isoformat(),
            "has_event": False,
        }
        for s in segs
    ]
    # BREAKING (paginasi): sebelumnya seluruh entri satu hari
    # dikembalikan; kini default 50 entri pertama, total di header
    # X-Total-Count. Satu hari penuh maksimal 144 segmen (10 menit),
    # jadi pemutar yang butuh sehari penuh harus minta ?limit=500.
    response.headers["X-Total-Count"] = str(len(entries))
    return {
        "date": day.isoformat(),
        "entries": entries[offset : offset + limit],
        "events": [],
    }


@router.get(
    "/recordings/{stream_id}/segments",
    response_model=list[SegmentOut],
    dependencies=[Depends(rate_limited(30, 60))],
)
async def segments(
    stream_id: int,
    response: Response,
    day: date | None = Query(None, alias="date"),
    hour: int | None = Query(None, ge=0, le=23),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    segs = await _all_segments(stream, day, db)
    if hour is not None:
        segs = [s for s in segs if s.start.hour == hour]
    # BREAKING (paginasi): seperti timeline, default 50 entri pertama;
    # total sebelum paginasi di header X-Total-Count.
    response.headers["X-Total-Count"] = str(len(segs))
    segs = segs[offset : offset + limit]
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


@router.get(
    "/recordings/{stream_id}/dates",
    response_model=DatesOut,
    dependencies=[Depends(rate_limited(30, 60))],
)
async def dates(
    stream_id: int,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    # 6.5: jawab dari sumber murah (listdir lokal + drive_uploads),
    # bukan _all_segments penuh (lsjson + list_files Drive) hanya
    # untuk daftar tanggal. Fallback penuh hanya bila jejak upload
    # kosong (pola 1ce30a2).
    counts, needs_full = await _cheap_segment_dates(stream, db)
    if needs_full:
        segs = await _all_segments(stream, None, db)
        dates = sorted({s.start.date().isoformat() for s in segs})
    else:
        dates = sorted(counts)
    return {"dates": dates}


@router.get("/recordings/{stream_id}/stream", dependencies=[Depends(rate_limited(10, 60))])
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
    # sebelumnya bisa TypeError -> 500). A-1.7: konversi ke waktu lokal
    # server, bukan sekadar buang tzinfo.
    start = _to_server_naive(start)
    end = _to_server_naive(end)
    if end is not None and end <= start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end harus setelah start")
    stream = await _get_stream(stream_id, db)
    seg = await _containing(stream, start, db)
    if seg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
    return await _serve_segment(
        stream, seg, download=False, db=db, request=request, start=start, end=end
    )


@router.get("/recordings/{stream_id}/file", dependencies=[Depends(rate_limited(10, 60))])
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
    # B-S3: seragamkan timezone sebelum membandingkan. A-1.7: konversi
    # ke waktu lokal server, bukan sekadar buang tzinfo.
    start = _to_server_naive(start)
    end = _to_server_naive(end)
    if end <= start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end harus setelah start")
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


MAX_DOWNLOAD_RANGE = timedelta(hours=2)
# A-1.24: batas tambahan selain durasi, satu unduhan 2 jam dari banyak
# segmen Drive bisa memenuhi disk temp (tiap segmen diunduh utuh dulu).
# Estimasi memakai ukuran segmen penuh (konservatif, sebelum dipotong).
MAX_DOWNLOAD_RANGE_SEGMENTS = 64
MAX_DOWNLOAD_RANGE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


@router.get("/recordings/{stream_id}/download-range", dependencies=[Depends(rate_limited(10, 60))])
async def download_range(
    stream_id: int,
    start: datetime,
    end: datetime,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    """Unduh rekaman rentang [start, end] sebagai satu file MP4.

    Segmen yang tumpang tindih dengan rentang dipotong ke rentang lalu
    digabung via ffmpeg (stream copy, tanpa re-encode). Maksimal 2 jam
    per unduhan; celah antar segmen (kamera mati) tidak diisi, video
    langsung melompat ke segmen berikutnya.
    """
    # A-1.7: konversi ke waktu lokal server, bukan sekadar buang tzinfo.
    start = _to_server_naive(start)
    end = _to_server_naive(end)
    if end <= start:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "end harus setelah start"
        )
    if end - start > MAX_DOWNLOAD_RANGE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "rentang maksimal 2 jam per unduhan",
        )
    if not shutil.which("ffmpeg"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ffmpeg tidak tersedia di server",
        )
    stream = await _get_stream(stream_id, db)
    # 6.3/6.12: pindai hanya hari-hari dalam rentang (maks 2 jam, jadi
    # paling banyak 2 tanggal), bukan seluruh riwayat. lsjson/list_files
    # Drive ter-cache, jadi panggilan hari kedua hampir gratis.
    days = sorted({start.date(), end.date()})
    _segs: list = []
    _names: set[str] = set()
    for d in days:
        for s in await _all_segments(stream, d, db):
            if s.name not in _names:
                _names.add(s.name)
                _segs.append(s)
    _finished = await asyncio.to_thread(_finish, _segs)
    segs = [
        s
        for s in _finished
        if s.start < end and (s.end or s.start) > start
    ]
    if not segs:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "tidak ada rekaman pada rentang itu"
        )
    # A-1.24: tolak sebelum mengunduh bila segmen/ukuran terlalu besar.
    if len(segs) > MAX_DOWNLOAD_RANGE_SEGMENTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"rentang mencakup {len(segs)} segmen, maksimal "
            f"{MAX_DOWNLOAD_RANGE_SEGMENTS} per unduhan",
        )
    estimated = sum(s.size or 0 for s in segs)
    if estimated > MAX_DOWNLOAD_RANGE_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "perkiraan ukuran unduhan melebihi 2 GiB, persempit rentang",
        )
    parts: list[str] = []
    temps: list[str] = []
    try:
        # 6.12: segmen disiapkan PARALEL (semaphore 4), bukan
        # berurutan. Tiap segmen Drive diunduh utuh ke temp sebelum
        # digabung, jadi unduhan berurutan membuat satu segmen
        # lambat menahan seluruh rentang. Tiap tugas memakai sesi
        # DB sendiri (factory turunan engine sesi pemanggil, lihat
        # _session_factory_for) karena _segment_part_file memakai
        # sesi untuk lookup Drive OAuth dan satu AsyncSession tidak
        # aman dipakai paralel; tanpa factory, jatuh ke jalur
        # berurutan lama. Urutan bagian dipertahankan (gather
        # mengembalikan sesuai urutan segmen) supaya concat tetap
        # kronologis. TrimFailedError dari satu segmen tetap
        # menggagalkan seluruh unduhan (500) seperti sebelumnya,
        # bukan dilewati diam-diam; segmen Drive yang gagal unduh
        # tetap dilewati dengan peringatan (return None).
        _part_jobs: list[tuple[Segment, datetime, datetime]] = []
        for seg in segs:
            seg_end = seg.end or seg.start
            p_start = max(seg.start, start)
            p_end = min(seg_end, end)
            if p_end <= p_start:
                continue
            _part_jobs.append((seg, p_start, p_end))
        _factory = _session_factory_for(db)
        if _factory is None or len(_part_jobs) <= 1:
            _part_results: list[tuple[str | None, bool]] = []
            for _seg, _ps, _pe in _part_jobs:
                _part_results.append(
                    await _segment_part_file(stream, _seg, _ps, _pe, db)
                )
        else:
            _sem = asyncio.Semaphore(4)

            async def _part_one(
                _seg: Segment, _ps: datetime, _pe: datetime,
            ) -> tuple[str | None, bool] | Exception:
                async with _sem:
                    try:
                        async with _factory() as _sdb:
                            return await _segment_part_file(
                                stream, _seg, _ps, _pe, _sdb
                            )
                    except Exception as _e:  # noqa: BLE001
                        return _e

            _part_results = await asyncio.gather(
                *(_part_one(_seg, _ps, _pe) for _seg, _ps, _pe in _part_jobs)
            )
            for _res in _part_results:
                if isinstance(_res, Exception):
                    raise _res
        for (_seg, _ps, _pe), _res in zip(_part_jobs, _part_results):
            path, is_temp = _res
            if path is None:
                log.warning(
                    "download-range: segmen %s dilewati (tidak bisa disiapkan)",
                    _seg.name,
                )
                continue
            parts.append(path)
            if is_temp:
                temps.append(path)
        if not parts:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "tidak ada rekaman pada rentang itu"
            )
        fd, list_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        temps.append(list_path)
        with open(list_path, "w") as f:
            for p in parts:
                # Jalur harus absolut: concat demuxer membaca jalur relatif
                # terhadap lokasi file list (di /tmp), bukan cwd API,
                # jadi jalur relatif data/recordings/... tidak ketemu.
                safe = os.path.abspath(p).replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        fd, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        temps.append(out_path)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", "-movflags", "+faststart", out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            # P0: timeout tanpa kill meninggalkan ffmpeg yatim; matikan
            # dan tunggu seperti pola gdrive_rclone._kill_and_wait.
            await _kill_and_wait(proc)
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "gagal menggabung rekaman",
            ) from None
        except asyncio.CancelledError:
            # Jalur pembatalan: kill + wait langsung (tanpa wait_for),
            # hapus file temp, lalu teruskan pembatalan.
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except asyncio.CancelledError:
                pass
            _cleanup_many(temps)
            raise
        if proc.returncode != 0:
            log.warning(
                "download-range gabung gagal: %s",
                err.decode(errors="replace").strip()[:200],
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "gagal menggabung rekaman",
            )
        name = (
            f"rekaman-{stream_id}-"
            f"{start.strftime('%Y%m%d-%H%M')}-sd-{end.strftime('%Y%m%d-%H%M')}.mp4"
        )
        return FileResponse(
            out_path,
            media_type="video/mp4",
            filename=name,
            background=BackgroundTask(_cleanup_many, temps),
        )
    except HTTPException:
        await _acleanup_many(temps)
        raise
    except Exception as e:  # noqa: BLE001
        await _acleanup_many(temps)
        log.warning("download-range gagal: %s", e)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "gagal mengunduh rentang",
        ) from e


async def _find_next_drive_aware(
    stream: Stream, after: datetime, db: AsyncSession,
    segs: list[Segment] | None = None,
) -> tuple[Segment, datetime] | None:
    """Segmen yang memuat `after`, atau segmen berikutnya (lokal + Drive).

    B-S2: dipakai playback-url dan next-playable agar konsisten, fallback
    tidak lagi lokal saja.

    6.3: `segs` opsional (jendela yang sudah dipindai playback-url)
    dipakai dulu untuk fallback Drive, supaya satu request tidak
    memindai ulang seluruh riwayat. Bila segmen berikutnya di luar
    jendela (kamera mati >1 hari), fallback ke pemindaian penuh agar
    hasil tetap sama seperti sebelumnya.
    """
    after = _to_server_naive(after)
    # find_next_playable sinkron (memindai listdir sampai 8 hari),
    # jalankan via to_thread supaya tidak memblokir event loop.
    res = await asyncio.to_thread(
        find_next_playable,
        stream.id, after, get_settings().recordings_dir, stream=stream,
    )
    if res is not None:
        return res
    if stream.storage_mode in ("drive", "both"):
        if segs is not None:
            for seg in segs:
                end = seg.end or seg.start
                if seg.start <= after < end:
                    return seg, after
                if seg.start >= after:
                    return seg, seg.start
            # Di luar jendela: pindai penuh (hasil tetap sama).
        for seg in await _all_segments(stream, None, db):
            end = seg.end or seg.start
            if seg.start <= after < end:
                return seg, after
            if seg.start >= after:
                return seg, seg.start
    return None


@router.get(
    "/recordings/{stream_id}/playback-url",
    response_model=PlaybackUrlOut,
    dependencies=[Depends(rate_limited(60, 60))],
)
async def playback_url(
    stream_id: int,
    time: datetime,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    time = _to_server_naive(time)
    # 6.3: SATU pemindaian jendela untuk _containing + _find_next,
    # bukan 2x _all_segments penuh + pindai lokal 8 hari.
    segs = await _segments_window(stream, time, db)
    seg = await _containing(stream, time, db, segs=segs)
    if seg is None:
        # B-S2: cari berikutnya dengan pencarian Drive-aware (seperti
        # next-playable), bukan hanya lokal.
        nxt = await _find_next_drive_aware(stream, time, db, segs=segs)
        if nxt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "tidak ada rekaman")
        seg = nxt[0]
    return {"url": _file_url(stream_id, seg), "expires_at": None}


@router.get(
    "/recordings/{stream_id}/next-playable",
    response_model=NextPlayableOut,
    dependencies=[Depends(rate_limited(60, 60))],
)
async def next_playable(
    stream_id: int,
    after: datetime | None = None,
    _user: User = Depends(user_or_above),
    _access: User = Depends(require_camera_playback_access()),
    db: AsyncSession = Depends(get_db),
):
    stream = await _get_stream(stream_id, db)
    after = after or datetime.now()
    after = _to_server_naive(after)
    res = await _find_next_drive_aware(stream, after, db)
    if res is None:
        return {"available": False, "time": None}
    return {"available": True, "time": res[1].isoformat()}
