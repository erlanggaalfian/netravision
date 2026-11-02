"""Router admin: pengguna & hak akses (MIGRATION-MAP §4)."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import can_manage_user, is_super_admin, require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.models.access import StreamAdminGrant, UserStreamAccess
from app.models.streams import Stream
from app.models.users import User

router = APIRouter()
admin_only = require_roles("admin")

VALID_ROLES = ("super_admin", "admin", "user", "guest")


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    show_ads: bool
    parent_admin_id: int | None = None
    dibuat_oleh: str | None = None


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"
    show_ads: bool = True


class UserUpdate(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None
    show_ads: bool | None = None


class StreamIdsIn(BaseModel):
    stream_ids: list[int]


async def _out(u: User, db: AsyncSession) -> UserOut:
    dibuat_oleh: str | None = None
    if u.parent_admin_id:
        pembuat = (
            (await db.execute(select(User).where(User.id == u.parent_admin_id)))
            .scalars()
            .first()
        )
        dibuat_oleh = pembuat.username if pembuat else None
    return UserOut(
        id=u.id,
        username=u.username,
        role=u.role,
        is_active=u.is_active,
        show_ads=u.show_ads,
        parent_admin_id=u.parent_admin_id,
        dibuat_oleh=dibuat_oleh,
    )


async def _get_user_or_404(user_id: int, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user tidak ditemukan")
    return user


@router.get("/admin/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db), me: User = Depends(admin_only)
):
    """Daftar user. Admin biasa hanya melihat dirinya + akun buatannya;
    super_admin melihat semua (paritas v2.0: bawahan_saya)."""
    q = select(User).order_by(User.username)
    if not is_super_admin(me):
        q = q.where(
            (User.id == me.id) | (User.parent_admin_id == me.id)
        )
    result = await db.execute(q)
    users = result.scalars().all()
    return [await _out(u, db) for u in users]


@router.post("/admin/users", response_model=UserOut, status_code=201)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(admin_only),
):
    if data.role not in VALID_ROLES:
        raise HTTPException(400, "role tidak valid")
    if data.role == "super_admin" and not is_super_admin(me):
        # v2.0: admin tidak bisa membuat super_admin.
        raise HTTPException(403, "hanya super_admin yang bisa membuat super_admin")
    exists = await db.execute(
        select(User.id).where(User.username == data.username)
    )
    if exists.scalars().first() is not None:
        raise HTTPException(409, "username sudah dipakai")
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        role=data.role,
        show_ads=data.show_ads,
        parent_admin_id=me.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await _out(user, db)


@router.put("/admin/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(admin_only),
):
    user = await _get_user_or_404(user_id, db)
    if not can_manage_user(me, user):
        raise HTTPException(403, "tidak boleh mengelola akun ini")
    if data.username is not None and data.username != user.username:
        dupe = await db.execute(
            select(User.id).where(
                User.username == data.username, User.id != user.id
            )
        )
        if dupe.scalars().first() is not None:
            raise HTTPException(409, "username sudah dipakai")
        user.username = data.username
    if data.password:
        user.password_hash = hash_password(data.password)
    if data.role is not None:
        if data.role not in VALID_ROLES:
            raise HTTPException(400, "role tidak valid")
        if data.role == "super_admin" and not is_super_admin(me):
            raise HTTPException(403, "hanya super_admin yang bisa memberi peran super_admin")
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.show_ads is not None:
        user.show_ads = data.show_ads
    await db.commit()
    await db.refresh(user)
    return await _out(user, db)


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(admin_only),
):
    if user_id == me.id:
        raise HTTPException(400, "tidak bisa menghapus akun sendiri")
    user = await _get_user_or_404(user_id, db)
    if not can_manage_user(me, user):
        raise HTTPException(403, "tidak boleh menghapus akun ini")
    await db.delete(user)
    await db.commit()
    return {"ok": True}


@router.get("/admin/users/{user_id}/camera-access")
async def get_camera_access(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
):
    await _get_user_or_404(user_id, db)
    result = await db.execute(
        select(UserStreamAccess.stream_id).where(
            UserStreamAccess.user_id == user_id,
            UserStreamAccess.can_view.is_(True),
        )
    )
    return {"user_id": user_id, "stream_ids": list(result.scalars().all())}


@router.post("/admin/users/{user_id}/camera-access")
async def set_camera_access(
    user_id: int,
    data: StreamIdsIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
):
    """Ganti daftar kamera yang boleh dilihat user (v2.0: camera-access)."""
    await _get_user_or_404(user_id, db)
    await db.execute(
        delete(UserStreamAccess).where(UserStreamAccess.user_id == user_id)
    )
    for sid in data.stream_ids:
        db.add(UserStreamAccess(user_id=user_id, stream_id=sid, can_view=True))
    await db.commit()
    return {"ok": True, "stream_ids": data.stream_ids}


@router.post("/admin/users/{user_id}/access")
async def set_access_legacy(
    user_id: int,
    data: StreamIdsIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(admin_only),
):
    """Alias kompatibilitas v2.0 untuk /camera-access."""
    return await set_camera_access(user_id, data, db, me)


@router.get("/admin/admins/{admin_id}/camera-grants")
async def get_admin_grants(
    admin_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(admin_only),
):
    await _get_user_or_404(admin_id, db)
    result = await db.execute(
        select(StreamAdminGrant.stream_id).where(
            StreamAdminGrant.admin_id == admin_id,
            StreamAdminGrant.can_manage.is_(True),
        )
    )
    return {"admin_id": admin_id, "stream_ids": list(result.scalars().all())}


@router.post("/admin/admins/{admin_id}/camera-grants")
async def set_admin_grants(
    admin_id: int,
    data: StreamIdsIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(admin_only),
):
    await _get_user_or_404(admin_id, db)
    await db.execute(
        delete(StreamAdminGrant).where(StreamAdminGrant.admin_id == admin_id)
    )
    for sid in data.stream_ids:
        db.add(
            StreamAdminGrant(
                admin_id=admin_id, stream_id=sid, can_manage=True,
                granted_by=me.id,
            )
        )
    await db.commit()
    return {"ok": True, "stream_ids": data.stream_ids}


@router.get("/admin/access-overview")
async def access_overview(
    db: AsyncSession = Depends(get_db), _: User = Depends(admin_only)
):
    """Ringkasan: jumlah user per role + grant per stream."""
    roles = await db.execute(
        select(User.role, func.count(User.id)).group_by(User.role)
    )
    grants = await db.execute(
        select(
            UserStreamAccess.stream_id, func.count(UserStreamAccess.user_id)
        ).group_by(UserStreamAccess.stream_id)
    )
    streams = await db.execute(
        select(Stream.id, Stream.name).where(Stream.is_active.is_(True))
    )
    names = {sid: name for sid, name in streams.all()}
    return {
        "roles": {role: count for role, count in roles.all()},
        "grants": [
            {
                "stream_id": sid,
                "stream_name": names.get(sid),
                "users": count,
            }
            for sid, count in grants.all()
        ],
    }
