"""Middleware audit: catat setiap request non-GET ke /api/admin/* ke audit_logs.

- Membuka session DB sendiri (middleware berjalan di luar dependency injection,
  jadi tidak bisa memakai Depends(get_db)).
- Di test, factory session bisa di-override via ``app.state.audit_session_factory``.
- Defensif: kegagalan pencatatan TIDAK BOLEH menggagalkan request.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import get_settings
from app.core.metrics import path_template_for_scope
from app.core.security import decode_token
from app.db.session import get_session_factory
from app.models.misc import AuditLog

log = logging.getLogger("netravision.audit")

_ADMIN_PREFIX = "/api/admin"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _client_ip(scope) -> str | None:
    """IP klien audit: percaya X-Forwarded-For HANYA dari proxy
    tepercaya, sama seperti rate_limit.client_ip (T-5). Sebelumnya
    XFF mentah dipakai tanpa syarat sehingga pelaku bisa memalsukan
    IP di audit log."""
    from app.core.rate_limit import _is_trusted_proxy

    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
    client = scope.get("client")
    peer = client[0] if client else None
    if peer and _is_trusted_proxy(peer):
        fwd = headers.get("x-forwarded-for")
        if fwd:
            first = fwd.split(",")[0].strip()
            if first:
                return first
        real = headers.get("x-real-ip", "").strip()
        if real:
            return real
    return peer


def _actor_from_scope(scope) -> tuple[int | None, str]:
    """(actor_id, actor_name) dari JWT; ("anonymous") bila tidak ada/tidak valid."""
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None, "anonymous"
    try:
        payload = decode_token(auth[7:].strip(), get_settings())
    except ValueError:
        return None, "anonymous"
    sub = str(payload.get("sub") or "")
    actor_id = int(sub) if sub.isdigit() else None
    return actor_id, str(payload.get("username") or "anonymous")


# 4.15: pembacaan admin yang sensitif ikut diaudit walau GET (daftar
# kunci + log akses dibaca massal oleh admin yang dikompromikan harus
# meninggalkan jejak).
_SENSITIVE_ADMIN_READS = (
    "/api/admin/api-keys",
    "/api/admin/api-access-logs",
)

# 4.15: semua percobaan auth ikut diaudit (login gagal/berhasil,
# refresh ditolak, guest): brute force login harus meninggalkan jejak
# di audit_logs, bukan hanya di log teks server.
_AUTH_PATHS = (
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/logout",
    "/api/auth/guest",
)

# 4.15: mutasi non-admin di luar /api/admin/* yang mengubah keadaan
# (reconnect kamera, resolve lokasi) ikut diaudit.
_EXTRA_MUTATIONS = (
    ("/api/maps/resolve-location", {"POST"}),
    ("/api/streams/", {"POST"}),
)


def _should_audit(scope) -> bool:
    if scope["type"] != "http":
        return False
    method = scope["method"]
    path = scope.get("path", "")
    if path in _AUTH_PATHS:
        return True
    if method not in _SAFE_METHODS:
        if path == _ADMIN_PREFIX or path.startswith(_ADMIN_PREFIX + "/"):
            return True
        for prefix, methods in _EXTRA_MUTATIONS:
            if method in methods and path.startswith(prefix):
                return True
        return False
    return any(
        path == p or path.startswith(p + "/") for p in _SENSITIVE_ADMIN_READS
    )


class AuditMiddleware:
    """Middleware ASGI murni."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not _should_audit(scope):
            await self.app(scope, receive, send)
            return

        status_holder: dict = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)

        try:
            await self._write_log(scope, status_holder.get("status", 0))
        except Exception as e:  # noqa: BLE001 -- audit tidak boleh menggagalkan request
            log.warning("gagal menulis audit log: %s", e)

    async def _write_log(self, scope, status_code: int) -> None:
        method = scope["method"]
        path = scope.get("path", "")
        # Template generik dari path aktual + path_params (andal terhadap
        # lazy _IncludedRouter yang route.path-nya tanpa prefix mount).
        # scope["route"] sudah diisi router setelah call di atas selesai.
        path_template = path_template_for_scope(scope)[:128]
        path_params = scope.get("path_params", {}) or {}
        resource_id = ",".join(f"{k}={v}" for k, v in path_params.items())[:64] or None
        actor_id, actor_name = _actor_from_scope(scope)

        factory = getattr(scope["app"].state, "audit_session_factory", None)
        if factory is None:
            factory = get_session_factory()
        async with factory() as db:
            db.add(
                AuditLog(
                    actor_id=actor_id,
                    action=f"{method} {path}",
                    resource=path_template,
                    resource_id=resource_id,
                    detail={"status_code": status_code, "actor": actor_name},
                    ip=_client_ip(scope),
                )
            )
            await db.commit()


async def prune_audit_logs(db, days: int = 90) -> int:
    """2.12: hapus baris audit_logs lebih tua dari `days` hari.

    audit_logs ditulis tiap aksi admin tapi tidak pernah dibaca dan
    tidak pernah dibersihkan; tanpa retensi tabel tumbuh tanpa batas.
    Dipanggil harian dari _retention_loop (main.py). Endpoint baca
    audit belum ada (butuh keputusan/fitur terpisah); retensi 90 hari
    mempertahankan jejak tiga bulan terakhir.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # synchronize_session=False: jangan evaluasi WHERE di Python untuk
    # objek di sesi (di SQLite datetime kembali naive sehingga
    # perbandingan naive vs aware melempar TypeError); sesi ini
    # langsung di-commit dan dibuang sesudahnya.
    res = await db.execute(
        delete(AuditLog)
        .where(AuditLog.created_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    n = res.rowcount or 0
    if n:
        log.info("retensi audit: %d baris audit_logs dihapus", n)
    return n
