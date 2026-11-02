"""Router admin: akun Google Drive multi-akun.

Kamera memilih akun via streams.drive_account_id (NULL = akun default).
OAuth memakai SATU redirect_uri untuk semua akun:
  {public_base}/api/admin/drive-accounts/oauth/callback
Token OAuth tiap akun disimpan terenkripsi (Fernet) di DB.
"""

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rbac import get_current_user, require_roles
from app.db.session import get_db
from app.models.drive import DriveAccount, GoogleDriveFolder
from app.models.streams import Stream
from app.models.users import User
from app.services.drive_accounts import clear_drive_client_cache

log = logging.getLogger("netravision.admin_drive")

router = APIRouter(tags=["admin-drive"])  # callback OAuth: publik (dipanggil Google)
admin_router = APIRouter(
    tags=["admin-drive"], dependencies=[Depends(require_roles("admin"))]
)

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_SCOPE = "https://www.googleapis.com/auth/drive.file"
_STATE_TTL = 600  # state OAuth berlaku 10 menit


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_default: bool | None = None


def _sign_state(account_id: str) -> str:
    """State OAuth bertanda-tangan: {account_id}.{exp}.{hmac}."""
    exp = int(time.time()) + _STATE_TTL
    payload = f"{account_id}.{exp}"
    sig = hmac.new(
        get_settings().jwt_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{sig}"


def _verify_state(state: str) -> str:
    """Return account_id bila state valid; raise ValueError bila tidak."""
    try:
        account_id, exp, sig = state.split(".")
        int(exp)
    except (ValueError, AttributeError):
        raise ValueError("format state salah")
    payload = f"{account_id}.{exp}"
    want = hmac.new(
        get_settings().jwt_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, want):
        raise ValueError("tanda tangan state tidak cocok")
    if int(exp) < time.time():
        raise ValueError("state kedaluwarsa")
    return account_id


def _client_credentials(settings) -> tuple[str, str]:
    """Baca client_id/secret dari credentials.json (bentuk installed/web)."""
    try:
        with open(settings.drive_credentials_file) as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise RuntimeError(
            f"credentials Drive tidak terbaca ({settings.drive_credentials_file}) — "
            "lihat docs/GOOGLE-DRIVE.md §1"
        ) from e
    node = data.get("web") or data.get("installed") or {}
    cid, csec = node.get("client_id"), node.get("client_secret")
    if not cid or not csec:
        raise RuntimeError("credentials.json tidak memuat client_id/client_secret")
    return cid, csec


def _redirect_uri(settings) -> str:
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError(
            "PUBLIC_BASE_URL / public_base_url wajib diset untuk OAuth Drive"
        )
    return f"{base}/api/admin/drive-accounts/oauth/callback"


def _oauth_url(account_id: str, settings) -> str:
    cid, _ = _client_credentials(settings)
    q = urlencode({
        "client_id": cid,
        "redirect_uri": _redirect_uri(settings),
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": _sign_state(account_id),
    })
    return f"{_GOOGLE_AUTH_URL}?{q}"


async def _exchange_code(code: str, settings) -> dict:
    """Tukar authorization code -> token OAuth (dipakai callback)."""
    cid, csec = _client_credentials(settings)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(_GOOGLE_TOKEN_URL, data={
            "code": code, "client_id": cid, "client_secret": csec,
            "redirect_uri": _redirect_uri(settings), "grant_type": "authorization_code",
        })
        r.raise_for_status()
        return r.json()


def _account_out(acc: DriveAccount, camera_count: int) -> dict:
    return {
        "id": str(acc.id),
        "name": acc.name,
        "is_default": acc.is_default,
        "connected": acc.connected,
        "status": acc.status,
        "last_error": acc.last_error,
        "camera_count": camera_count,
        "created_at": acc.created_at.isoformat() if acc.created_at else None,
    }


async def _camera_counts(db: AsyncSession) -> dict:
    rows = (await db.execute(
        select(Stream.drive_account_id, func.count())
        .where(Stream.drive_account_id.is_not(None))
        .group_by(Stream.drive_account_id)
    )).all()
    return {str(a): c for a, c in rows}


async def _get_or_404(db: AsyncSession, account_id: uuid.UUID) -> DriveAccount:
    acc = await db.get(DriveAccount, account_id)
    if acc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "akun Drive tidak ditemukan")
    return acc


@admin_router.get("/admin/drive-accounts")
async def list_accounts(db: AsyncSession = Depends(get_db)):
    accs = (await db.execute(select(DriveAccount).order_by(DriveAccount.name))).scalars().all()
    counts = await _camera_counts(db)
    return [_account_out(a, counts.get(str(a.id), 0)) for a in accs]


@admin_router.post("/admin/drive-accounts", status_code=status.HTTP_201_CREATED)
async def create_account(data: AccountCreate, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    exists = (await db.execute(
        select(DriveAccount).where(DriveAccount.name == data.name)
    )).scalars().first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "nama akun sudah dipakai")
    # Validasi dini: credentials + public_base harus benar sebelum user OAuth.
    _client_credentials(settings)
    _redirect_uri(settings)
    acc = DriveAccount(name=data.name)
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    return {"id": str(acc.id), "name": acc.name, "oauth_url": _oauth_url(str(acc.id), settings)}


@admin_router.put("/admin/drive-accounts/{account_id}")
async def update_account(
    account_id: uuid.UUID, data: AccountUpdate, db: AsyncSession = Depends(get_db)
):
    acc = await _get_or_404(db, account_id)
    if data.name is not None:
        dup = (await db.execute(select(DriveAccount).where(
            DriveAccount.name == data.name, DriveAccount.id != acc.id
        ))).scalars().first()
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "nama akun sudah dipakai")
        acc.name = data.name
    if data.is_default is True:
        await db.execute(
            update(DriveAccount).where(DriveAccount.id != acc.id).values(is_default=False)
        )
        acc.is_default = True
    elif data.is_default is False:
        acc.is_default = False
    await db.commit()
    await db.refresh(acc)
    counts = await _camera_counts(db)
    return _account_out(acc, counts.get(str(acc.id), 0))


@admin_router.post("/admin/drive-accounts/{account_id}/reauth")
async def reauth_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    acc = await _get_or_404(db, account_id)
    return {"oauth_url": _oauth_url(str(acc.id), get_settings())}


@admin_router.delete("/admin/drive-accounts/{account_id}")
async def delete_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    acc = await _get_or_404(db, account_id)
    n = (await db.execute(select(func.count()).where(
        Stream.drive_account_id == acc.id
    ))).scalar() or 0
    if n:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": f"akun masih dipakai {n} kamera", "camera_count": n},
        )
    # Revoke token ke Google (best-effort; hapus DB apa pun hasilnya).
    if acc.token_encrypted:
        try:
            from app.core.drive_tokens import decrypt_token

            tok = decrypt_token(acc.token_encrypted)
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(_GOOGLE_REVOKE_URL, data={
                    "token": tok.get("refresh_token") or tok.get("access_token", "")
                })
        except Exception as e:  # noqa: BLE001
            log.warning("revoke token akun %s gagal: %s", acc.id, e)
    clear_drive_client_cache(acc.id)
    await db.delete(acc)
    await db.commit()
    return {"ok": True}


@router.get("/admin/drive-accounts/oauth/callback", include_in_schema=False)
async def oauth_callback(
    code: str, state: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Dipanggil browser user setelah consent Google (TANPA auth — state HMAC)."""
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/") or str(request.base_url).rstrip("/")
    try:
        account_id = _verify_state(state)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "state OAuth tidak valid")
    acc = await _get_or_404(db, uuid.UUID(account_id))
    try:
        token = await _exchange_code(code, settings)
        if "refresh_token" not in token:
            log.warning("OAuth akun %s tanpa refresh_token — consent mungkin diulang", acc.id)
        from app.core.drive_tokens import encrypt_token

        acc.token_encrypted = encrypt_token(token)
        acc.status = "connected"
        acc.last_error = None
        await db.commit()
        clear_drive_client_cache(acc.id)
        return RedirectResponse(f"{base}/admin/drive/?connected=1", status_code=302)
    except Exception as e:  # noqa: BLE001
        acc.status = "error"
        acc.last_error = str(e)[:500]
        await db.commit()
        log.warning("OAuth callback akun %s gagal: %s", acc.id, e)
        return RedirectResponse(f"{base}/admin/drive/?connected=0", status_code=302)


# ---------------------------------------------------------------------------
# Mode folder-link + rclone (ala fieriindra/CCTV-Monitoring).
# Implementasi TAMBAHAN yang lebih sederhana di samping OAuth multi-akun:
# tujuan Drive cukup diganti dengan menempel tautan folder baru.
# ---------------------------------------------------------------------------


class GoogleDriveFolderIn(BaseModel):
    folder_url: str
    folder_name: str = ""
    local_path: str = ""


def parse_gdrive_folder_id(url: str) -> str:
    """Ambil ID folder dari tautan Google Drive (berbagai bentuk URL)."""
    text = (url or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", text)
    return m.group(1) if m else ""


def _gdrive_folder_dict(row) -> dict:
    settings = get_settings()
    return {
        "id": row.id,
        "folder_url": row.folder_url,
        "folder_id": row.folder_id,
        "folder_name": row.folder_name,
        "local_path": row.local_path or settings.gdrive_record_path,
        "local_path_custom": bool(row.local_path),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by or "",
    }


@admin_router.get("/admin/storage/google-drive")
async def list_gdrive_folders(db: AsyncSession = Depends(get_db)):
    """Daftar tautan folder Google Drive (bisa banyak)."""
    res = await db.execute(select(GoogleDriveFolder).order_by(GoogleDriveFolder.id))
    rows = res.scalars().all()
    settings = get_settings()
    return {
        "folders": [_gdrive_folder_dict(r) for r in rows],
        "staging_default": settings.gdrive_record_path,
        "quota_tb": settings.gdrive_quota_tb,
    }


@admin_router.post("/admin/storage/google-drive", status_code=201)
async def add_gdrive_folder(
    payload: GoogleDriveFolderIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """Tambah satu tautan folder Google Drive.

    Bila koneksi rclone Drive aktif, akses folder diverifikasi dulu —
    gagal = 400 dengan pesan jelas.
    """
    folder_id = parse_gdrive_folder_id(payload.folder_url)
    if not folder_id:
        raise HTTPException(
            status_code=400,
            detail="Tautan folder Google Drive tidak dikenali. Tempel tautan folder, "
            "mis. https://drive.google.com/drive/folders/<ID>",
        )
    folder_name = (payload.folder_name or "").strip()
    # Verifikasi via rclone bila terhubung
    from app.services import gdrive_rclone as gr

    try:
        st = await gr.connection_status()
    except Exception:  # noqa: BLE001
        st = {"connected": False}
    if st.get("connected"):
        try:
            info = await gr.check_folder_access(folder_id)
            if not folder_name:
                folder_name = info.get("name", "")
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    row = GoogleDriveFolder(
        folder_url=payload.folder_url.strip(),
        folder_id=folder_id,
        folder_name=folder_name,
        local_path=(payload.local_path or "").strip(),
        updated_at=datetime.now(timezone.utc),
        updated_by=admin.username,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _gdrive_folder_dict(row)


@admin_router.put("/admin/storage/google-drive/{folder_id}")
async def update_gdrive_folder(
    folder_id: int,
    payload: GoogleDriveFolderIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """Ubah satu tautan folder Google Drive."""
    row = await db.get(GoogleDriveFolder, folder_id)
    if row is None:
        raise HTTPException(status_code=404, detail="folder tidak ditemukan")
    fid = parse_gdrive_folder_id(payload.folder_url)
    if not fid:
        raise HTTPException(
            status_code=400,
            detail="Tautan folder Google Drive tidak dikenali.",
        )
    row.folder_url = payload.folder_url.strip()
    row.folder_id = fid
    row.folder_name = (payload.folder_name or "").strip()
    row.local_path = (payload.local_path or "").strip()
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = admin.username
    await db.commit()
    return _gdrive_folder_dict(row)


@admin_router.delete("/admin/storage/google-drive/{folder_id}")
async def delete_gdrive_folder(folder_id: int, db: AsyncSession = Depends(get_db)):
    """Hapus satu tautan folder. Kamera yang menunjuk ke sini jadi default."""
    row = await db.get(GoogleDriveFolder, folder_id)
    if row is None:
        raise HTTPException(status_code=404, detail="folder tidak ditemukan")
    await db.execute(
        update(Stream).where(Stream.drive_folder_id == folder_id).values(drive_folder_id=None)
    )
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Koneksi Google Drive via rclone (tombol "Hubungkan" di aplikasi)
# ---------------------------------------------------------------------------

class RcloneTokenIn(BaseModel):
    token: str


@admin_router.get("/admin/storage/google-drive/connection")
async def gdrive_connection_status():
    """Status koneksi rclone Drive: {connected, email, rclone_found}."""
    from app.services import gdrive_rclone as gr

    st = await gr.connection_status()
    st["rclone_found"] = bool(gr.find_rclone())
    return st


@admin_router.post("/admin/storage/google-drive/connect", status_code=201)
async def gdrive_connect(payload: RcloneTokenIn):
    """Simpan token dari `rclone authorize "drive"` + verifikasi ke Google.

    Token ditempel user dari aplikasi (tombol Hubungkan) — tanpa SSH,
    tanpa Cloud Console.
    """
    from app.services import gdrive_rclone as gr

    try:
        info = await gr.save_token(payload.token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, **info}


@admin_router.delete("/admin/storage/google-drive/connection")
async def gdrive_disconnect():
    """Putuskan koneksi Drive (hapus token rclone)."""
    from app.services import gdrive_rclone as gr

    await gr.disconnect()
    return {"ok": True}
