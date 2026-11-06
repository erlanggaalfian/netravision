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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import _user_from_token, bearer_scheme, require_roles
from app.db.session import get_db
from app.models.misc import AdConfig
from app.models.users import User

router = APIRouter(tags=["admin-ads"])
admin_router = APIRouter(tags=["admin-ads"], dependencies=[Depends(require_roles("admin"))])


class AdConfigIn(BaseModel):
    image_url: str = ""
    marquee_text: str = ""
    bg_color: str = "#1e293b"
    text_color: str = "#ffffff"
    scroll_speed: int = 5
    font_size: int = 10
    font_family: str = "monospace"
    image_opacity: float = 1.0
    bg_opacity: float = 1.0
    text_opacity: float = 1.0
    is_active: bool = True
    box_width: int = 100
    text_align: str = "left"
    image_height: int = 20
    embed_timeout_seconds: int = 300
    click_to_play: bool = True
    # Fleksibilitas tampilan (2026-11-06):
    position: str = "bottom"  # bottom | top
    banner_height: int = 0  # px, 0 = otomatis
    display_mode: str = "marquee"  # marquee | popup | static
    popup_trigger: str = "always"  # always | interval | hover
    popup_show_seconds: int = 10  # detik tampil (mode popup + trigger interval)
    popup_hide_seconds: int = 50  # detik sembunyi (mode popup + trigger interval)
    # Audiens (2026-11-06): all | guest | roles | users
    audience: str = "all"
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
    if not cfg.get("is_active", True):
        return _inactive_config()
    if isinstance(user, User):
        # show_ads=False (paritas v2.0) selalu menonaktifkan.
        if user.role != "super_admin" and not user.show_ads:
            return _inactive_config()
        # Audiens per peran / per user (2026-11-06).
        audience = cfg.get("audience", "all")
        if audience == "guest":
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


@admin_router.post("/admin/ad-config")
async def save_ad_config(data: AdConfigIn, db: AsyncSession = Depends(get_db)):
    return await _set_value(db, "default", data.model_dump())


@admin_router.put("/admin/groups/{group_name}/ads")
async def set_group_ads(group_name: str, data: GroupAdsIn, db: AsyncSession = Depends(get_db)):
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
    content = await image.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="ukuran maksimal 5 MB")
    dest.write_bytes(content)
    return {"image_url": f"/api/uploads/ads/{fname}"}
