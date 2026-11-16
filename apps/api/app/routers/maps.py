"""Router maps: penyelesaian lokasi multi-format menjadi koordinat.

POST /api/maps/resolve-location menerima teks lokasi apa pun
(koordinat desimal, tautan Google Maps, Plus Code, DMS, alamat)
dan mengembalikan latitude/longitude. Dipakai kolom "Lokasi" di
Scanner, Tambah/Ubah Kamera, dan Set Koordinat. Butuh login.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.rbac import require_roles
from app.models.users import User
from app.services.location import LocationError, resolve_location

log = logging.getLogger("netravision.maps")

router = APIRouter(tags=["maps"])


class ResolveLocationIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    ref_lat: float | None = Field(default=None, ge=-90, le=90)
    ref_lng: float | None = Field(default=None, ge=-180, le=180)


class ResolveLocationOut(BaseModel):
    latitude: float
    longitude: float
    format: str
    place_name: str | None = None


@router.post("/maps/resolve-location", response_model=ResolveLocationOut)
async def resolve_location_endpoint(
    body: ResolveLocationIn,
    _user: User = Depends(require_roles("admin")),
) -> ResolveLocationOut:
    # Hanya admin (super_admin lolos require_roles): endpoint ini
    # memicu fetch jaringan keluar (redirect tautan pendek + geocoding)
    # dan hanya dipakai form admin (Scanner, Tambah/Ubah Kamera, Set
    # Koordinat, Edit Lokasi). User/guest tidak punya form itu, jadi
    # tidak perlu akses resolve-location (S-8).
    try:
        got = await resolve_location(body.text, body.ref_lat, body.ref_lng)
    except LocationError as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=str(e)) from e
    return ResolveLocationOut(
        latitude=got.latitude,
        longitude=got.longitude,
        format=got.format,
        place_name=got.place_name,
    )
