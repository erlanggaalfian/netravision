"""Router admin: daftar disk rekaman (paritas v2.0).

GET /api/admin/disks, super_admin-only, mengembalikan daftar mount
point lokal dari app.services.disks.list_disks apa adanya:
mount, size_bytes, avail_bytes, size_human, avail_human, fstype,
usage_pct.
"""

from pydantic import BaseModel

from fastapi import APIRouter, Depends

from app.core.rbac import require_roles
from app.services.disks import list_disks

router = APIRouter(
    tags=["admin-disks"], dependencies=[Depends(require_roles("super_admin"))]
)


class DiskOut(BaseModel):
    mount: str
    size_bytes: int
    avail_bytes: int
    size_human: str
    avail_human: str
    fstype: str
    usage_pct: float


@router.get("/admin/disks", response_model=list[DiskOut])
async def list_admin_disks():
    """Daftar semua disk ter-mount (df, >1GB), paritas v2.0."""
    return list_disks()
