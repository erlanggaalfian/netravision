"""Router admin: baca audit_logs (2.12).

Semua endpoint butuh super_admin. Path /api/* mengikuti pola
/admin/api-access-logs (admin_keys.py): body tetap array, total
untuk pagination bernomor dikirim lewat header X-Total-Count.

Filter:
- actor_id: id user pelaku (persis).
- resource: template path, mis. /api/admin/users/{user_id} (persis).
- action: substring atas "METHOD /path/aktual", mis. "POST" atau
  "POST /api/admin/users" (LIKE %...%, audit_logs kecil dan
  di-retensi 90 hari, jadi pindai substring masih murah).
- date_from / date_to: rentang created_at, inklusif.

Registrasi router di app/main.py dilakukan koordinator (lihat
laporan Area A): app.include_router(admin_audit.router, prefix="/api").
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limited
from app.core.rbac import require_roles
from app.db.session import get_db_with_timeout
from app.models.misc import AuditLog

# Kelola jejak audit hanya super_admin (admin biasa tidak boleh).
router = APIRouter(
    tags=["admin-audit"],
    dependencies=[
        Depends(require_roles("super_admin")),
        Depends(rate_limited(20, 60)),
    ],
)


def _log_to_out(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "actor_id": log.actor_id,
        "action": log.action,
        "resource": log.resource,
        "resource_id": log.resource_id,
        "detail": log.detail,
        "ip": log.ip,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


@router.get("/admin/audit-logs")
async def list_audit_logs(
    actor_id: int | None = Query(default=None),
    resource: str | None = Query(default=None, max_length=128),
    action: str | None = Query(
        default=None,
        max_length=128,
        description="substring atas action, mis. POST atau POST /api/admin/users",
    ),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=0, le=500),
    offset: int = Query(default=0, ge=0),
    # 2.19: bacaan berat atas tabel yang tumbuh: statement_timeout
    # per-endpoint 60 detik (default engine 30 detik).
    db: AsyncSession = Depends(get_db_with_timeout(60)),
    response: Response = None,
):
    q = select(AuditLog).order_by(AuditLog.id.desc())
    if actor_id is not None:
        q = q.where(AuditLog.actor_id == actor_id)
    if resource:
        q = q.where(AuditLog.resource == resource)
    if action:
        q = q.where(AuditLog.action.contains(action))
    if date_from is not None:
        q = q.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        q = q.where(AuditLog.created_at <= date_to)
    # Total untuk pagination bernomor (perintah user 2026-11-17): dikirim
    # lewat header X-Total-Count supaya body tetap array dan kontrak
    # /api/* tidak berubah.
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    q = q.limit(limit).offset(offset)
    res = await db.execute(q)
    return [_log_to_out(log) for log in res.scalars().all()]
