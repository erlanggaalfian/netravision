"""Router admin: daftar disk rekaman (paritas v2.0).

GET /api/admin/disks, super_admin-only, mengembalikan daftar mount
point lokal dari app.services.disks.list_disks apa adanya:
mount, size_bytes, avail_bytes, size_human, avail_human, fstype,
usage_pct.
"""

import asyncio

from pydantic import BaseModel

from fastapi import APIRouter, Depends

from app.core.rate_limit import rate_limited
from app.core.rbac import require_roles
from app.services.disks import list_disks

router = APIRouter(
    tags=["admin-disks"],
    # 4.7: daftar disk tanpa batas; disk-summary di admin_streams
    # memicu os.walk. 20/menit per IP seperti router admin lain.
    dependencies=[
        Depends(require_roles("super_admin")),
        Depends(rate_limited(20, 60)),
    ],
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
    """Daftar semua disk ter-mount (df, >1GB), paritas v2.0.

    Temuan 3.9: `list_disks()` sinkron (subprocess `df` + `rclone
    about` per remote) dan dulu dipanggil langsung dari endpoint
    async sehingga memblokir event loop; kini lewat `to_thread`.
    """
    return await asyncio.to_thread(list_disks)
