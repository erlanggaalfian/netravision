"""Kesehatan loop latar (Area 5, temuan 5.8) + lock koordinasi retensi Drive (5.6).

Setiap loop latar mencatat denyutnya di sini (`last_tick_at`,
`last_success_at`, `consecutive_failures`, `last_error`) supaya operator
bisa melihat loop yang macet atau mati diam-diam lewat `GET /api/health`
(tidak lagi hanya `log.warning`). Registry ini in-process dan reset saat
proses restart; itu disengaja, nilainya memang status proses ini.

`drive_retention_lock()` adalah satu lock proses yang dipakai SEMUA jalur
yang menghapus file di Google Drive (retensi OAuth di `_drive_loop`,
`cleanup_rclone_remote`, `cleanup_folder_retention`), supaya dua loop
tidak menghitung usage dari snapshot basi lalu menghapus file yang sama
(temuan 5.6). Lock dibuat malas (lazy) agar aman dipakai dari fixture
test yang tiap test memakai event loop baru.
"""

import asyncio
import time

_STATE: dict[str, dict] = {}
_lock: asyncio.Lock | None = None


def drive_retention_lock() -> asyncio.Lock:
    """Satu lock proses untuk semua penghapusan file di Google Drive."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _entry(name: str) -> dict:
    return _STATE.setdefault(
        name,
        {
            "last_tick_at": None,
            "last_success_at": None,
            "consecutive_failures": 0,
            "last_error": None,
            "last_duration_ms": None,
        },
    )


def record_tick(name: str) -> None:
    """Satu putaran loop dimulai."""
    _entry(name)["last_tick_at"] = time.time()


def record_success(name: str, duration_ms: float | None = None) -> None:
    """Satu putaran loop selesai tanpa error."""
    e = _entry(name)
    e["last_success_at"] = time.time()
    e["consecutive_failures"] = 0
    e["last_error"] = None
    if duration_ms is not None:
        e["last_duration_ms"] = round(duration_ms, 1)


def record_failure(name: str, error: Exception | str) -> None:
    """Satu putaran loop gagal (loop tetap hidup, coba lagi putaran berikut)."""
    e = _entry(name)
    e["consecutive_failures"] += 1
    e["last_error"] = str(error)[:200]


def snapshot() -> dict[str, dict]:
    """Salinan status semua loop (JSON-serializable, untuk /api/health)."""
    return {name: dict(vals) for name, vals in _STATE.items()}


def reset() -> None:
    """Kosongkan registry (dipakai test)."""
    global _lock
    _STATE.clear()
    _lock = None
