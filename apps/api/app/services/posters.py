"""Worker poster: tangkap satu frame dari RTSP via ffmpeg (best-effort).

Poster dipakai tile kamera sebelum live diputar. Tanpa ffmpeg terinstal,
worker diam (warning sekali) — bukan error fatal.
"""

import asyncio
import logging
import os
import shutil
import subprocess
from urllib.parse import urlparse

from sqlalchemy import select

log = logging.getLogger("netravision.posters")

_FFMPEG_WARNED = False


def capture_poster(
    stream_id: int,
    rtsp_url: str,
    out_path: str,
    timeout: int = 15,
) -> bool:
    """Tangkap satu frame JPEG. Return True bila berkas valid tertulis."""
    if not shutil.which("ffmpeg"):
        return False
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-rtsp_transport", "tcp",
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


async def run_poster_loop(interval_sec: int = 60) -> None:
    """Loop abadi: tiap interval, tangkap poster semua stream aktif."""
    global _FFMPEG_WARNED
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.models.streams import Stream

    if not shutil.which("ffmpeg"):
        if not _FFMPEG_WARNED:
            log.warning("ffmpeg tidak ditemukan — worker poster dinonaktifkan")
            _FFMPEG_WARNED = True
        return

    settings = get_settings()
    rtsp_host = urlparse(settings.mediamtx_api_url).hostname or "127.0.0.1"
    try:
        while True:
            try:
                async with get_session_factory()() as db:
                    result = await db.execute(
                        select(Stream).where(Stream.is_active.is_(True))
                    )
                    streams = list(result.scalars().all())
                for s in streams:
                    # Lewat MediaMTX (berbagi sesi dengan penonton), bukan ke
                    # kamera langsung: banyak kamera hanya mengizinkan 1 sesi
                    # RTSP, poster langsung akan menolak/menendang live view.
                    path = f"stream_{s.id}_sub" if s.sub_url else f"stream_{s.id}"
                    url = f"rtsp://{rtsp_host}:8554/{path}"
                    out = os.path.join(
                        settings.posters_dir, f"stream_{s.id}.jpg"
                    )
                    ok = await asyncio.to_thread(
                        capture_poster, s.id, url, out
                    )
                    if not ok:
                        log.debug("poster stream %s dilewati", s.id)
            except Exception as e:  # satu putaran gagal tidak mematikan loop
                log.warning("poster loop gagal: %s", e)
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        pass
