"""Router admin: API key embed pihak ketiga + log akses.

Semua endpoint butuh peran admin. Path /api/* persis kontrak openapi.yaml.
Yang disimpan hanya hash SHA-256 kuncinya; key penuh hanya tampil sekali
saat pembuatan (ApiKeyCreated.key).
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream
from app.models.streams import Stream

# E-K1: kelola API key hanya super_admin (admin biasa tidak boleh).
router = APIRouter(tags=["admin-keys"], dependencies=[Depends(require_roles("super_admin"))])


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    stream_ids: list[int]
    domain_lock: str | None = None
    password: str | None = None
    session_limit_min: int | None = Field(default=None, ge=1, le=1440)
    custom_camera_name: str | None = None
    include_playback: bool | None = None
    show_ads: bool | None = None


class ApiKeyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    domain_lock: str | None = None
    password: str | None = None
    session_limit_min: int | None = Field(default=None, ge=1, le=1440)
    stream_ids: list[int] | None = None
    is_active: bool | None = None
    custom_camera_name: str | None = None
    include_playback: bool | None = None
    show_ads: bool | None = None


def _key_to_out(key: ApiKey, stream_ids: list[int]) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "domain_lock": key.domain_lock,
        "is_active": key.is_active,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "stream_ids": stream_ids,
        "custom_camera_name": key.custom_camera_name or "",
        "include_playback": key.include_playback,
        "show_ads": key.show_ads,
        "session_limit_min": key.session_ttl_mnt,
    }


async def _validate_stream_ids(db: AsyncSession, stream_ids: list[int]) -> list[int]:
    """Dedup (jaga urutan) + pastikan semua stream ada; 400 bila fiktif (A-S6)."""
    seen: list[int] = []
    for sid in stream_ids:
        if sid not in seen:
            seen.append(sid)
    if seen:
        found = set(
            (await db.execute(select(Stream.id).where(Stream.id.in_(seen))))
            .scalars()
            .all()
        )
        missing = [sid for sid in seen if sid not in found]
        if missing:
            raise HTTPException(
                status_code=400, detail=f"stream tidak ada: {missing}"
            )
    return seen


async def _stream_ids_of(db: AsyncSession, key_id: int) -> list[int]:
    res = await db.execute(
        select(ApiKeyStream.stream_id)
        .where(ApiKeyStream.api_key_id == key_id)
        .order_by(ApiKeyStream.position, ApiKeyStream.stream_id)
    )
    return list(res.scalars().all())


async def _set_key_streams(db: AsyncSession, key_id: int, stream_ids: list[int]) -> None:
    """Simpan cakupan kamera dengan urutan (position = indeks)."""
    stream_ids = await _validate_stream_ids(db, stream_ids)
    await db.execute(delete(ApiKeyStream).where(ApiKeyStream.api_key_id == key_id))
    for pos, sid in enumerate(stream_ids):
        db.add(ApiKeyStream(api_key_id=key_id, stream_id=sid, position=pos))


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
    stream_ids = await _validate_stream_ids(db, data.stream_ids)
    raw = secrets.token_urlsafe(32)
    key = ApiKey(
        name=data.name,
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        domain_lock=data.domain_lock,
        password_hash=hash_password(data.password) if data.password else None,
        # A-S1: simpan TTL sesi embed supaya benar-benar mengikuti setelan.
        session_ttl_mnt=data.session_limit_min,
        custom_camera_name=(data.custom_camera_name or "").strip(),
        include_playback=data.include_playback if data.include_playback is not None else True,
        show_ads=data.show_ads if data.show_ads is not None else True,
    )
    db.add(key)
    await db.flush()
    await _set_key_streams(db, key.id, stream_ids)
    await db.commit()
    await db.refresh(key)
    out = _key_to_out(key, stream_ids)
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
    if data.custom_camera_name is not None:
        key.custom_camera_name = data.custom_camera_name.strip()
    if data.include_playback is not None:
        key.include_playback = data.include_playback
    if data.show_ads is not None:
        key.show_ads = data.show_ads
    if data.session_limit_min is not None:
        # A-S1: simpan TTL sesi embed supaya benar-benar mengikuti setelan.
        key.session_ttl_mnt = data.session_limit_min
    if data.stream_ids is not None:
        await _set_key_streams(db, key_id, data.stream_ids)
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
        "action": log.action,
        "accessed_at": log.created_at.isoformat() if log.created_at else None,
    }


@router.get("/admin/api-access-logs")
async def list_logs(
    key_id: int | None = Query(default=None),
    action: str | None = Query(default=None),
    status: str | None = Query(default=None, description="hit|denied (v2.0)"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = select(ApiAccessLog).order_by(ApiAccessLog.id.desc())
    if key_id is not None:
        q = q.where(ApiAccessLog.api_key_id == key_id)
    if action:
        q = q.where(ApiAccessLog.action == action)
    if status == "denied":
        q = q.where(ApiAccessLog.action.like("%.denied%"))
    elif status in ("ok", "hit"):
        q = q.where(~ApiAccessLog.action.like("%.denied%"))
    q = q.limit(limit).offset(offset)
    res = await db.execute(q)
    return [_log_to_out(log) for log in res.scalars().all()]


@router.delete("/admin/api-access-logs")
async def clear_logs(
    days: int | None = Query(
        default=None, ge=1,
        description="v2.0: hapus log lebih lama dari N hari; kosong = hapus semua",
    ),
    db: AsyncSession = Depends(get_db),
):
    q = delete(ApiAccessLog)
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.where(ApiAccessLog.created_at < cutoff)
    await db.execute(q)
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
