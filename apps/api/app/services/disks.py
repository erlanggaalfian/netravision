"""Service disk rekaman: sanitasi path, daftar disk, bersih-bersih disk penuh.

Fondasi fitur "Rekaman multi-disk": tiap kamera boleh menunjuk mount point
disk sendiri via streams.record_disk; kosong = recordings_dir default.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive import DriveUpload, GoogleDriveFolder
from app.models.streams import Stream
from app.services.recording import SEGMENT_RE

logger = logging.getLogger(__name__)

_GB = 1024 ** 3
_UNITS = ("B", "KB", "MB", "GB", "TB")


def sanitize_path_part(s: str) -> str:
    """Sanitasi ala v2: hanya alnum, '-' dan '_'; spasi dan karakter lain jadi '_'."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def camera_rec_base(stream: Stream) -> str:
    """Path dasar rekaman: {disk}/recordings/{safe_group}/{safe_name}."""
    disk = (stream.record_disk or "/").rstrip("/")
    group = sanitize_path_part(stream.group_name or "Default")
    name = sanitize_path_part(stream.name or f"stream_{stream.id}")
    return f"{disk}/recordings/{group}/{name}"


def camera_rec_dir(stream: Stream, recordings_dir: str | Path) -> str:
    """Direktori segmen sebenarnya (dengan stream_{id} di ujung)."""
    if stream.record_disk:
        return f"{camera_rec_base(stream)}/stream_{stream.id}"
    return os.path.join(os.fspath(recordings_dir), f"stream_{stream.id}")


def camera_rec_dirs(stream: Stream, recordings_dir: str | Path) -> list[str]:
    """Semua direktori segmen kamera: main stream_{id} + sub
    stream_{id}_sub (perintah user 2026-11-14: rekaman dari substream
    bila kamera punya sub). Direktori main selalu pertama, supaya
    segmen lama dari main tetap terbaca; direktori sub kedua. Bila
    kamera tidak punya sub, direktori sub tidak ada dan pembaca
    mengabaikannya (os.listdir gagal -> kosong)."""
    main_dir = camera_rec_dir(stream, recordings_dir)
    return [main_dir, f"{main_dir}_sub"]


def record_path_for(stream: Stream, recordings_dir: str | Path) -> str | None:
    """recordPath MediaMTX bila record_disk terisi, None bila pakai default."""
    if not stream.record_disk:
        return None
    return f"{camera_rec_base(stream)}/%path/%Y-%m-%d_%H-%M-%S-%f.mp4"


def _pick_unit(n: int) -> str:
    """Satuan terbesar yang nilainya masih >= 1 (pembagian 1024)."""
    value = float(n)
    unit = "B"
    for u in _UNITS[1:]:
        if value < 1024:
            break
        value /= 1024
        unit = u
    return unit


def _human(n: int, unit: str) -> str:
    """Format v2 dalam satuan yang diberi: 1 desimal bila 1 <= x < 10,
    0 desimal bila >= 10 (mis. '48GB', '0GB')."""
    value = n / (1024 ** _UNITS.index(unit))
    if 1 <= value < 10:
        return f"{value:.1f}{unit}"
    return f"{value:.0f}{unit}"


def _local_rclone_conf_path() -> str:
    """Lokasi .rclone.conf, logika yang sama dengan gdrive_rclone._data_dir."""
    override = os.environ.get("RCLONE_DATA_DIR") or os.environ.get(
        "NETRAVISION_DATA_DIR"
    )
    base = override or str(Path(__file__).resolve().parents[2] / "data")
    return os.path.join(base, ".rclone.conf")


def _local_rclone_remote_names() -> list[str]:
    """Parse nama section dari .rclone.conf tanpa import gdrive_rclone.

    Fallback bila import gdrive_rclone bermasalah (mis. circular import).
    """
    try:
        text = Path(_local_rclone_conf_path()).read_text()
    except OSError:
        return []
    names: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if m:
            names.append(m.group(1).strip())
    return names


def list_disks() -> list[dict]:
    """Daftar mount point lokal dari `df` (size > 1GB, tanpa /sys /proc /dev),
    ditambah tiap remote rclone dari conf sebagai entri disk
    (mount `rclone:{nama}`, fstype `rclone`)."""
    try:
        proc = subprocess.run(
            ["df", "-B1", "--output=target,size,avail,fstype"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("list_disks: df gagal: %s", e)
        return []
    out: list[dict] = []
    for line in proc.stdout.splitlines()[1:]:  # lewati header
        parts = line.rsplit(None, 3)
        if len(parts) != 4:
            continue
        target, size_s, avail_s, fstype = parts
        if not target.startswith("/"):
            continue
        if target in ("/sys", "/proc", "/dev") or target.startswith(
            ("/sys/", "/proc/", "/dev/")
        ):
            continue
        try:
            size = int(size_s)
            avail = int(avail_s)
        except ValueError:
            continue
        if size <= _GB:
            continue
        unit = _pick_unit(size)
        out.append(
            {
                "mount": target,
                "size_bytes": size,
                "avail_bytes": avail,
                "size_human": _human(size, unit),
                "avail_human": _human(avail, unit),
                "fstype": fstype,
                "usage_pct": round((size - avail) / size * 100, 1),
            }
        )
    out.extend(_rclone_disks())
    return out


def _rclone_about_one(binary: str, conf: str, name: str) -> dict | None:
    """Satu entri disk dari `rclone about {name}: --json`, atau None bila
    remote gagal dibaca. Dipakai `_rclone_disks` (paralel, temuan 3.9)."""
    try:
        proc = subprocess.run(
            [binary, "--config", conf, "about", f"{name}:", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    total = data.get("total")
    used = data.get("used")
    free = data.get("free")
    if not isinstance(total, int) or total <= 0:
        return None
    if not isinstance(used, int):
        used = total - free if isinstance(free, int) else 0
    if not isinstance(free, int):
        free = total - used
    unit = _pick_unit(total)
    return {
        "mount": f"rclone:{name}",
        "size_bytes": total,
        "avail_bytes": free,
        "size_human": _human(total, unit),
        "avail_human": _human(free, unit),
        "fstype": "rclone",
        "usage_pct": round(used / total * 100, 1),
    }


def _rclone_disks() -> list[dict]:
    """Entri disk untuk tiap remote rclone di conf.

    Kapasitas dari `rclone about {remote}: --json` (timeout 10 detik per
    remote). Remote yang gagal dibaca dilewati diam-diam.

    Temuan 3.9: `rclone about` per remote dijalankan PARALEL (dulu
    berurutan, jadi N remote x 10 dtk memblokir event loop puluhan
    detik bila Drive lambat).
    """
    from concurrent.futures import ThreadPoolExecutor

    try:
        from app.services.gdrive_rclone import conf_path as _conf_path
        from app.services.gdrive_rclone import find_rclone
        from app.services.gdrive_rclone import list_remote_names as _list_names

        names = _list_names()
        conf = _conf_path()
        binary = find_rclone()
    except Exception as e:  # noqa: BLE001 - jangan gugurkan list_disks
        logger.debug("list_disks: import gdrive_rclone gagal, parse conf langsung: %s", e)
        names = _local_rclone_remote_names()
        conf = _local_rclone_conf_path()
        binary = shutil.which("rclone")
    if not binary or not names:
        return []
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda n: _rclone_about_one(binary, conf, n), names))
    return [r for r in results if r is not None]


def _disk_usage_pct(path: str) -> float | None:
    """Pemakaian disk dalam persen, atau None bila path tak terbaca."""
    try:
        usage = shutil.disk_usage(path)
    except OSError as e:
        logger.warning("tak bisa baca pemakaian disk %s: %s", path, e)
        return None
    if usage.total <= 0:
        return None
    return usage.used / usage.total * 100


def _listdir_names(path: str) -> list[str]:
    """os.listdir(path), [] bila direktori tak terbaca.

    Helper sinkron untuk asyncio.to_thread (P1: pemindaian direktori
    tidak boleh memblokir event loop); OSError ditelan seperti
    perilaku lama pemanggil.
    """
    try:
        return os.listdir(path)
    except OSError:
        return []


async def _disk_usage_pct_async(path: str) -> float | None:
    """_disk_usage_pct di thread (shutil.disk_usage memblokir, P1)."""
    return await asyncio.to_thread(_disk_usage_pct, path)


def _is_safe_rclone_delete_name(name: str) -> bool:
    """True bila nama file dari lsjson aman ditulis ke --files-from.

    Nama harus relatif (bukan absolut), tidak diawali '-' (supaya
    tidak ditafsir sebagai flag rclone), dan tidak mengandung
    komponen '..' atau komponen kosong (mis. 'a//b'). Nama yang
    tidak lolos TIDAK dihapus (dilewati + dicatat di log).
    """
    if not name or name.startswith(("-", "/")):
        return False
    return all(p not in ("", "..") for p in name.split("/"))


async def cleanup_full_disks(
    db: AsyncSession,
    recordings_dir: str | Path,
    threshold_pct: float,
    target_pct: float,
) -> int:
    """Hapus segmen tertua di disk yang pemakaiannya >= threshold sampai < target.

    Disk yang dibersihkan = tiap record_disk unik yang terisi di tabel
    streams, plus recordings_dir sebagai disk default bila ada kamera tanpa
    record_disk. Kamera mode drive/both hanya kehilangan segmen yang sudah
    tercatat ter-upload di drive_uploads.
    """
    result = await db.execute(select(Stream))
    streams = result.scalars().all()
    if not streams:
        return 0

    by_disk: dict[str | None, list[Stream]] = {}
    for stream in streams:
        key = (stream.record_disk or "").strip() or None
        by_disk.setdefault(key, []).append(stream)

    deleted_total = 0
    for disk, disk_streams in by_disk.items():
        probe = disk if disk else os.fspath(recordings_dir)
        pct = await _disk_usage_pct_async(probe)
        if pct is None:
            continue
        if pct < threshold_pct:
            continue
        logger.info(
            "cleanup: disk %s penuh %.1f%% (ambang %.1f%%), hapus segmen tertua",
            probe,
            pct,
            threshold_pct,
        )

        candidates: list[tuple[float, str]] = []  # (mtime, path), tertua dulu
        for stream in disk_streams:
            rec_dirs = camera_rec_dirs(stream, recordings_dir)
            local_names: list[str] = []
            for rec_dir in rec_dirs:
                # P1: listdir di thread.
                local_names.extend(
                    n
                    for n in await asyncio.to_thread(_listdir_names, rec_dir)
                    if SEGMENT_RE.match(n)
                )
            uploaded: set[str] | None = None
            if stream.storage_mode in ("drive", "both") and local_names:
                # 2.3: cek jejak HANYA untuk segmen lokal yang ada
                # (WHERE segment_name IN (...)), bukan seluruh riwayat
                # upload kamera yang dimuat ke RAM tiap putaran cleanup.
                res = await db.execute(
                    select(DriveUpload.segment_name).where(
                        DriveUpload.stream_id == stream.id,
                        DriveUpload.segment_name.in_(local_names),
                    )
                )
                uploaded = {r[0] for r in res.all()}
            for rec_dir in rec_dirs:
                names = await asyncio.to_thread(_listdir_names, rec_dir)
                for name in names:
                    if not SEGMENT_RE.match(name):
                        continue
                    if uploaded is not None and name not in uploaded:
                        continue
                    path = os.path.join(rec_dir, name)
                    try:
                        # P1: stat di thread.
                        mtime = await asyncio.to_thread(os.path.getmtime, path)
                    except OSError:
                        continue
                    candidates.append((mtime, path))
        candidates.sort(key=lambda c: c[0])

        removed = 0
        for _mtime, path in candidates:
            try:
                # P1: hapus file di thread.
                await asyncio.to_thread(os.remove, path)
            except OSError as e:
                logger.warning("cleanup: gagal hapus segmen %s: %s", path, e)
                continue
            removed += 1
            deleted_total += 1
            if removed % 10 == 0:
                pct = await _disk_usage_pct_async(probe)
                if pct is None or pct < target_pct:
                    break
        if removed:
            logger.info("cleanup: %d segmen dihapus dari disk %s", removed, probe)
        pct = await _disk_usage_pct_async(probe)
        if pct is not None and pct >= threshold_pct:
            logger.warning(
                "cleanup: disk %s tetap penuh %.1f%% setelah semua segmen "
                "yang boleh dihapus habis",
                probe,
                pct,
            )
    return deleted_total


def _rclone_run_sync(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Jalankan satu perintah rclone secara sinkron (untuk asyncio.to_thread).

    Raise RuntimeError bila biner rclone tidak ditemukan.
    """
    from app.services.gdrive_rclone import conf_path, find_rclone

    binary = find_rclone()
    if not binary:
        raise RuntimeError("rclone tidak ditemukan di server")
    proc = subprocess.run(
        [binary, "--config", conf_path(), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


_BATCH_DELETE_SIZE = 50


async def _rclone_delete_batch(
    remote_name: str, folder_id: str, names: list[str]
) -> int:
    """Hapus banyak file sekaligus via satu `rclone delete --files-from`.

    Temuan 3.10: sebelumnya satu proses `rclone delete` (startup +
    auth, timeout 120 dtk) PER FILE, jadi cleanup ribuan segmen
    berjalan berjam-jam. Daftar nama ditulis ke file temp (satu baris
    per path, relatif terhadap folder), lalu satu proses menghapus
    semuanya. Return jumlah yang dihapus (0 bila batch gagal; nama yang
    mengandung newline dilewati karena tidak aman di daftar
    --files-from).

    P1: remote_name dan folder_id divalidasi (validate_remote_name /
    _validate_rclone_path) sebelum jadi argv; nama file dari lsjson
    diperiksa _is_safe_rclone_delete_name, nama yang tidak lolos
    (komponen '..', absolut, diawali '-') TIDAK dihapus, hanya dicatat
    di log dan dilewati.
    """
    import tempfile

    from app.services.gdrive_rclone import _validate_rclone_path
    from app.services.gdrive_rclone import validate_remote_name

    try:
        remote_name = validate_remote_name(remote_name)
        folder_id = _validate_rclone_path(folder_id)
    except ValueError as e:
        logger.warning("cleanup rclone: batch delete dibatalkan: %s", e)
        return 0
    safe: list[str] = []
    for n in names:
        if not n or "\n" in n or "\r" in n:
            continue
        if not _is_safe_rclone_delete_name(n):
            logger.warning(
                "cleanup rclone: nama file tidak aman, dilewati (tidak dihapus): %r",
                n,
            )
            continue
        safe.append(n)
    if not safe:
        return 0
    fd, list_path = tempfile.mkstemp(prefix="rclone-del-", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(safe) + "\n")
        rc, _out, err = await asyncio.to_thread(
            _rclone_run_sync,
            ["delete", f"{remote_name}:{folder_id}", "--files-from", list_path],
            300,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("cleanup rclone: batch delete gagal: %s", e)
        return 0
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass
    if rc != 0:
        logger.warning(
            "cleanup rclone: batch delete gagal: %s", err.strip()[:200]
        )
        return 0
    return len(safe)


async def _rclone_usage_pct(remote_name: str) -> float | None:
    """Pemakaian remote dalam persen via `rclone about --json`,
    atau None bila rclone/remote tidak bisa dibaca."""
    try:
        rc, out, _ = await asyncio.to_thread(
            _rclone_run_sync, ["about", f"{remote_name}:", "--json"], 10
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("cleanup rclone: about %s gagal: %s", remote_name, e)
        return None
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    total, used = data.get("total"), data.get("used")
    if not isinstance(total, int) or total <= 0 or not isinstance(used, int):
        return None
    return used / total * 100


async def cleanup_rclone_remote(
    db: AsyncSession,
    remote_name: str,
    threshold_pct: float,
    target_pct: float,
    max_files: int = 200,
) -> int:
    """Hapus file rekaman tertua DI REMOTE rclone sampai usage < target.

    KEPUTUSAN DESAIN: record_disk bernilai "rclone:{remote}" artinya
    rekaman ditulis lokal dulu (staging), lalu di-upload ke remote itu;
    JANGAN pakai `rclone mount` (FUSE) sebagai jalur utama. Fungsi ini
    membersihkan sisi remote saja, bukan disk lokal.

    Bila usage remote >= threshold, file .mp4 di folder tujuan kamera
    (folder_id dari tabel google_drive_folders, termasuk subfolder per
    kamera) dihapus dari yang tertua, usage dicek ulang tiap 10 file.
    HANYA file .mp4 rekaman di folder tujuan itu yang dihapus, bukan
    file lain. Return jumlah file yang dihapus.

    Area 5, 5.6: `max_files` membatasi satu putaran (dulu satu putaran
    bisa menghapus ribuan file dengan `rclone delete` 120 dtk per file,
    berjalan berjam-jam sambil menahan satu sesi DB). Sisa file
    dihapus putaran berikut.
    """
    from app.services.gdrive_rclone import _validate_rclone_path
    from app.services.gdrive_rclone import validate_remote_name

    try:
        remote_name = validate_remote_name(remote_name)
    except ValueError as e:
        logger.warning("cleanup rclone: remote tidak valid: %s", e)
        return 0
    pct = await _rclone_usage_pct(remote_name)
    if pct is None:
        logger.warning(
            "cleanup rclone: tidak bisa baca pemakaian remote %s "
            "(rclone hilang atau remote tidak ada)",
            remote_name,
        )
        return 0
    if pct < threshold_pct:
        return 0
    logger.info(
        "cleanup rclone: remote %s penuh %.1f%% (ambang %.1f%%), "
        "hapus file rekaman tertua",
        remote_name,
        pct,
        threshold_pct,
    )
    folders = (await db.execute(select(GoogleDriveFolder))).scalars().all()
    if not folders:
        logger.warning(
            "cleanup rclone: tidak ada folder tujuan di google_drive_folders, "
            "remote %s tidak dibersihkan",
            remote_name,
        )
        return 0

    deleted_total = 0
    for folder in folders:
        folder_id = (folder.folder_id or "").strip()
        if not folder_id:
            continue
        # P1: folder_id dari DB dipakai mentah sebagai path remote;
        # validasi sebelum jadi argv rclone.
        try:
            folder_id = _validate_rclone_path(folder_id)
        except ValueError as e:
            logger.warning(
                "cleanup rclone: folder_id tidak valid, dilewati: %s", e
            )
            continue
        # Daftar file rekaman (rekursif, subfolder per kamera ikut).
        files: list[tuple[str, str]] = []  # (modtime/nama, path relatif)
        try:
            rc, out, _ = await asyncio.to_thread(
                _rclone_run_sync,
                ["lsjson", "--recursive", f"{remote_name}:{folder_id}", "--files-only", "--no-mimetype"],
                60,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("cleanup rclone: lsjson %s gagal: %s", folder_id, e)
            continue
        if rc == 0:
            try:
                entries = json.loads(out)
            except ValueError:
                entries = []
            for entry in entries:
                name = entry.get("Path") or entry.get("Name") or ""
                if not name.lower().endswith(".mp4"):
                    continue
                files.append((entry.get("ModTime") or "", name))
            files.sort(key=lambda f: (f[0], f[1]))
        else:
            # Fallback bila lsjson tidak tersedia: lsf --format ps
            # (path;size, dipisah ';'), urut nama = urut waktu karena nama
            # segmen mengandung timestamp YYYY-MM-DD_HH-MM-SS.
            try:
                rc2, out2, _ = await asyncio.to_thread(
                    _rclone_run_sync,
                    ["lsf", "--recursive", f"{remote_name}:{folder_id}",
                     "--files-only", "--format", "ps"],
                    60,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("cleanup rclone: lsf %s gagal: %s", folder_id, e)
                continue
            if rc2 != 0:
                continue
            for line in out2.splitlines():
                name = line.rsplit(";", 1)[0].strip()
                if not name.lower().endswith(".mp4"):
                    continue
                files.append((name, name))
            files.sort(key=lambda f: f[0])

        # Temuan 3.10: hapus per batch (satu proses `rclone delete
        # --files-from` per 50 file), bukan satu proses per file.
        # Usage dicek ulang tiap batch, bukan tiap 10 file.
        removed = 0
        names = [name for _sort_key, name in files]
        for i in range(0, len(names), _BATCH_DELETE_SIZE):
            if deleted_total >= max_files:
                break
            chunk = names[i : i + _BATCH_DELETE_SIZE]
            chunk = chunk[: max_files - deleted_total]
            n = await _rclone_delete_batch(remote_name, folder_id, chunk)
            removed += n
            deleted_total += n
            if n < len(chunk):
                logger.warning(
                    "cleanup rclone: batch delete hanya menghapus %d/%d, "
                    "berhenti di folder ini",
                    n, len(chunk),
                )
                break
            if deleted_total >= max_files:
                logger.warning(
                    "cleanup rclone: batas %d file per putaran tercapai, "
                    "sisa dihapus putaran berikut",
                    max_files,
                )
                break
            pct = await _rclone_usage_pct(remote_name)
            if pct is None or pct < target_pct:
                break
        if removed:
            logger.info(
                "cleanup rclone: %d file rekaman dihapus dari %s:%s",
                removed,
                remote_name,
                folder_id,
            )
        if deleted_total >= max_files:
            break
        pct = await _rclone_usage_pct(remote_name)
        if pct is not None and pct < target_pct:
            break
    if deleted_total:
        # 6.4: file dihapus dari remote, buang cache lsjson remote itu
        # supaya segmen yang sudah dihapus tidak lagi disajikan.
        from app.services.gdrive_rclone import invalidate_lsjson_cache

        invalidate_lsjson_cache(remote_name)
        pct = await _rclone_usage_pct(remote_name)
        if pct is not None and pct >= threshold_pct:
            logger.warning(
                "cleanup rclone: remote %s tetap penuh %.1f%% setelah semua "
                "file rekaman yang boleh dihapus habis",
                remote_name,
                pct,
            )
    return deleted_total


def _parse_modtime(value: str | None) -> float | None:
    """Timestamp ModTime rclone (ISO 8601) ke epoch, atau None bila tak bisa diparse."""
    from datetime import datetime, timezone

    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


async def cleanup_folder_retention(db: AsyncSession, max_files: int = 200) -> int:
    """Retensi per folder Drive: hapus file .mp4 yang lebih tua dari
    google_drive_folders.retention_days di folder itu.

    Remote default "gdrive". Bila rclone tidak ada, lewati diam-diam
    (return 0). Hanya file .mp4 yang dihapus; file yang ModTime-nya
    tidak bisa diparse dilewati (tidak ditebak). Return jumlah file
    yang dihapus.

    Area 5, 5.6: `max_files` membatasi satu putaran supaya tidak
    berjalan berjam-jam sambil menahan satu sesi DB; sisa file dihapus
    putaran berikut.
    """
    import time as _time

    from app.services.gdrive_rclone import REMOTE_NAME

    folders = (
        await db.execute(
            select(GoogleDriveFolder).where(
                GoogleDriveFolder.retention_days.is_not(None)
            )
        )
    ).scalars().all()
    deleted_total = 0
    for folder in folders:
        days = folder.retention_days
        if not days or days <= 0:
            continue
        folder_id = (folder.folder_id or "").strip()
        if not folder_id:
            continue
        # P1: folder_id dari DB dipakai mentah sebagai path remote;
        # validasi sebelum jadi argv rclone.
        try:
            from app.services.gdrive_rclone import _validate_rclone_path

            folder_id = _validate_rclone_path(folder_id)
        except ValueError as e:
            logger.warning(
                "retensi folder: folder_id tidak valid, dilewati: %s", e
            )
            continue
        cutoff = _time.time() - days * 86400
        try:
            rc, out, _ = await asyncio.to_thread(
                _rclone_run_sync,
                ["lsjson", "--recursive", f"{REMOTE_NAME}:{folder_id}", "--files-only", "--no-mimetype"],
                60,
            )
        except RuntimeError as e:
            # rclone tidak ada di server: lewati diam-diam.
            logger.debug("retensi folder: rclone tidak tersedia: %s", e)
            continue
        except Exception as e:  # noqa: BLE001
            logger.warning("retensi folder: lsjson %s gagal: %s", folder_id, e)
            continue
        if rc != 0:
            continue
        try:
            entries = json.loads(out)
        except ValueError:
            continue
        # Temuan 3.10: kumpulkan dulu yang kedaluwarsa, lalu hapus per
        # batch (satu proses `rclone delete --files-from` per 50 file),
        # bukan satu proses per file.
        expired: list[str] = []
        for entry in entries:
            name = entry.get("Path") or entry.get("Name") or ""
            if not name.lower().endswith(".mp4"):
                continue
            mtime = _parse_modtime(entry.get("ModTime"))
            if mtime is None or mtime >= cutoff:
                continue
            expired.append(name)
        removed = 0
        for i in range(0, len(expired), _BATCH_DELETE_SIZE):
            if deleted_total >= max_files:
                break
            chunk = expired[i : i + _BATCH_DELETE_SIZE]
            chunk = chunk[: max_files - deleted_total]
            n = await _rclone_delete_batch(REMOTE_NAME, folder_id, chunk)
            removed += n
            deleted_total += n
            if n < len(chunk):
                break
            if deleted_total >= max_files:
                logger.warning(
                    "retensi folder: batas %d file per putaran tercapai, "
                    "sisa dihapus putaran berikut",
                    max_files,
                )
                break
        if removed:
            logger.info(
                "retensi folder: %d file dihapus dari %s:%s (retensi %d hari)",
                removed,
                REMOTE_NAME,
                folder_id,
                days,
            )
        if deleted_total >= max_files:
            break
    if deleted_total:
        # 6.4: file dihapus dari remote, buang cache lsjson-nya.
        from app.services.gdrive_rclone import invalidate_lsjson_cache

        invalidate_lsjson_cache(REMOTE_NAME)
    return deleted_total
