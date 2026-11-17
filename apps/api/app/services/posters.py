"""Worker poster: tangkap satu frame dari RTSP via ffmpeg (best-effort).

Poster dipakai tile kamera sebelum live diputar. Tanpa ffmpeg terinstal,
worker diam (warning sekali) — bukan error fatal.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import time
from urllib.parse import urlparse

from sqlalchemy import select

log = logging.getLogger("netravision.posters")

_FFMPEG_WARNED = False

# Area 5, 5.5: tangkap poster paralel (dulu sekuensial 68 kamera x
# ffmpeg 15 dtk, putaran bisa 17 menit). 6 penangkapan bersamaan cukup
# untuk memangkas putaran ke kisaran belasan detik tanpa membanjiri
# MediaMTX dengan 68 sesi RTSP sekaligus.
_POSTER_MAX_CONCURRENCY = 6
# Satu putaran tidak boleh menggantung tanpa batas.
_POSTER_ROUND_TIMEOUT_SEC = 300

# JPEG poster abu-abu polos (solid gray 800x448, q=4) hanya ~2-3 KB,
# sedangkan foto asli 28 KB ke atas. Bila hasil tangkap di bawah ambang
# ini dan poster lama sudah ada, jangan timpa poster lama yang masih bagus.
_MIN_POSTER_BYTES = 8192


def capture_poster(
    stream_id: int,
    rtsp_url: str,
    out_path: str,
    timeout: int = 15,
) -> bool:
    """Tangkap satu frame JPEG. Return True bila berkas valid tertulis."""
    if not shutil.which("ffmpeg"):
        return False
    # Temuan 3.14: URL yang mengandung newline ditolak.
    if "\n" in rtsp_url or "\r" in rtsp_url:
        log.warning("poster stream %s ditolak: URL mengandung newline", stream_id)
        return False
    # URL berkredensial TIDAK PERNAH dilewatkan sebagai argv ffmpeg
    # (terlihat di `ps` oleh semua user di server). Penangkap poster
    # hanya memakai URL MediaMTX tanpa kredensial; URL berkredensial
    # ditolak daripada dibocorkan.
    if urlparse(rtsp_url).username or urlparse(rtsp_url).password:
        log.warning(
            "poster stream %s ditolak: URL mengandung kredensial", stream_id
        )
        return False
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    # URL dilewatkan langsung sebagai -i. Demuxer concat TIDAK
    # meneruskan -rtsp_transport ke demuxer RTSP, sehingga ffmpeg jatuh
    # ke UDP dan MediaMTX menolaknya (461 Unsupported Transport);
    # semua tangkapan poster gagal sejak concat dipakai. URL MediaMTX
    # tidak berisi kredensial, jadi aman di argv.
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-rtsp_transport", "tcp",
                # Hanya decode keyframe. Tanpa ini, frame pertama yang
                # keluar dari decoder HEVC sering abu-abu polos: decoder
                # belum melihat keyframe sehingga gagal cari reference
                # ("Could not find ref with POC") lalu mengeluarkan frame
                # kosong bernilai gray 128. Kamera yang URL-nya tertulis
                # H.264 pun ternyata mengirim HEVC (terbukti di 356/358/
                # 360/361), jadi ini bukan masalah codec semata.
                "-skip_frame", "nokey",
                "-i", rtsp_url,
                "-frames:v", "1",
                "-q:v", "4",
                # Nama berkas *.tmp tak bisa ditebak formatnya — paksa JPEG.
                "-f", "image2", "-c:v", "mjpeg",
                tmp,
            ],
            timeout=timeout,
            capture_output=True,
        )
        if r.returncode == 0 and os.path.getsize(tmp) > 0:
            if (
                os.path.getsize(tmp) < _MIN_POSTER_BYTES
                and os.path.exists(out_path)
            ):
                log.info(
                    "poster stream %s dicurigai abu-abu (%s byte) — "
                    "poster lama dipertahankan",
                    stream_id, os.path.getsize(tmp),
                )
                os.remove(tmp)
                return False
            os.replace(tmp, out_path)
            return True
        log.info(
            "poster stream %s gagal (ffmpeg %s): %s",
            stream_id, r.returncode, r.stderr.decode(errors="replace")[-200:],
        )
        os.remove(tmp)
        return False
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError) as e:
        log.debug("poster stream %s gagal: %s", stream_id, e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


async def _poster_round(streams, rtsp_host: str, posters_dir: str,
                        interval_sec: int,
                        max_concurrency: int = _POSTER_MAX_CONCURRENCY,
                        _capture=capture_poster) -> int:
    """Satu putaran tangkap poster semua stream aktif, paralel.

    Kamera yang posternya masih segar (diubah < 2x interval lalu)
    dilewati: mengulang 68 sesi RTSP tiap 60 detik hanya untuk
    menimpa poster yang baru saja diambil tidak ada gunanya (5.5).
    Return jumlah poster yang berhasil ditangkap.
    """
    sem = asyncio.Semaphore(max_concurrency)
    fresh_after = 2 * max(interval_sec, 1)

    async def _one(s) -> bool:
        url = f"rtsp://{rtsp_host}:8554/stream_{s.id}"
        out = os.path.join(posters_dir, f"stream_{s.id}.jpg")
        try:
            if os.path.exists(out) and time.time() - os.path.getmtime(out) < fresh_after:
                return False
        except OSError:
            pass
        async with sem:
            return bool(await asyncio.to_thread(_capture, s.id, url, out))

    results = await asyncio.gather(
        *[_one(s) for s in streams], return_exceptions=True
    )
    ok = 0
    for s, r in zip(streams, results):
        if r is True:
            ok += 1
        elif isinstance(r, Exception):
            log.warning("poster stream %s gagal: %s", s.id, r)
    return ok


async def run_poster_loop(interval_sec: int = 60, initial_delay: float = 0,
                         max_concurrency: int = _POSTER_MAX_CONCURRENCY) -> None:
    """Loop abadi: tiap interval, tangkap poster semua stream aktif.

    Area 5, 5.11: `initial_delay` menunda putaran pertama supaya tidak
    semua loop start bersamaan saat API baru naik.
    """
    global _FFMPEG_WARNED
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.models.streams import Stream
    from app.services.loop_health import (
        record_failure,
        record_success,
        record_tick,
    )

    if not shutil.which("ffmpeg"):
        if not _FFMPEG_WARNED:
            log.warning("ffmpeg tidak ditemukan — worker poster dinonaktifkan")
            _FFMPEG_WARNED = True
        return

    settings = get_settings()
    rtsp_host = urlparse(settings.mediamtx_api_url).hostname or "127.0.0.1"
    try:
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            started = time.monotonic()
            record_tick("poster")
            try:
                async with get_session_factory()() as db:
                    result = await db.execute(
                        select(Stream).where(Stream.is_active.is_(True))
                    )
                    streams = list(result.scalars().all())
                # Lewat MediaMTX dari path MAIN: selalu tersambung (pola
                # v2), tanpa membuka sesi RTSP baru ke kamera dan tanpa
                # menyalakan transkode sub hanya untuk poster.
                try:
                    ok = await asyncio.wait_for(
                        _poster_round(
                            streams, rtsp_host, settings.posters_dir,
                            interval_sec, max_concurrency,
                        ),
                        timeout=_POSTER_ROUND_TIMEOUT_SEC,
                    )
                except asyncio.TimeoutError:
                    log.warning(
                        "poster loop: putaran melebihi %ds, dilewati",
                        _POSTER_ROUND_TIMEOUT_SEC,
                    )
                    record_failure("poster", "round timeout")
                    await asyncio.sleep(interval_sec)
                    continue
                if ok:
                    log.debug("poster loop: %d poster ditangkap", ok)
                record_success(
                    "poster", (time.monotonic() - started) * 1000
                )
            except Exception as e:  # satu putaran gagal tidak mematikan loop
                log.warning("poster loop gagal: %s", e)
                record_failure("poster", e)
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        pass
