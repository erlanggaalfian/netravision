"""RBAC: dependency FastAPI untuk autentikasi + otorisasi.

Peran: super_admin | admin | user | guest (paritas v2.0).
super_admin adalah kuasa penuh (KUASA_PENUH v2.0): lolos semua gerbang peran.
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.access import StreamAdminGrant, StreamPermission, UserStreamAccess
from app.models.streams import Stream
from app.models.users import User

bearer_scheme = HTTPBearer(auto_error=False)


def _sub_to_int(payload: dict) -> int:
    """Ubah klaim sub menjadi id user; 401 bila hilang atau bukan angka.

    Token sesi embed yang sah punya sub "key:N" dan token tanpa sub
    sebelumnya melempar ValueError/KeyError menjadi 500 (A-T5).
    """
    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token tanpa sub"
        )
    try:
        return int(sub)
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token tidak valid"
        ) from e


async def _user_from_token(raw: str, db: AsyncSession) -> User:
    try:
        payload = decode_token(raw, get_settings())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token salah tipe")

    # Guest: pakai baris user 'guest' dari DB bila ada (migrasi 0011),
    # agar show_ads-nya bisa diatur superadmin di menu Pengguna.
    # Bila baris ada tapi nonaktif, token guest lama ditolak (401):
    # menonaktifkan guest harus langsung mematikan sesi guest yang
    # sudah berjalan. Fallback ke user sintetis hanya bila baris
    # belum ada sama sekali (DB lama).
    if payload.get("sub") == "guest":
        result = await db.execute(select(User).where(User.username == "guest"))
        guest = result.scalars().first()
        if guest is not None:
            if not guest.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="login tamu nonaktif",
                )
            return guest
        return User(id=0, username="guest", password_hash="", role="guest",
                    is_active=True, show_ads=True)

    result = await db.execute(
        select(User).where(User.id == _sub_to_int(payload), User.is_active.is_(True))
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user tidak ada")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="butuh login")
    return await _user_from_token(credentials.credentials, db)


async def get_current_user_flexible(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Terima token via header Authorization ATAU query ?token=.

    Diperlukan untuk <img src> (poster kamera) yang tidak bisa mengirim header.
    """
    raw = credentials.credentials if credentials else token
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="butuh login")
    return await _user_from_token(raw, db)


def is_super_admin(user: User) -> bool:
    """Benar bila pengguna memegang kuasa penuh (paritas v2.0: KUASA_PENUH)."""
    return (getattr(user, "role", "") or "") == "super_admin"


async def require_super_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency: hentikan siapa pun selain super_admin (v2.0: tolak_bukan_super)."""
    if not is_super_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="hanya super_admin",
        )
    return user


def can_manage_user(actor: User, target: User) -> bool:
    """Apakah actor boleh mengelola (lihat/ubah/hapus) akun target?

    Paritas v2.0 (bawahan_saya): super_admin membawahi semua; admin biasa
    hanya mengelola akun yang ia buat (parent_admin_id) dan dirinya sendiri;
    sesama admin / super_admin tidak boleh dikelola admin biasa.
    """
    if is_super_admin(actor):
        return True
    if (getattr(actor, "role", "") or "") != "admin":
        return False
    if target.id == actor.id:
        return True
    if (getattr(target, "role", "") or "") in ("admin", "super_admin"):
        return False
    return (getattr(target, "parent_admin_id", None) or 0) == actor.id


async def mask_rtsp_url(stream, user: User, db: AsyncSession) -> str:
    """Kembalikan rtsp_url kamera bila user berhak melihatnya, atau "" bila tidak.

    Paritas v2.0 (saring_rtsp/boleh_lihat_rtsp): super_admin melihat semua;
    admin hanya melihat kamera yang ia pasang sendiri (created_by, jatuh ke
    owner_id bila belum tercatat) atau yang ia terima via grant can_view.
    """
    raw = getattr(stream, "rtsp_url", "") or ""
    if is_super_admin(user):
        return raw
    if (getattr(user, "role", "") or "") != "admin":
        return ""
    created_by = getattr(stream, "created_by", None)
    if created_by is None:
        created_by = getattr(stream, "owner_id", None)
    if created_by is not None and created_by == user.id:
        return raw
    grant = (
        (
            await db.execute(
                select(StreamAdminGrant).where(
                    StreamAdminGrant.stream_id == stream.id,
                    StreamAdminGrant.admin_id == user.id,
                    StreamAdminGrant.can_view.is_(True),
                )
            )
        )
        .scalars()
        .first()
    )
    return raw if grant is not None else ""


def require_roles(*roles: str) -> Callable:
    """Dependency factory: tolak bila role user tidak termasuk daftar.

    super_admin lolos semua gerbang peran (kuasa penuh, paritas v2.0).
    """

    async def checker(user: User = Depends(get_current_user)) -> User:
        if not is_super_admin(user) and user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="akses ditolak")
        return user

    return checker


def require_camera_playback_access() -> Callable:
    """Dependency factory: akses kamera + wajib izin playback (untuk endpoint rekaman).

    Paritas v2.0 (boleh_playback): izin membuka rekaman dipisah dari izin
    menonton live. Catatan: app/routers/recordings.py belum memakai ini
    (di luar cakupan file ini) — lihat app/models/_rbac_patch_notes.md.
    """

    async def checker(
        stream_id: int,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        return await _check_camera_access(stream_id, user, db, need_playback=True)

    return checker


async def require_camera_access(
    stream_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Izinkan bila: super_admin, admin pemilik/grant, atau punya grant eksplisit,
    atau grant berbasis peran (user_id NULL)."""
    return await _check_camera_access(stream_id, user, db)


async def require_camera_access_token_qp(
    stream_id: int,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Varian require_camera_access yang menerima token via ?token= (untuk <img>)."""
    return await _check_camera_access(stream_id, user, db)


async def require_reshare(
    me: User, db: AsyncSession, stream_id: int, need_playback: bool
) -> None:
    """Admin yang membagikan kamera ke bawahannya wajib punya grant
    can_reshare (+ can_view; can_playback bila yang dibagikan mencakup
    rekaman). Super_admin bebas (paritas v2.0: can_reshare)."""
    if is_super_admin(me):
        return
    grant = (
        (
            await db.execute(
                select(StreamAdminGrant).where(
                    StreamAdminGrant.stream_id == stream_id,
                    StreamAdminGrant.admin_id == me.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if grant is None or not grant.can_view or not grant.can_reshare:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tidak punya izin membagikan kamera ini",
        )
    if need_playback and not grant.can_playback:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tidak punya izin membagikan rekaman kamera ini",
        )


async def _check_camera_access(
    stream_id: int, user: User, db: AsyncSession, need_playback: bool = False
) -> User:
    """Cek akses kamera; need_playback=True mewajibkan izin rekaman terpisah.

    Paritas v2.0 (boleh_tonton vs boleh_playback): seseorang dapat diberi
    siaran langsung tanpa riwayat rekamannya. need_playback=False
    mempertahankan perilaku lama.
    """
    if is_super_admin(user):
        return user

    stream_ada = (
        (await db.execute(select(Stream).where(Stream.id == stream_id)))
        .scalars()
        .first()
    )
    if stream_ada is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="kamera tidak ditemukan"
        )

    if user.role == "admin":
        # A-T2 (perubahan perilaku, paling restriktif): admin biasa
        # hanya boleh mengakses kamera miliknya sendiri (dipasang atau
        # dimiliki) atau yang di-grant kepadanya. can_view untuk Live,
        # can_playback untuk playback. Perilaku lama yang membiarkan
        # admin melihat semua kamera sudah tidak berlaku.
        pemasang = getattr(stream_ada, "created_by", None) or getattr(
            stream_ada, "owner_id", None
        )
        if pemasang == user.id:
            return user
        grant = (
            (
                await db.execute(
                    select(StreamAdminGrant).where(
                        StreamAdminGrant.stream_id == stream_id,
                        StreamAdminGrant.admin_id == user.id,
                        (
                            StreamAdminGrant.can_playback.is_(True)
                            if need_playback
                            else StreamAdminGrant.can_view.is_(True)
                        ),
                    )
                )
            )
            .scalars()
            .first()
        )
        if grant is not None:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "tidak punya izin membuka rekaman kamera ini"
                if need_playback
                else "tidak punya akses ke kamera ini"
            ),
        )

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
        if need_playback and not grant.can_playback:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="tidak punya izin membuka rekaman kamera ini",
            )
        return user

    role_perm = (
        (
            await db.execute(
                select(StreamPermission).where(
                    StreamPermission.stream_id == stream_id,
                    StreamPermission.role == user.role,
                    # A-R4: hanya baris berbasis peran (user_id NULL);
                    # baris yang ditujukan ke user tertentu tidak boleh
                    # memberi akses ke semua user dengan peran itu.
                    StreamPermission.user_id.is_(None),
                    StreamPermission.can_view.is_(True),
                )
            )
        )
        .scalars()
        .first()
    )
    if role_perm is not None:
        if need_playback and not role_perm.can_playback:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="tidak punya izin membuka rekaman kamera ini",
            )
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="tidak punya akses ke kamera ini"
    )
