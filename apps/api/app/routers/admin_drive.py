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
import os
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rbac import get_current_user, require_roles
from app.db.session import get_db
from app.models.drive import DriveAccount, DriveUpload, GoogleDriveFolder, RcloneRemote
from app.models.streams import Stream
from app.models.users import User
from app.services.drive_accounts import clear_drive_client_cache

log = logging.getLogger("netravision.admin_drive")

router = APIRouter(tags=["admin-drive"])  # callback OAuth: publik (dipanggil Google)
admin_router = APIRouter(
    # E-K1 (backend): Penyimpanan/Drive hanya super_admin, bukan admin biasa.
    tags=["admin-drive"], dependencies=[Depends(require_roles("super_admin"))]
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
            f"credentials Drive tidak terbaca ({settings.drive_credentials_file}), "
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


def _config_exc(e: RuntimeError) -> HTTPException:
    """A-S12: RuntimeError konfigurasi Drive -> HTTPException yang bisa
    ditindaklanjuti (bukan 500). PUBLIC_BASE_URL kosong adalah masalah
    konfigurasi server (503); credentials tidak terbaca adalah setup yang
    belum lengkap (400)."""
    msg = str(e)
    if "PUBLIC_BASE_URL" in msg:
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, msg)
    return HTTPException(status.HTTP_400_BAD_REQUEST, msg)


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
    try:
        _client_credentials(settings)
        _redirect_uri(settings)
    except RuntimeError as e:
        raise _config_exc(e) from e
    # B-S7: akun pertama otomatis menjadi default, supaya resolve_drive_account
    # tidak mengembalikan None dan Drive tidak diam-diam nonaktif.
    n_accounts = (await db.execute(
        select(func.count()).select_from(DriveAccount)
    )).scalar() or 0
    acc = DriveAccount(name=data.name, is_default=(n_accounts == 0))
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    try:
        oauth_url = _oauth_url(str(acc.id), settings)
    except RuntimeError as e:
        raise _config_exc(e) from e
    return {
        "id": str(acc.id),
        "name": acc.name,
        "is_default": acc.is_default,
        "oauth_url": oauth_url,
    }


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
    try:
        return {"oauth_url": _oauth_url(str(acc.id), get_settings())}
    except RuntimeError as e:
        raise _config_exc(e) from e


@admin_router.delete("/admin/drive-accounts/{account_id}")
async def delete_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    acc = await _get_or_404(db, account_id)
    n = (await db.execute(select(func.count()).where(
        Stream.drive_account_id == acc.id
    ))).scalar() or 0
    if n:
        # A-R2: detail harus string seperti endpoint lain (jumlah kamera
        # sudah tercantum di pesan), bukan dict.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"akun masih dipakai {n} kamera",
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
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Dipanggil browser user setelah consent Google (TANPA auth, state HMAC).

    A-R2: Google bisa memanggil balik dengan ?error=access_denied (tanpa
    code/state); itu harus dijawab redirect connected=0, bukan 422 karena
    code/state wajib.
    """
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/") or str(request.base_url).rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{base}/admin/drive/?connected=0", status_code=302)
    try:
        account_id = _verify_state(state)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "state OAuth tidak valid")
    acc = await _get_or_404(db, uuid.UUID(account_id))
    try:
        token = await _exchange_code(code, settings)
        if "refresh_token" not in token:
            log.warning("OAuth akun %s tanpa refresh_token, consent mungkin diulang", acc.id)
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
    # Retensi per folder (hari); None = tidak ada hapus otomatis.
    retention_days: int | None = Field(default=None, ge=1)


def parse_gdrive_folder_id(url: str) -> str:
    """Ambil ID folder dari tautan Google Drive (berbagai bentuk URL)."""
    text = (url or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", text)
    return m.group(1) if m else ""


def _gdrive_folder_dict(row, remote_label: str | None = None) -> dict:
    settings = get_settings()
    return {
        "id": row.id,
        "folder_url": row.folder_url,
        "folder_id": row.folder_id,
        "folder_name": row.folder_name,
        "local_path": row.local_path or settings.gdrive_record_path,
        "local_path_custom": bool(row.local_path),
        "retention_days": row.retention_days,
        "remote_name": row.remote_name or "",
        "remote_label": remote_label or "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by or "",
    }


@admin_router.get("/admin/storage/google-drive")
async def list_gdrive_folders(db: AsyncSession = Depends(get_db)):
    """Daftar tautan folder Google Drive (bisa banyak)."""
    res = await db.execute(select(GoogleDriveFolder).order_by(GoogleDriveFolder.id))
    rows = res.scalars().all()
    settings = get_settings()
    # Label akun tiap remote, supaya pemilih folder bisa menampilkan
    # "netravision (disk1)" bukan "netravision (gdrive)".
    remotes = (await db.execute(select(RcloneRemote))).scalars().all()
    labels = {r.remote_name: (r.label or "") for r in remotes}
    return {
        "folders": [
            _gdrive_folder_dict(r, labels.get(r.remote_name or ""))
            for r in rows
        ],
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

    Bila koneksi rclone Drive aktif, akses folder diverifikasi dulu,
    gagal = 400 dengan pesan jelas.

    B-R4 (pilihan yang dipakai): bila rclone BELUM terhubung, tautan tetap
    disimpan, tetapi dengan penanda `verified: false` + `warning` di respons
    dan warning di log, bukan diam-diam. Alasan: alur setup memperbolehkan
    tempel tautan dulu sebelum menekan "Hubungkan"; menolak 400 akan memaksa
    urutan setup yang kaku. Bila folder ternyata salah, upload rclone tetap
    gagal dengan jelas di log (bukan diam-diam).
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

    verified = False
    warning = ""
    try:
        st = await gr.connection_status()
    except Exception:  # noqa: BLE001
        st = {"connected": False}
    if st.get("connected"):
        try:
            info = await gr.check_folder_access(folder_id)
            if not folder_name:
                folder_name = info.get("name", "")
            verified = True
        except Exception as e:  # noqa: BLE001 - rclone/subprocess bisa OSError, bukan cuma RuntimeError
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        warning = (
            "Google Drive belum terhubung, tautan disimpan TANPA verifikasi. "
            "Hubungkan Google Drive dulu, lalu periksa kembali folder ini."
        )
        log.warning("tambah folder Drive %s tanpa verifikasi: %s", folder_id, warning)
    row = GoogleDriveFolder(
        folder_url=payload.folder_url.strip(),
        folder_id=folder_id,
        folder_name=folder_name,
        local_path=(payload.local_path or "").strip(),
        retention_days=payload.retention_days,
        updated_at=datetime.now(timezone.utc),
        updated_by=admin.username,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    out = _gdrive_folder_dict(row)
    out["verified"] = verified
    if warning:
        out["warning"] = warning
    return out


@admin_router.put("/admin/storage/google-drive/{folder_id}")
async def update_gdrive_folder(
    folder_id: int,
    payload: GoogleDriveFolderIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """Ubah satu tautan folder Google Drive.

    B-S5: seperti saat tambah, akses folder diverifikasi bila rclone
    terhubung (gagal = 400). Bila folder tujuan BERGANTI, jejak upload lama
    untuk folder lama dihapus dari drive_uploads, drive_uploads dikunci per
    folder, jadi segmen lama di-upload ulang ke folder baru, bukan dianggap
    sudah ter-upload hanya karena namanya sama.
    """
    row = await db.get(GoogleDriveFolder, folder_id)
    if row is None:
        raise HTTPException(status_code=404, detail="folder tidak ditemukan")
    fid = parse_gdrive_folder_id(payload.folder_url)
    if not fid:
        raise HTTPException(
            status_code=400,
            detail="Tautan folder Google Drive tidak dikenali.",
        )
    folder_name = (payload.folder_name or "").strip()
    verified = False
    warning = ""
    from app.services import gdrive_rclone as gr

    try:
        st = await gr.connection_status()
    except Exception:  # noqa: BLE001
        st = {"connected": False}
    if st.get("connected"):
        try:
            info = await gr.check_folder_access(fid)
            if not folder_name:
                folder_name = info.get("name", "")
            verified = True
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        warning = (
            "Google Drive belum terhubung, folder diubah TANPA verifikasi. "
            "Hubungkan Google Drive dulu, lalu periksa kembali folder ini."
        )
        log.warning("ubah folder Drive %s tanpa verifikasi: %s", fid, warning)
    old_fid = row.folder_id
    if fid != old_fid:
        # Folder berganti: segmen lama harus di-upload ulang ke folder baru.
        res = await db.execute(
            delete(DriveUpload).where(DriveUpload.folder_id == old_fid)
        )
        if res.rowcount:
            log.info(
                "folder Drive %s -> %s: %d jejak upload lama dihapus, "
                "segmen akan di-upload ulang",
                old_fid, fid, res.rowcount,
            )
    row.folder_url = payload.folder_url.strip()
    row.folder_id = fid
    row.folder_name = folder_name
    row.local_path = (payload.local_path or "").strip()
    row.retention_days = payload.retention_days
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = admin.username
    await db.commit()
    out = _gdrive_folder_dict(row)
    out["verified"] = verified
    if warning:
        out["warning"] = warning
    return out


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

    Token ditempel user dari aplikasi (tombol Hubungkan), tanpa SSH,
    tanpa Cloud Console.
    """
    from app.services import gdrive_rclone as gr

    try:
        info = await gr.save_token(payload.token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - subprocess/IO bisa OSError, bukan cuma RuntimeError
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, **info}


@admin_router.delete("/admin/storage/google-drive/connection")
async def gdrive_disconnect():
    """Putuskan koneksi Drive (hapus token rclone)."""
    from app.services import gdrive_rclone as gr

    await gr.disconnect()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Koneksi Google Drive via rclone config otomatis (tanpa instal lokal/SSH)
# ---------------------------------------------------------------------------

class GdriveCodeIn(BaseModel):
    session_id: str
    code: str


@admin_router.post("/admin/storage/google-drive/connect/start")
async def gdrive_connect_start():
    """Mulai sesi hubung: jalankan rclone config sampai URL auth muncul.

    Return {session_id, auth_url}, user buka URL di browser, salin kode.
    """
    from app.services import gdrive_pkce as gc

    try:
        return await gc.start_session()
    except Exception as e:  # noqa: BLE001 - jangan 500 untuk kegagalan setup sesi
        raise HTTPException(status_code=400, detail=str(e)) from e


@admin_router.post("/admin/storage/google-drive/connect/finish")
async def gdrive_connect_finish(payload: GdriveCodeIn):
    """Selesaikan sesi hubung dengan kode verifikasi dari user."""
    from app.services import gdrive_pkce as gc

    try:
        return await gc.finish_session(payload.session_id, payload.code)
    except Exception as e:  # noqa: BLE001 - httpx bisa ConnectError/Timeout, bukan cuma RuntimeError
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Remote rclone multi-akun (satu section per remote di .rclone.conf).
# ---------------------------------------------------------------------------

class RemoteCreate(BaseModel):
    token: str
    remote_name: str
    label: str | None = Field(default=None, max_length=128)
    update_existing: bool = False


def _remote_out(row: RcloneRemote, status_info: dict | None = None) -> dict:
    out = {
        "id": row.id,
        "remote_name": row.remote_name,
        "label": row.label,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if status_info is not None:
        out["connected"] = bool(status_info.get("connected"))
        out["error"] = status_info.get("error", "")
        for key in ("total_bytes", "used_bytes", "free_bytes"):
            if key in status_info:
                out[key] = status_info[key]
    return out


def _validate_remote_name_or_400(remote_name: str) -> str:
    from app.services import gdrive_rclone as gr

    try:
        return gr.validate_remote_name(remote_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@admin_router.get("/admin/drive-remotes")
async def list_drive_remotes(
    db: AsyncSession = Depends(get_db), status: str = "full"
):
    """Daftar remote rclone dari tabel rclone_remotes + status koneksi
    tiap remote bila bisa dicek. Remote yang hanya ada di conf (tanpa
    baris DB, mis. dari tombol Hubungkan lama) ikut tercantum dengan
    in_db False supaya tidak tersembunyi.

    status=quick: lewati `rclone about` (panggilan jaringan lambat ke
    Google) supaya daftar tampil seketika; connected diisi optimistis
    (True bila remote ada di conf) dan kapasitas dibiarkan kosong.
    Frontend lalu melengkapi status tiap remote lewat
    GET /admin/drive-remotes/{name}/status di latar belakang.
    """
    from app.services import gdrive_rclone as gr

    rows = (await db.execute(
        select(RcloneRemote).order_by(RcloneRemote.remote_name)
    )).scalars().all()
    try:
        conf_names = gr.list_remote_names()
    except Exception:  # noqa: BLE001 - conf rusak jangan gugurkan list
        conf_names = []
    out = []
    seen = set()
    quick = status == "quick"
    for row in rows:
        seen.add(row.remote_name)
        if quick:
            st = {"connected": row.remote_name in conf_names, "error": ""}
        else:
            try:
                st = await gr.remote_status(row.remote_name)
            except Exception as e:  # noqa: BLE001
                st = {"connected": False, "error": str(e)}
        item = _remote_out(row, st)
        item["in_conf"] = row.remote_name in conf_names
        item["in_db"] = True
        out.append(item)
    for name in conf_names:
        if name in seen:
            continue
        if quick:
            st = {"connected": True, "error": ""}
        else:
            try:
                st = await gr.remote_status(name)
            except Exception as e:  # noqa: BLE001
                st = {"connected": False, "error": str(e)}
        out.append({
            "id": None,
            "remote_name": name,
            "label": None,
            "created_at": None,
            "connected": bool(st.get("connected")),
            "error": st.get("error", ""),
            "in_conf": True,
            "in_db": False,
        })
    return out


class AuthorizeStart(BaseModel):
    label: str = Field(default="", max_length=128)


def _next_remote_name(taken: set[str]) -> str:
    """Nama remote kosong pertama: gdrive, gdrive-2, gdrive-3, ..."""
    if "gdrive" not in taken:
        return "gdrive"
    i = 2
    while f"gdrive-{i}" in taken:
        i += 1
    return f"gdrive-{i}"


@admin_router.post("/admin/drive-remotes/authorize")
async def start_drive_authorize(
    payload: AuthorizeStart,
    db: AsyncSession = Depends(get_db),
):
    """Mulai alur hubungkan akun via `rclone authorize` di server.

    Server menjalankan `rclone authorize "drive"`, frontend mem-poll
    GET /admin/drive-remotes/authorize/{job_id} untuk mendapat link
    http://127.0.0.1:53682/auth?state=... Pengguna membuka link itu
    (butuh akses ke port 53682 server, mis. SSH forward
    `ssh -L 53682:127.0.0.1:53682 root@alamat-server`), login Google,
    izinkan. Token ditangkap server; frontend lalu menyimpan lewat POST
    /admin/drive-remotes yang sudah ada. Job lama yang masih menunggu
    dibatalkan otomatis supaya tidak ada yang tertahan."""
    from app.services import gdrive_rclone as gr

    label = (payload.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Isi dulu nama akun.")
    rows = (await db.execute(select(RcloneRemote.remote_name))).scalars().all()
    taken = set(rows) | set(gr.list_remote_names())
    remote_name = _next_remote_name(taken)
    try:
        job = await gr.start_authorize(remote_name, label)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "job_id": job["job_id"],
        "remote_name": remote_name,
        "label": label,
    }


@admin_router.get("/admin/drive-remotes/authorize/active")
async def get_active_drive_authorize():
    """Job authorize yang masih menunggu, bila ada. Dipakai frontend
    untuk memulihkan tampilan (link + tombol Batalkan) setelah refresh,
    supaya job tidak menggantung tanpa bisa dibatalkan."""
    from app.services import gdrive_rclone as gr

    for job in gr._AUTHORIZE_JOBS.values():
        if job["status"] == "waiting":
            return {
                "job_id": job["job_id"],
                "remote_name": job["remote_name"],
                "label": job.get("label", ""),
                "status": job["status"],
                "auth_url": job.get("auth_url"),
                "token": None,
                "error": None,
            }
    return {"job_id": None}


@admin_router.get("/admin/drive-remotes/authorize/{job_id}")
async def get_drive_authorize(job_id: str):
    """Status satu job authorize: waiting (auth_url bila sudah ada),
    done (token bila sudah didapat), cancelled, atau error."""
    from app.services import gdrive_rclone as gr

    job = gr.authorize_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job authorize tidak ditemukan.")
    return {
        "job_id": job["job_id"],
        "remote_name": job["remote_name"],
        "label": job.get("label", ""),
        "status": job["status"],
        "auth_url": job.get("auth_url"),
        "token": job.get("token"),
        "error": job.get("error"),
    }


@admin_router.delete("/admin/drive-remotes/authorize/{job_id}")
async def cancel_drive_authorize(job_id: str):
    """Batalkan satu job authorize yang masih menunggu: matikan proses
    rclone authorize-nya supaya tidak ada yang tertahan."""
    from app.services import gdrive_rclone as gr

    job = await gr.cancel_authorize(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job authorize tidak ditemukan.")
    return {"ok": True, "status": job["status"]}


def _remote_folder_url(remote_name: str) -> str:
    """Penanda folder root satu akun: folder google_drive_folders yang
    mewakili seluruh Drive akun ini (bukan satu tautan folder spesifik)."""
    return f"rclone:{remote_name}"


async def _ensure_remote_folder(
    db: AsyncSession, remote_name: str, label: str | None
) -> GoogleDriveFolder:
    """Buatkan entri folder untuk akun rclone bila belum ada, supaya akun
    muncul di pemilih 'Folder Google Drive tujuan' di form kamera.

    Folder sungguhan bernama 'netravision' dibuat di root Drive akun itu
    (rclone mkdir, idempotent) dan ID-nya disimpan, jadi rekaman nanti
    tersimpan di folder tersebut. Bila pembuatan folder gagal (mis. rclone
    bermasalah), jatuh kembali ke entri root (folder_url penanda
    rclone:{nama}) supaya penambahan akun tidak gagal."""
    from app.services import gdrive_rclone as gr

    row = (await db.execute(
        select(GoogleDriveFolder).where(
            GoogleDriveFolder.remote_name == remote_name
        )
    )).scalars().first()
    if row is not None:
        return row
    try:
        info = await gr.ensure_netravision_folder(remote_name)
        row = GoogleDriveFolder(
            folder_url=info["folder_url"],
            folder_id=info["folder_id"],
            folder_name=info["folder_name"],
            local_path="",
            remote_name=remote_name,
        )
    except Exception as e:  # noqa: BLE001 - folder gagal dibuat, pakai entri root
        log.warning(
            "folder netravision untuk %s gagal dibuat (%s), pakai entri root",
            remote_name, e,
        )
        row = GoogleDriveFolder(
            folder_url=_remote_folder_url(remote_name),
            folder_id="",
            folder_name=(label or "").strip() or remote_name,
            local_path="",
            remote_name=remote_name,
        )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@admin_router.post("/admin/drive-remotes")
async def create_drive_remote(
    payload: RemoteCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Tambah (atau perbarui) satu remote rclone dari token JSON hasil
    `rclone authorize "drive"`. Remote diverifikasi dulu via
    `rclone about`; gagal = 400 dan conf tidak berubah. Bila sukses,
    section remote disimpan di conf + baris DB. Bila remote_name yang
    diminta sudah terpakai dan update_existing False, dipakai nama
    kosong berikutnya (gdrive-2, ...) supaya akun baru tidak pernah
    menimpa akun lama; update_existing True = sengaja memperbarui
    remote yang sama (re-auth).

    Sekaligus buatkan entri folder untuk akun ini (_ensure_remote_folder)
    supaya akun langsung bisa dipilih sebagai 'Folder Google Drive tujuan'
    di form kamera tanpa harus tambah tautan folder dulu.
    """
    from app.services import gdrive_rclone as gr

    remote_name = _validate_remote_name_or_400(payload.remote_name)
    label = (payload.label or "").strip() or None
    # Tambah akun baru tidak boleh menimpa remote yang sudah ada: bila
    # nama yang diminta sudah terpakai (di DB atau di conf) dan ini bukan
    # update yang disengaja, alokasikan nama kosong berikutnya. Ini
    # menutup celah frontend yang menghitung nama dari state `remotes`
    # yang belum termuat (mengirim 'gdrive' lagi untuk akun kedua) yang
    # sebelumnya diam-diam menimpa token + label akun pertama. Re-auth
    # yang disengaja tetap bisa lewat update_existing=True.
    if not payload.update_existing:
        taken = set(
            (await db.execute(select(RcloneRemote.remote_name))).scalars().all()
        ) | set(gr.list_remote_names())
        if remote_name in taken:
            new_name = _next_remote_name(taken)
            log.info(
                "tambah akun: remote %s sudah terpakai, pakai %s",
                remote_name, new_name,
            )
            remote_name = new_name
    try:
        await gr.save_token(payload.token, remote_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - subprocess/IO bisa OSError
        raise HTTPException(status_code=400, detail=str(e)) from e
    row = (await db.execute(
        select(RcloneRemote).where(RcloneRemote.remote_name == remote_name)
    )).scalars().first()
    # Token disimpan terenkripsi di DB (sumber kebenaran): bila .rclone.conf
    # hilang, API membangun ulang conf dari kolom ini saat start.
    try:
        from app.core.drive_tokens import encrypt_token

        token_enc = encrypt_token(json.loads(payload.token))
    except Exception as e:  # noqa: BLE001 - key belum diset / token aneh
        log.warning("simpan token rclone ke DB gagal (%s), lanjut tanpa DB", e)
        token_enc = None
    if row is None:
        row = RcloneRemote(
            remote_name=remote_name, label=label, token_encrypted=token_enc
        )
        db.add(row)
        response.status_code = status.HTTP_201_CREATED
    else:
        row.label = label
        if token_enc is not None:
            row.token_encrypted = token_enc
        response.status_code = status.HTTP_200_OK
    await db.commit()
    await db.refresh(row)
    # Akun baru/baru diperbarui: pastikan ada entri folder untuk akun ini
    # supaya langsung muncul di pemilih folder tujuan di form kamera.
    await _ensure_remote_folder(db, remote_name, label)
    try:
        st = await gr.remote_status(remote_name)
    except Exception as e:  # noqa: BLE001
        st = {"connected": False, "error": str(e)}
    return _remote_out(row, st)


@admin_router.delete("/admin/drive-remotes/{remote_name}")
async def delete_drive_remote(
    remote_name: str, db: AsyncSession = Depends(get_db)
):
    """Hapus remote: section di conf + baris DB. 404 bila tidak ada
    di keduanya."""
    from app.services import gdrive_rclone as gr

    remote_name = _validate_remote_name_or_400(remote_name)
    row = (await db.execute(
        select(RcloneRemote).where(RcloneRemote.remote_name == remote_name)
    )).scalars().first()
    in_conf = remote_name in gr.list_remote_names()
    if row is None and not in_conf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "remote tidak ditemukan")
    if row is not None:
        await db.delete(row)
        await db.commit()
    # Hapus juga entri folder akun ini (bila ada): kamera yang menunjuk
    # ke sana kembali ke default, sama seperti hapus folder biasa.
    frow = (await db.execute(
        select(GoogleDriveFolder).where(
            GoogleDriveFolder.remote_name == remote_name
        )
    )).scalars().first()
    if frow is None:
        # Kompatibel lama: entri root penanda rclone:{nama}.
        frow = (await db.execute(
            select(GoogleDriveFolder).where(
                GoogleDriveFolder.folder_url == _remote_folder_url(remote_name)
            )
        )).scalars().first()
    if frow is not None:
        await db.execute(
            update(Stream).where(Stream.drive_folder_id == frow.id).values(
                drive_folder_id=None
            )
        )
        await db.delete(frow)
        await db.commit()
    if in_conf:
        gr.delete_remote(remote_name)
    return {"ok": True}


@admin_router.get("/admin/drive-remotes/{remote_name}/status")
async def drive_remote_status(
    remote_name: str, db: AsyncSession = Depends(get_db)
):
    """Status koneksi + kapasitas satu remote dari `rclone about`.
    404 bila remote tidak ada di DB. Bila rclone tidak terinstal,
    kembalikan connected False dengan pesan jelas, bukan crash."""
    from app.services import gdrive_rclone as gr

    remote_name = _validate_remote_name_or_400(remote_name)
    row = (await db.execute(
        select(RcloneRemote).where(RcloneRemote.remote_name == remote_name)
    )).scalars().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "remote tidak ditemukan")
    try:
        st = await gr.remote_status(remote_name)
    except Exception as e:  # noqa: BLE001
        st = {"connected": False, "error": str(e)}
    st["remote_name"] = remote_name
    st["label"] = row.label
    st["rclone_found"] = bool(gr.find_rclone())
    return st


# ---------------------------------------------------------------------------
# Status antrean upload segmen ke Drive (super_admin-only, via admin_router).
# ---------------------------------------------------------------------------


@admin_router.get("/admin/drive/upload-queue")
async def drive_upload_queue(db: AsyncSession = Depends(get_db)):
    """Antrean upload: segmen .mp4 stabil yang belum tercatat ter-upload.

    pending = segmen stabil (lebih tua dari _STABLE_SEC uploader) di
    direktori kamera mode drive/both yang belum ada di drive_uploads
    (cocok stream_id + segment_name). last_success_at = uploaded_at
    terbaru di drive_uploads, null bila belum pernah. remotes = status
    koneksi tiap remote rclone; connected False bila rclone tidak ada
    atau gagal, tanpa crash.
    """
    from app.services.disks import camera_rec_dir
    from app.services.drive_uploader import _STABLE_SEC
    from app.services.recording import parse_segment_name
    from app.services import gdrive_rclone as gr

    settings = get_settings()
    now = time.time()
    streams = (
        await db.execute(
            select(Stream).where(
                Stream.recording_enabled.is_(True),
                Stream.storage_mode.in_(["drive", "both"]),
            )
        )
    ).scalars().all()
    pending = 0
    for s in streams:
        uploaded = {
            r[0]
            for r in (
                await db.execute(
                    select(DriveUpload.segment_name).where(
                        DriveUpload.stream_id == s.id
                    )
                )
            ).all()
        }
        rec_dir = camera_rec_dir(s, settings.recordings_dir)
        try:
            names = os.listdir(rec_dir)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".mp4"):
                continue
            if parse_segment_name(name) is None:
                continue
            if name in uploaded:
                continue
            path = os.path.join(rec_dir, name)
            try:
                if now - os.path.getmtime(path) < _STABLE_SEC:
                    continue
                if os.path.getsize(path) == 0:
                    continue
            except OSError:
                continue
            pending += 1
    last = (
        await db.execute(select(func.max(DriveUpload.uploaded_at)))
    ).scalar()
    try:
        remote_names = gr.list_remote_names()
    except Exception:  # noqa: BLE001
        remote_names = []
    remotes = []
    for name in remote_names:
        try:
            st = await gr.remote_status(name)
        except Exception:  # noqa: BLE001
            st = {"connected": False}
        remotes.append(
            {"remote_name": name, "connected": bool(st.get("connected"))}
        )
    return {
        "pending": pending,
        "last_success_at": last.isoformat() if last else None,
        "remotes": remotes,
    }
