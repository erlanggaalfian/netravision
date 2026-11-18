"""Poller status kamera: sinkronkan is_online/last_seen_at dari MediaMTX ke DB.

Dipakai oleh worker terjadwal (Fase 1+) dan endpoint admin. Perubahan status
nantinya di-broadcast via WebSocket (/ws).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.streams import Stream
from app.services.mediamtx import MediaMTXClient


def _path_name(stream_id: int, sub: bool = False) -> str:
    return f"stream_{stream_id}_sub" if sub else f"stream_{stream_id}"


async def poll_once(db: AsyncSession, mediamtx: MediaMTXClient) -> list[dict]:
    """Satu putaran cek status semua stream aktif.

    Online = sumber path stream_{id} sedang tersambung (runtime ready).
    Update DB hanya bila status berubah; return daftar perubahan.
    """
    result = await db.execute(select(Stream).where(Stream.is_active.is_(True)))
    streams = list(result.scalars().all())

    changes: list[dict] = []
    now = datetime.now(timezone.utc)

    # Cek semua path PARALEL: sekuensial, 68 kamera x timeout HTTP
    # bisa melebihi interval broadcaster 10 detik sehingga status
    # selalu tertinggal. Satu kamera yang error tidak menggugurkan
    # yang lain (statusnya dipertahankan, bukan dianggap offline).
    # Semaphore 8 (sama seperti sync loop) membatasi koneksi HTTP
    # bersamaan ke control API MediaMTX; gather mempertahankan urutan
    # hasil sesuai urutan streams.
    sem = asyncio.Semaphore(8)

    async def _ready(name: str) -> bool:
        async with sem:
            return await mediamtx.path_ready(name)

    results = await asyncio.gather(
        *(_ready(_path_name(s.id)) for s in streams),
        return_exceptions=True,
    )
    for stream, online in zip(streams, results):
        if isinstance(online, Exception):
            continue
        online = bool(online)
        if online != stream.is_online:
            stream.is_online = online
            stream.last_seen_at = now if online else stream.last_seen_at
            changes.append({"stream_id": stream.id, "is_online": online})

    if changes:
        await db.commit()

    return changes
