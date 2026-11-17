"""Klaim per-segmen antar tiga jalur upload Drive (temuan audit 3.2).

Tiga loop berjalan berdampingan di proses yang sama dan membaca sumber
yang sama untuk kamera `storage_mode` drive/both:

- `drive_uploader` (rclone copyto, tiap 60 dtk),
- `drive_mirror` (salin ke staging mount rclone, tiap 30 dtk),
- `drive.DriveUploader` OAuth (scan tiap 5 menit + antrean upload).

Tanpa koordinasi, satu jalur bisa `os.remove` sumber sementara jalur
lain sedang membacanya, atau segmen yang sama ter-upload dua-tiga kali
ke tujuan berbeda. Modul ini memberi satu pemilik per segmen:
jalur yang sedang memproses (upload/salin/scan) mengklaim
`(stream_id, segment_name)`; jalur lain melewatinya.

Klaim hanya di memori proses (deploy memakai satu worker uvicorn,
lihat Area 5) dan berkedaluwarsa (TTL), supaya proses yang mati atau
task yang dibatalkan di tengah jalan tidak memblokir segmen selamanya.
Klaim harus selalu dilepas di `finally` oleh pemiliknya.
"""

import threading
import time

_LOCK = threading.Lock()
_claims: dict[tuple[int, str], tuple[str, float]] = {}

# Lebih lama dari satu putaran loop mana pun (uploader 60 dtk, mirror
# 30 dtk, scan OAuth 5 menit) dan dari grace verifikasi mirror, supaya
# klaim tidak kedaluwarsa di tengah pemrosesan yang sah.
_CLAIM_TTL_SEC = 1800.0


def try_claim(stream_id: int, segment_name: str, owner: str) -> bool:
    """Klaim segmen untuk `owner`. True bila berhasil (atau klaim sudah
    milik owner ini); False bila segmen sedang diklaim jalur lain."""
    now = time.monotonic()
    key = (stream_id, segment_name)
    with _LOCK:
        cur = _claims.get(key)
        if cur is not None:
            if cur[0] == owner:
                _claims[key] = (owner, now)
                return True
            if now - cur[1] < _CLAIM_TTL_SEC:
                return False
        _claims[key] = (owner, now)
        return True


def touch_claim(stream_id: int, segment_name: str, owner: str) -> bool:
    """Perbarui waktu klaim milik `owner` (dipakai klaim jangka panjang,
    mis. segmen mirror yang menunggu verifikasi remote). False bila
    klaim sudah bukan milik owner ini."""
    now = time.monotonic()
    key = (stream_id, segment_name)
    with _LOCK:
        cur = _claims.get(key)
        if cur is None or cur[0] != owner:
            return False
        _claims[key] = (owner, now)
        return True


def release_claim(stream_id: int, segment_name: str, owner: str) -> None:
    """Lepas klaim; hanya pemiliknya yang boleh melepas."""
    key = (stream_id, segment_name)
    with _LOCK:
        cur = _claims.get(key)
        if cur is not None and cur[0] == owner:
            del _claims[key]


def is_claimed(stream_id: int, segment_name: str) -> bool:
    """True bila segmen sedang diklaim jalur mana pun (dan belum kedaluwarsa)."""
    now = time.monotonic()
    key = (stream_id, segment_name)
    with _LOCK:
        cur = _claims.get(key)
        if cur is None:
            return False
        if now - cur[1] >= _CLAIM_TTL_SEC:
            del _claims[key]
            return False
        return True


def _reset_for_tests() -> None:
    """Kosongkan semua klaim (hanya untuk tes)."""
    with _LOCK:
        _claims.clear()
