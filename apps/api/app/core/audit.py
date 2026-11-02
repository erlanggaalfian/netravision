"""Middleware audit: catat setiap request non-GET ke /api/admin/* ke audit_logs.

- Membuka session DB sendiri (middleware berjalan di luar dependency injection,
  jadi tidak bisa memakai Depends(get_db)).
- Di test, factory session bisa di-override via ``app.state.audit_session_factory``.
- Defensif: kegagalan pencatatan TIDAK BOLEH menggagalkan request.
"""

import logging

from app.core.config import get_settings
from app.core.metrics import path_template_for_scope
from app.core.security import decode_token
from app.db.session import get_session_factory
from app.models.misc import AuditLog

log = logging.getLogger("netravision.audit")

_ADMIN_PREFIX = "/api/admin"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _client_ip(scope) -> str | None:
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
    fwd = headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else None


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


def _should_audit(scope) -> bool:
    if scope["type"] != "http":
        return False
    if scope["method"] in _SAFE_METHODS:
        return False
    path = scope.get("path", "")
    return path == _ADMIN_PREFIX or path.startswith(_ADMIN_PREFIX + "/")


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
