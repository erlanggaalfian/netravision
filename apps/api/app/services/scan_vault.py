"""Brankas sementara URL hasil scan (4.6).

Masalah: hasil scan (best_main/best_sub/paths[].url) mengandung password
kamera mentah, termasuk password default pabrik hasil discovery, dan
dikembalikan apa adanya ke JSON. Respons itu tersebar ke body respons,
state frontend, dan job scan di memori.

Perbaikan: respons scan hanya membawa URL TEREDAKSI (password -> ****,
lihat redact_url_credentials). URL ASLI tidak pernah keluar dari server:
disimpan di brankas in-memory ini, dikunci referensi scan (job_id scan
subnet, atau scan_id sekali pakai untuk POST /admin/scan), dan hanya
dipakai kembali saat kamera dibuat dari hasil scan itu (POST
/admin/streams dengan scan_ref + URL teredaksi).

- register(ref, urls): simpan peta {url_teredaksi: url_asli}.
- resolve(ref, masked_url): kembalikan url asli bila cocok, None bila
  referensi kedaluwarsa / URL tidak dikenal (pemanggil menjawab 400
  "hasil scan kedaluwarsa, scan ulang", dan TIDAK PERNAH menyimpan
  password **** secara harfiah).
- TTL 10 menit (sama seperti job scan), maks 200 referensi; entri lama
  dibuang oportunistik supaya memori tidak tumbuh tanpa batas.
"""

import time

from app.core.security import redact_url_credentials

_TTL = 600.0
_MAX_REFS = 200

_store: dict[str, dict[str, str]] = {}
_expires: dict[str, float] = {}


def _prune(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    for ref in [r for r, until in _expires.items() if until <= now]:
        _store.pop(ref, None)
        _expires.pop(ref, None)
    while len(_store) > _MAX_REFS:
        oldest = min(_expires, key=lambda r: _expires[r])
        _store.pop(oldest, None)
        _expires.pop(oldest, None)


def register(ref: str, urls) -> None:
    """Simpan URL asli hasil scan di bawah referensi `ref`."""
    mapping: dict[str, str] = {}
    for url in urls:
        if not url:
            continue
        mapping[redact_url_credentials(url)] = url
    if not mapping:
        return
    _prune()
    entry = _store.setdefault(ref, {})
    entry.update(mapping)
    _expires[ref] = time.monotonic() + _TTL


def resolve(ref: str | None, masked_url: str | None) -> str | None:
    """Kembalikan URL asli untuk URL teredaksi, atau None."""
    if not ref or not masked_url:
        return None
    _prune()
    entry = _store.get(ref)
    if not entry:
        return None
    return entry.get(masked_url)


def reset() -> None:
    """Kosongkan brankas (dipakai test agar antar-test terisolasi)."""
    _store.clear()
    _expires.clear()
