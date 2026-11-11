"""Router admin: konfigurasi iklan/banner + upload gambar (paritas v2.0).

- GET /api/ad-config: publik (dibaca player/embed). Bila pemanggil dikenali
  sebagai user login (bukan super_admin) dengan show_ads=False, kembalikan
  config nonaktif.
- POST /api/admin/ad-config, upload-image, PUT grup ads: butuh peran admin.
Disimpan sebagai baris key/value di tabel ad_config (key "default",
"group:<nama>").
"""

import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import _user_from_token, bearer_scheme, require_roles
from app.db.session import get_db
from app.models.misc import AdConfig
from app.models.users import User

router = APIRouter(tags=["admin-ads"])
# E-K1: kelola iklan hanya super_admin (admin biasa tidak boleh).
admin_router = APIRouter(tags=["admin-ads"], dependencies=[Depends(require_roles("super_admin"))])


class AdConfigIn(BaseModel):
    image_url: str = ""
    marquee_text: str = ""
    bg_color: str = "#1e293b"
    text_color: str = "#ffffff"
    # A-R3: nilai divalidasi (Literal/rentang) supaya nilai tidak
    # valid tidak tersimpan diam-diam.
    scroll_speed: int = Field(default=5, ge=1, le=100)
    font_size: int = Field(default=10, ge=6, le=72)
    font_family: str = "monospace"
    image_opacity: float = Field(default=1.0, ge=0, le=1)
    bg_opacity: float = Field(default=1.0, ge=0, le=1)
    text_opacity: float = Field(default=1.0, ge=0, le=1)
    is_active: bool = True
    box_width: int = Field(default=100, ge=1, le=100)
    text_align: Literal["left", "center", "right"] = "left"
    image_height: int = Field(default=20, ge=0, le=500)
    embed_timeout_seconds: int = Field(default=300, ge=0, le=86400)
    click_to_play: bool = True
    # Fleksibilitas tampilan (2026-11-06):
    position: Literal["bottom", "top"] = "bottom"  # bottom | top
    banner_height: int = Field(default=0, ge=0, le=1000)  # px, 0 = otomatis
    # Jenis tampilan (2026-11-06): always (selalu tampil) | periodic
    # (berkala). Teks selalu berjalan di semua pilihan, tidak ada statis.
    display_mode: Literal["always", "periodic"] = "always"
    # Cara tampil berkala: interval (tampil/sembunyi bergantian) | hover
    # (terlihat saat hover + jeda) | click (muncul saat diklik)
    periodic_trigger: Literal["interval", "hover", "click"] = "interval"
    popup_show_seconds: int = Field(default=10, ge=0, le=3600)  # detik tampil (berkala + interval)
    popup_hide_seconds: int = Field(default=50, ge=0, le=3600)  # detik sembunyi (berkala + interval)
    marquee_hover_show_seconds: int = Field(default=5, ge=0, le=3600)  # detik terlihat saat hover
    # Jeda setelah hover: iklan masih tampil X detik setelah hover
    # selesai, baru hilang (bukan cooldown pemblokir).
    marquee_hover_hide_delay_seconds: int = Field(default=5, ge=0, le=3600)
    marquee_click_show_seconds: int = Field(default=5, ge=0, le=3600)  # detik muncul saat diklik
    # Audiens (2026-11-06): all | guest | roles | users
    audience: Literal["all", "guest", "roles", "users"] = "all"
    audience_roles: list[str] = []
    audience_user_ids: list[int] = []
    # Interaksi (2026-11-06):
    click_url: str = ""


class GroupAdsIn(BaseModel):
    ads_enabled: bool


_DEFAULT = AdConfigIn().model_dump()


def _inactive_config() -> dict:
    """Config nonaktif untuk user yang show_ads=False (paritas v2.0)."""
    cfg = dict(_DEFAULT)
    cfg.update(image_url="", marquee_text="", is_active=False)
    return cfg


async def _get_value(db: AsyncSession, key: str) -> dict:
    res = await db.execute(select(AdConfig).where(AdConfig.key == key))
    row = res.scalars().first()
    if row and isinstance(row.value, dict):
        return {**_DEFAULT, **row.value}
    return dict(_DEFAULT)


async def _set_value(db: AsyncSession, key: str, value: dict) -> dict:
    res = await db.execute(select(AdConfig).where(AdConfig.key == key))
    row = res.scalars().first()
    if row is None:
        row = AdConfig(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    await db.commit()
    return value


async def _group_ads_enabled(db: AsyncSession, group_name: str | None) -> bool | None:
    """Setelan iklan per grup (key group:<nama>); None bila tidak diatur."""
    if not group_name:
        return None
    res = await db.execute(select(AdConfig).where(AdConfig.key == f"group:{group_name}"))
    row = res.scalars().first()
    if row and isinstance(row.value, dict) and "ads_enabled" in row.value:
        return bool(row.value["ads_enabled"])
    return None


@router.get("/ad-config")
async def public_ad_config(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Config iklan publik; nonaktifkan bila user login punya show_ads=False
    atau di luar audiens yang dikonfigurasi superadmin."""
    raw = credentials.credentials if credentials else token
    user: User | None = None
    if raw:
        try:
            user = await _user_from_token(raw, db)
        except HTTPException:
            user = None
    cfg = await _get_value(db, "default")
    # A-S10: setelan iklan per grup menimpa default untuk anggota grup itu.
    group_ads = await _group_ads_enabled(db, user.admin_group if user else None)
    if group_ads is False:
        return _inactive_config()
    if not cfg.get("is_active", True) and group_ads is not True:
        return _inactive_config()
    if isinstance(user, User):
        # show_ads=False (paritas v2.0) selalu menonaktifkan.
        if user.role != "super_admin" and not user.show_ads:
            return _inactive_config()
        # Audiens per peran / per user (2026-11-06).
        audience = cfg.get("audience", "all")
        if audience == "guest":
            # A-S8: audiens guest berarti iklan UNTUK guest yang login;
            # user login non-guest justru tidak melihatnya.
            if user.role != "guest":
                return _inactive_config()
        if audience == "roles":
            roles = cfg.get("audience_roles") or []
            if roles and user.role not in roles:
                return _inactive_config()
        elif audience == "users":
            ids = cfg.get("audience_user_ids") or []
            if ids and user.id not in ids:
                return _inactive_config()
    else:
        # Tamu (tanpa login): hanya bila audiens all atau guest.
        audience = cfg.get("audience", "all")
        if audience in ("roles", "users"):
            return _inactive_config()
    return cfg


@admin_router.get("/admin/ad-config")
async def get_ad_config_raw(db: AsyncSession = Depends(get_db)):
    """Config iklan MENTAH untuk halaman Admin (super_admin only).

    Berbeda dengan GET /ad-config yang memfilter menurut audiens dan
    show_ads pemanggil, endpoint ini mengembalikan setelan apa adanya
    supaya halaman Admin Iklan/API Key bisa memuat config asli.
    """
    return await _get_value(db, "default")


@admin_router.post("/admin/ad-config")
async def save_ad_config(data: AdConfigIn, db: AsyncSession = Depends(get_db)):
    return await _set_value(db, "default", data.model_dump())


@admin_router.put("/admin/groups/{group_name}/ads")
async def set_group_ads(group_name: str, data: GroupAdsIn, db: AsyncSession = Depends(get_db)):
    # A-S10: nama grup harus ada (grup user: ada akun dengan
    # admin_group itu). Grup iklan dibaca lewat admin_group user.
    res = await db.execute(select(User).where(User.admin_group == group_name))
    if res.scalars().first() is None:
        raise HTTPException(status_code=404, detail="grup tidak ditemukan")
    await _set_value(db, f"group:{group_name}", {"ads_enabled": data.ads_enabled})
    return {"ok": True, "ads_enabled": data.ads_enabled}


_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@admin_router.post("/admin/ad-config/upload-image")
async def upload_ad_image(image: UploadFile = File(...)):
    ext = Path(image.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="format gambar tidak didukung")
    dest_dir = Path("data/uploads/ads")
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}{ext}"
    dest = dest_dir / fname
    # A-R3: baca bertahap dengan batas 5 MB; tolak sebelum seluruh
    # isi sempat memenuhi memori.
    limit = 5 * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await image.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=400, detail="ukuran maksimal 5 MB")
        chunks.append(chunk)
    dest.write_bytes(b"".join(chunks))
    return {"image_url": f"/api/uploads/ads/{fname}"}
