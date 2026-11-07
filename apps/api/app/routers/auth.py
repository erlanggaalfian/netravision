"""Auth: login, refresh (rotation), logout, guest.

Path dipertahankan persis seperti v2.0: POST /api/auth/login|refresh|logout|guest.
"""

import hmac

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.core.rbac import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.session import get_db
from app.models.users import User
from app.schemas.auth import GuestIn, LoginIn, RefreshIn, TokenOut

router = APIRouter(tags=["auth"])


async def _get_active_user(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(
        select(User).where(User.username == username, User.is_active.is_(True))
    )
    return result.scalars().first()


def _token_pair(user: User) -> TokenOut:
    settings = get_settings()
    access = create_access_token(user.id, user.username, user.role, settings)
    refresh, _jti = create_refresh_token(user.id, settings)
    user.refresh_token_hash = hash_token(refresh)
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_minutes * 60,
    )


@router.post(
    "/auth/login",
    response_model=TokenOut,
    dependencies=[Depends(rate_limited(5, 60))],
)
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = await _get_active_user(db, data.username)
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="username/password salah"
        )
    pair = _token_pair(user)
    await db.commit()
    return pair


@router.post(
    "/auth/refresh",
    response_model=TokenOut,
    dependencies=[Depends(rate_limited(20, 60))],
)
async def refresh(data: RefreshIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    settings = get_settings()
    try:
        payload = decode_token(data.refresh_token, settings)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token salah tipe")

    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalars().first()
    if (
        user is None
        or not user.is_active
        or user.refresh_token_hash is None
        or not hmac.compare_digest(user.refresh_token_hash, hash_token(data.refresh_token))
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh ditolak")

    # Rotation: token lama hangus, terbit pasangan baru.
    pair = _token_pair(user)
    await db.commit()
    return pair


@router.post("/auth/logout")
async def logout(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    if user.id:  # guest ephemeral tidak punya baris DB
        result = await db.execute(select(User).where(User.id == user.id))
        db_user = result.scalars().first()
        if db_user is not None:
            db_user.refresh_token_hash = None
            await db.commit()
    return {"ok": True}


@router.get("/auth/guest-enabled")
async def guest_enabled(db: AsyncSession = Depends(get_db)) -> dict:
    """Apakah login guest sedang aktif (dipakai halaman login untuk
    menampilkan atau menyembunyikan tombol Guest)."""
    return {"enabled": await _guest_login_enabled(db)}


async def _guest_login_enabled(db: AsyncSession) -> bool:
    """Login guest aktif bila baris guest di DB aktif.

    Bila baris guest belum ada (DB lama sebelum migrasi 0011),
    pakai env GUEST_ENABLED sebagai cadangan.
    """
    result = await db.execute(select(User).where(User.username == "guest"))
    row = result.scalars().first()
    if row is not None:
        return bool(row.is_active)
    return get_settings().guest_enabled


@router.post(
    "/auth/guest",
    response_model=TokenOut,
    dependencies=[Depends(rate_limited(5, 60))],
)
async def guest(data: GuestIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    """Login tamu untuk semua pengunjung — tanpa password, tanpa
    autentikasi apapun (2026-11-06). Nonaktif bila baris guest di DB
    is_active False (diatur superadmin lewat web); bila baris belum
    ada, nonaktif bila GUEST_ENABLED false."""
    if not await _guest_login_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="login tamu nonaktif"
        )
    settings = get_settings()
    access = create_access_token("guest", "guest", "guest", settings, expires_minutes=60)
    return TokenOut(access_token=access, refresh_token=None, expires_in=3600)


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    """Profil user dari token saat ini (dipakai web saat boot)."""
    return {"id": user.id, "username": user.username, "role": user.role}


# Helper internal (dipakai skrip seed Fase 1, bukan endpoint publik).
def _make_password_hash(password: str) -> str:  # pragma: no cover
    return hash_password(password)
