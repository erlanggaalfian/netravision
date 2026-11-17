"""Retensi log akses embed (api_access_logs).

6.8: tabel api_access_logs tumbuh tanpa batas (satu baris per
request embed) dan sebelumnya hanya bisa dihapus manual lewat
DELETE /admin/api-access-logs. Fungsi di sini menghapus baris
lebih tua dari `days` hari (default 90, sama seperti retensi
jejak upload dan audit_logs) dan mengembalikan jumlah baris
yang dihapus. Penjadwalan TIDAK ada di modul ini: koordinator
memasang prune_api_access_logs ke loop retensi harian di
app/main.py::_retention_loop, di samping prune_drive_upload_traces
dan prune_audit_logs (lihat laporan Area C 2026-11-17 untuk titik
wiring persisnya).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.keys import ApiAccessLog

log = logging.getLogger("netravision.api_access_log_retention")

DEFAULT_RETENTION_DAYS = 90


async def prune_api_access_logs(db: AsyncSession, days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Hapus baris api_access_logs lebih tua dari `days` hari.

    Return jumlah baris yang dihapus. Dipanggil harian dari
    _retention_loop (main.py) dengan sesi DB sendiri, seperti
    prune_drive_upload_traces dan prune_audit_logs.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # synchronize_session=False: jangan evaluasi WHERE di Python untuk
    # objek di sesi (di SQLite datetime kembali naive sehingga
    # perbandingan naive vs aware melempar TypeError); sesi ini
    # langsung di-commit dan dibuang sesudahnya.
    res = await db.execute(
        delete(ApiAccessLog)
        .where(ApiAccessLog.created_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    n = res.rowcount or 0
    if n:
        log.info("retensi log akses embed: %d baris api_access_logs dihapus", n)
    return n
