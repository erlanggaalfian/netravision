"""RBAC: dependency FastAPI untuk autentikasi + otorisasi.

Peran: admin | user | guest (dipertahankan dari v2.0).
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.access import StreamPermission, UserStreamAccess
from app.models.users import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="butuh login")
    try:
        payload = decode_token(credentials.credentials, get_settings())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token salah tipe")

    # Guest v2.0 bersifat ephemeral — tanpa baris user di DB.
    if payload.get("sub") == "guest":
        return User(id=0, username="guest", password_hash="", role="guest", is_active=True)

    result = await db.execute(
        select(User).where(User.id == int(payload["sub"]), User.is_active.is_(True))
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user tidak ada")
    return user


def require_roles(*roles: str) -> Callable:
    """Dependency factory: tolak bila role user tidak termasuk daftar."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="akses ditolak")
        return user

    return checker


async def require_camera_access(
    stream_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Izinkan bila: admin, atau punya grant eksplisit, atau grant berbasis peran."""
    if user.role == "admin":
        return user

    grant = (
        (
            await db.execute(
                select(UserStreamAccess).where(
                    UserStreamAccess.user_id == user.id,
                    UserStreamAccess.stream_id == stream_id,
                    UserStreamAccess.can_view.is_(True),
                )
            )
        )
        .scalars()
        .first()
    )
    if grant is not None:
        return user

    role_perm = (
        (
            await db.execute(
                select(StreamPermission).where(
                    StreamPermission.stream_id == stream_id,
                    StreamPermission.role == user.role,
                    StreamPermission.can_view.is_(True),
                )
            )
        )
        .scalars()
        .first()
    )
    if role_perm is not None:
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="tidak punya akses ke kamera ini"
    )
