"""Router admin: network subnet scan (CIDR) untuk tab Camera Scanner.

POST /api/admin/scan-subnet — pindai satu subnet (maks 256 host, pola v2.0):
cek TCP singkat per host, lalu bangun kandidat stream via brand-resolver
yang sudah ada. Rate limit sama seperti /admin/scan (10/menit).
"""

import asyncio
import ipaddress
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.rate_limit import rate_limited
from app.core.rbac import require_roles
from app.services.stream_resolver import resolve_stream

router = APIRouter(
    tags=["admin-scan"], dependencies=[Depends(require_roles("admin"))]
)
log = logging.getLogger("netravision.admin_scan")

# Brand yang dicoba saat scan "auto" (sama seperti /admin/scan).
_AUTO_BRANDS = ["hikvision", "dahua", "uniview_ipc", "tplink_vigi", "reolink"]
_MAX_HOSTS = 256
_TCP_TIMEOUT = 1.5
_CONCURRENCY = 32


class SubnetScanRequest(BaseModel):
    ip_range: str = Field(min_length=1)  # CIDR, mis. "192.168.1.0/24"
    port: int = Field(default=554, ge=1, le=65535)
    username: str = "admin"
    password: str = ""
    brand: str = "auto"


class SubnetCandidate(BaseModel):
    host: str
    port: int
    brand: str
    main_url: str
    sub_url: str | None


class SubnetScanResult(BaseModel):
    candidates: list[SubnetCandidate]


async def _tcp_alive(host: str, port: int) -> bool:
    """Cek singkat: apakah ada yang mendengar di host:port?"""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=_TCP_TIMEOUT
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001 - timeout / refused / unreachable
        return False


async def _scan_host(
    host: str,
    port: int,
    username: str,
    password: str,
    brands: list[str],
    sem: asyncio.Semaphore,
) -> list[SubnetCandidate]:
    async with sem:
        if not await _tcp_alive(host, port):
            return []
        out: list[SubnetCandidate] = []
        for brand in brands:
            try:
                res = await resolve_stream(
                    brand=brand,
                    rtsp_url=None,
                    user=username or None,
                    password=password or None,
                    host=host,
                    port=port,
                    channel=1,
                )
            except ValueError:
                continue
            out.append(
                SubnetCandidate(
                    host=host,
                    port=port,
                    brand=res.brand,
                    main_url=res.main_url,
                    sub_url=res.sub_url,
                )
            )
        return out


@router.post(
    "/admin/scan-subnet",
    response_model=SubnetScanResult,
    dependencies=[Depends(rate_limited(10, 60))],
)
async def scan_subnet(data: SubnetScanRequest):
    """Pindai subnet CIDR: host yang port-nya terbuka dikembalikan
    sebagai kandidat kamera (satu kandidat per brand yang cocok)."""
    try:
        network = ipaddress.ip_network(data.ip_range, strict=False)
        hosts = [str(h) for h in network.hosts()]
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"Format CIDR IP tidak valid: {e}"
        )
    if len(hosts) > _MAX_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Demi keamanan, batas pemindaian maksimum adalah 256 IP "
                "(misal subnet /24)"
            ),
        )
    brands = (
        [data.brand]
        if data.brand and data.brand != "auto"
        else list(_AUTO_BRANDS)
    )
    sem = asyncio.Semaphore(_CONCURRENCY)
    results = await asyncio.gather(
        *(
            _scan_host(
                h, data.port, data.username, data.password, brands, sem
            )
            for h in hosts
        )
    )
    candidates = [c for group in results for c in group]
    log.info(
        "scan-subnet %s: %d host hidup, %d kandidat",
        data.ip_range,
        len([g for g in results if g]),
        len(candidates),
    )
    return SubnetScanResult(candidates=candidates)
