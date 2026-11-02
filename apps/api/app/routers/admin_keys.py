"""Router admin: API key embed pihak ketiga + log akses.

Semua endpoint butuh peran admin. Path /api/* persis kontrak openapi.yaml.
Yang disimpan hanya hash SHA-256 kuncinya; key penuh hanya tampil sekali
saat pembuatan (ApiKeyCreated.key).
"""

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream

router = APIRouter(tags=["admin-keys"], dependencies=[Depends(require_roles("admin"))])


class ApiKeyCreate(BaseModel):
    name: str
    stream_ids: list[int]
    domain_lock: str | None = None
    password: str | None = None
    session_limit_min: int | None = None


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    domain_lock: str | None = None
    password: str | None = None
    session_limit_min: int | None = None
    stream_ids: list[int] | None = None
    is_active: bool | None = None


def _key_to_out(key: ApiKey, stream_ids: list[int]) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "domain_lock": key.domain_lock,
        "is_active": key.is_active,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "stream_ids": stream_ids,
    }


async def _stream_ids_of(db: AsyncSession, key_id: int) -> list[int]:
    res = await db.execute(select(ApiKeyStream.stream_id).where(ApiKeyStream.api_key_id == key_id))
    return list(res.scalars().all())


async def _get_key_or_404(db: AsyncSession, key_id: int) -> ApiKey:
    res = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = res.scalars().first()
    if key is None:
        raise HTTPException(status_code=404, detail="api key tidak ditemukan")
    return key


@router.get("/admin/api-keys")
async def list_keys(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ApiKey).order_by(ApiKey.id))
    out = []
    for key in res.scalars().all():
        out.append(_key_to_out(key, await _stream_ids_of(db, key.id)))
    return out


@router.post("/admin/api-keys", status_code=201)
async def create_key(data: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    raw = secrets.token_urlsafe(32)
    key = ApiKey(
        name=data.name,
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        domain_lock=data.domain_lock,
        password_hash=hash_password(data.password) if data.password else None,
    )
    db.add(key)
    await db.flush()
    for sid in data.stream_ids:
        db.add(ApiKeyStream(api_key_id=key.id, stream_id=sid))
    await db.commit()
    await db.refresh(key)
    out = _key_to_out(key, data.stream_ids)
    out["key"] = raw  # hanya tampil sekali
    return out


@router.put("/admin/api-keys/{key_id}")
async def update_key(key_id: int, data: ApiKeyUpdate, db: AsyncSession = Depends(get_db)):
    key = await _get_key_or_404(db, key_id)
    if data.name is not None:
        key.name = data.name
    if data.domain_lock is not None:
        key.domain_lock = data.domain_lock or None
    if data.password:
        key.password_hash = hash_password(data.password)
    if data.is_active is not None:
        key.is_active = data.is_active
    if data.stream_ids is not None:
        await db.execute(delete(ApiKeyStream).where(ApiKeyStream.api_key_id == key_id))
        for sid in data.stream_ids:
            db.add(ApiKeyStream(api_key_id=key_id, stream_id=sid))
    await db.commit()
    await db.refresh(key)
    return _key_to_out(key, await _stream_ids_of(db, key_id))


@router.delete("/admin/api-keys/{key_id}")
async def delete_key(key_id: int, db: AsyncSession = Depends(get_db)):
    key = await _get_key_or_404(db, key_id)
    await db.execute(delete(ApiKeyStream).where(ApiKeyStream.api_key_id == key_id))
    await db.delete(key)
    await db.commit()
    return {"ok": True}


def _log_to_out(log: ApiAccessLog) -> dict:
    return {
        "id": log.id,
        "key_id": log.api_key_id,
        "stream_id": log.stream_id,
        "ip": log.ip,
        "accessed_at": log.created_at.isoformat() if log.created_at else None,
    }


@router.get("/admin/api-access-logs")
async def list_logs(
    key_id: int | None = Query(default=None),
    limit: int = Query(default=50, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(ApiAccessLog).order_by(ApiAccessLog.id.desc()).limit(limit)
    if key_id is not None:
        q = q.where(ApiAccessLog.api_key_id == key_id)
    res = await db.execute(q)
    return [_log_to_out(log) for log in res.scalars().all()]


@router.delete("/admin/api-access-logs")
async def clear_logs(db: AsyncSession = Depends(get_db)):
    await db.execute(delete(ApiAccessLog))
    await db.commit()
    return {"ok": True}


@router.get("/admin/api-access-logs/summary")
async def logs_summary(db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(ApiAccessLog.id)))).scalar() or 0
    res = await db.execute(
        select(ApiAccessLog.api_key_id, func.count(ApiAccessLog.id))
        .group_by(ApiAccessLog.api_key_id)
        .order_by(func.count(ApiAccessLog.id).desc())
    )
    by_key = [{"key_id": k, "count": c} for k, c in res.all()]
    return {"total": total, "by_key": by_key}
