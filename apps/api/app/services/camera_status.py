"""Poller status kamera: sinkronkan is_online/last_seen_at dari MediaMTX ke DB.

Dipakai oleh worker terjadwal (Fase 1+) dan endpoint admin. Perubahan status
nantinya di-broadcast via WebSocket (/ws).
"""

from __future__ import annotations

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

    for stream in streams:
        # Main selalu tersambung (sourceOnDemand false), jadi `ready` runtime
        # = kamera benar-benar mengirim video — sama dengan v2
        # check_mediamtx_path_ready.
        online = await mediamtx.path_ready(_path_name(stream.id))

        if online != stream.is_online:
            stream.is_online = online
            stream.last_seen_at = now if online else stream.last_seen_at
            changes.append({"stream_id": stream.id, "is_online": online})

    if changes:
        await db.commit()

    return changes
