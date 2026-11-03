"""Router admin: network subnet scan (CIDR) untuk tab Camera Scanner.

POST /api/admin/scan-subnet — pindai satu subnet (maks 256 host, pola v2.0):
cek TCP singkat per host, lalu discovery path RTSP + verifikasi video
(rtsp_discovery). Rate limit sama seperti /admin/scan (10/menit).
"""

import asyncio
import ipaddress
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.rate_limit import rate_limited
from app.core.rbac import require_roles
from app.schemas.stream import ScanPath
from app.services import rtsp_discovery

router = APIRouter(
    tags=["admin-scan"], dependencies=[Depends(require_roles("admin"))]
)
log = logging.getLogger("netravision.admin_scan")

_MAX_HOSTS = 256
_HOST_CONCURRENCY = 4
_HOST_TIMEOUT = 45.0  # detik maksimum discovery per host

class SubnetScanRequest(BaseModel):
    ip_range: str = Field(min_length=1)  # CIDR, mis. "192.168.1.0/24"
    port: int = Field(default=554, ge=1, le=65535)
    username: str = "admin"
    password: str = ""
    brand: str = "auto"  # tak dipakai lagi (discovery brand-agnostik), kompat API


class SubnetCandidate(BaseModel):
    """Kompatibilitas lama: satu kandidat per host yang punya video."""
    host: str
    port: int
    brand: str
    main_url: str
    sub_url: str | None


class SubnetHost(BaseModel):
    host: str
    port: int
    status: str  # video | no_video | auth_failed | not_found | timeout | error | unreachable
    best_main: str | None
    best_sub: str | None
    paths: list[ScanPath]


class SubnetScanResult(BaseModel):
    hosts: list[SubnetHost]
    candidates: list[SubnetCandidate]  # kompat: host dengan path video, pakai best_main


def _host_status(disc: rtsp_discovery.DiscoveryResult) -> str:
    if not disc.reachable:
        return "unreachable"
    if disc.best_main:
        return "video"
    statuses = {p.status for p in disc.paths}
    for s in ("auth_failed", "no_video", "not_found", "timeout", "error"):
        if s in statuses:
            return s
    return "error"


async def _scan_host(
    host: str,
    port: int,
    username: str,
    password: str,
    sem: asyncio.Semaphore,
) -> SubnetHost:
    async with sem:
        try:
            disc = await asyncio.wait_for(
                rtsp_discovery.discover_host(
                    host, port, username or None, password or None
                ),
                timeout=_HOST_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return SubnetHost(
                host=host, port=port, status="timeout",
                best_main=None, best_sub=None, paths=[],
            )
    paths = [
        ScanPath(
            path=p.path, url=p.url, status=p.status, codec=p.codec,
            width=p.width, height=p.height, fps=p.fps,
            gop_seconds=p.gop_seconds,
            role="main" if p.url == disc.best_main
            else ("sub" if p.url == disc.best_sub else None),
        )
        for p in disc.paths
    ]
    return SubnetHost(
        host=host, port=port, status=_host_status(disc),
        best_main=disc.best_main, best_sub=disc.best_sub, paths=paths,
    )


@router.post(
    "/admin/scan-subnet",
    response_model=SubnetScanResult,
    dependencies=[Depends(rate_limited(10, 60))],
)
async def scan_subnet(data: SubnetScanRequest):
    """Pindai subnet CIDR: tiap host yang port-nya terbuka di-discovery
    path RTSP-nya dan diverifikasi benar-benar mengirim video."""
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
    sem = asyncio.Semaphore(_HOST_CONCURRENCY)
    results = await asyncio.gather(
        *(_scan_host(h, data.port, data.username, data.password, sem)
          for h in hosts)
    )
    found = [h for h in results if h.status != "unreachable"]
    candidates = [
        SubnetCandidate(
            host=h.host, port=h.port, brand="auto",
            main_url=h.best_main or "", sub_url=h.best_sub,
        )
        for h in found
        if h.best_main
    ]
    log.info(
        "scan-subnet %s: %d host terjangkau, %d dengan video",
        data.ip_range, len(found), len(candidates),
    )
    return SubnetScanResult(hosts=found, candidates=candidates)
