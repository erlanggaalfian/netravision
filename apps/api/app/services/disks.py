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


def _rclone_disks() -> list[dict]:
    """Entri disk untuk tiap remote rclone di conf.

    Kapasitas dari `rclone about {remote}: --json` (timeout 10 detik per
    remote). Remote yang gagal dibaca dilewati diam-diam.
    """
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
    out: list[dict] = []
    for name in names:
        try:
            proc = subprocess.run(
                [binary, "--config", conf, "about", f"{name}:", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0:
            continue
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            continue
        total = data.get("total")
        used = data.get("used")
        free = data.get("free")
        if not isinstance(total, int) or total <= 0:
            continue
        if not isinstance(used, int):
            used = total - free if isinstance(free, int) else 0
        if not isinstance(free, int):
            free = total - used
        unit = _pick_unit(total)
        out.append(
            {
                "mount": f"rclone:{name}",
                "size_bytes": total,
                "avail_bytes": free,
                "size_human": _human(total, unit),
                "avail_human": _human(free, unit),
                "fstype": "rclone",
                "usage_pct": round(used / total * 100, 1),
            }
        )
    return out


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
        pct = _disk_usage_pct(probe)
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
            uploaded: set[str] | None = None
            if stream.storage_mode in ("drive", "both"):
                res = await db.execute(
                    select(DriveUpload.segment_name).where(
                        DriveUpload.stream_id == stream.id
                    )
                )
                uploaded = {r[0] for r in res.all()}
            rec_dir = camera_rec_dir(stream, recordings_dir)
            try:
                names = os.listdir(rec_dir)
            except OSError:
                continue
            for name in names:
                if not SEGMENT_RE.match(name):
                    continue
                if uploaded is not None and name not in uploaded:
                    continue
                path = os.path.join(rec_dir, name)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                candidates.append((mtime, path))
        candidates.sort(key=lambda c: c[0])

        removed = 0
        for _mtime, path in candidates:
            try:
                os.remove(path)
            except OSError as e:
                logger.warning("cleanup: gagal hapus segmen %s: %s", path, e)
                continue
            removed += 1
            deleted_total += 1
            if removed % 10 == 0:
                pct = _disk_usage_pct(probe)
                if pct is None or pct < target_pct:
                    break
        if removed:
            logger.info("cleanup: %d segmen dihapus dari disk %s", removed, probe)
        pct = _disk_usage_pct(probe)
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
    """
    remote_name = (remote_name or "").strip()
    if not remote_name:
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
        # Daftar file rekaman (rekursif, subfolder per kamera ikut).
        files: list[tuple[str, str]] = []  # (modtime/nama, path relatif)
        try:
            rc, out, _ = await asyncio.to_thread(
                _rclone_run_sync,
                ["lsjson", "--recursive", f"{remote_name}:{folder_id}", "--files-only"],
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

        removed = 0
        for _sort_key, name in files:
            try:
                rc3, _, err3 = await asyncio.to_thread(
                    _rclone_run_sync,
                    ["delete", f"{remote_name}:{folder_id}/{name}"],
                    120,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("cleanup rclone: delete %s gagal: %s", name, e)
                continue
            if rc3 != 0:
                logger.warning(
                    "cleanup rclone: delete %s gagal: %s", name, err3.strip()[:200]
                )
                continue
            removed += 1
            deleted_total += 1
            if removed % 10 == 0:
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
        pct = await _rclone_usage_pct(remote_name)
        if pct is not None and pct < target_pct:
            break
    if deleted_total:
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


async def cleanup_folder_retention(db: AsyncSession) -> int:
    """Retensi per folder Drive: hapus file .mp4 yang lebih tua dari
    google_drive_folders.retention_days di folder itu.

    Remote default "gdrive". Bila rclone tidak ada, lewati diam-diam
    (return 0). Hanya file .mp4 yang dihapus; file yang ModTime-nya
    tidak bisa diparse dilewati (tidak ditebak). Return jumlah file
    yang dihapus.
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
        cutoff = _time.time() - days * 86400
        try:
            rc, out, _ = await asyncio.to_thread(
                _rclone_run_sync,
                ["lsjson", "--recursive", f"{REMOTE_NAME}:{folder_id}", "--files-only"],
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
        removed = 0
        for entry in entries:
            name = entry.get("Path") or entry.get("Name") or ""
            if not name.lower().endswith(".mp4"):
                continue
            mtime = _parse_modtime(entry.get("ModTime"))
            if mtime is None or mtime >= cutoff:
                continue
            try:
                rc3, _, err3 = await asyncio.to_thread(
                    _rclone_run_sync,
                    ["delete", f"{REMOTE_NAME}:{folder_id}/{name}"],
                    120,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("retensi folder: delete %s gagal: %s", name, e)
                continue
            if rc3 != 0:
                logger.warning(
                    "retensi folder: delete %s gagal: %s", name, err3.strip()[:200]
                )
                continue
            removed += 1
            deleted_total += 1
        if removed:
            logger.info(
                "retensi folder: %d file dihapus dari %s:%s (retensi %d hari)",
                removed,
                REMOTE_NAME,
                folder_id,
                days,
            )
    return deleted_total
