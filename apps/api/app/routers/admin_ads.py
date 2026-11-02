"""Router admin: konfigurasi iklan/banner + upload gambar.

- GET /api/ad-config: publik (dibaca player/embed).
- POST /api/admin/ad-config, upload-image, PUT grup ads: butuh peran admin.
Disimpan sebagai baris key/value di tabel ad_config (key "default",
"group:<nama>").
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_roles
from app.db.session import get_db
from app.models.misc import AdConfig

_DEFAULT = {"enabled": False, "title": None, "image_url": None, "link_url": None, "position": None}

router = APIRouter(tags=["admin-ads"])
admin_router = APIRouter(tags=["admin-ads"], dependencies=[Depends(require_roles("admin"))])


class AdConfigIn(BaseModel):
    enabled: bool = False
    title: str | None = None
    image_url: str | None = None
    link_url: str | None = None
    position: str | None = None


class GroupAdsIn(BaseModel):
    ads_enabled: bool


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
async def public_ad_config(db: AsyncSession = Depends(get_db)):
    return await _get_value(db, "default")


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
    return {"image_url": f"/uploads/ads/{fname}"}
