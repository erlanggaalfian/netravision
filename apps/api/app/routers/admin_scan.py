"""Router admin: network subnet scan (CIDR) untuk tab Camera Scanner.

POST /api/admin/scan-subnet, pindai satu subnet (maks 256 host, pola v2.0):
cek TCP singkat per host, lalu discovery path RTSP + verifikasi video
(rtsp_discovery). Rate limit sama seperti /admin/scan (10/menit).

Scan berjalan ASYNC: POST langsung mengembalikan 202 + job_id dan
pemindaian jalan di background sebagai asyncio task, supaya request
tidak kena timeout Cloudflare 100 detik (HTTP 524) saat diakses via
domain. Progres dan hasil diambil lewat GET /admin/scan-subnet/{job_id}.
"""

import asyncio
import ipaddress
import logging
import time
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.rate_limit import rate_limited
from app.core.rbac import require_roles
from app.schemas.stream import ScanPath
from app.services import rtsp_discovery

router = APIRouter(
    # E-K1 (backend): Scanner hanya super_admin, bukan admin biasa.
    tags=["admin-scan"], dependencies=[Depends(require_roles("super_admin"))]
)
log = logging.getLogger("netravision.admin_scan")

_MAX_HOSTS = 256
_HOST_CONCURRENCY = 4
_HOST_TIMEOUT = 45.0  # detik maksimum discovery per host
# H1: batas waktu global seluruh scan, satu /24 tak boleh menggantung
# request sampai ~48 menit walau tiap host dibatasi 45 detik.
_SCAN_GLOBAL_TIMEOUT = 300.0  # detik

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


class SubnetScanJobCreated(BaseModel):
    job_id: str


class SubnetScanJobStatus(BaseModel):
    status: str  # running | done | error
    scanned: int
    total: int
    hosts: list[SubnetHost]
    candidates: list[SubnetCandidate]
    error: str | None = None


@dataclass
class _ScanJob:
    job_id: str
    total: int
    status: str = "running"  # running | done | error
    scanned: int = 0
    hosts: list[SubnetHost] = field(default_factory=list)
    candidates: list[SubnetCandidate] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None


# Job scan disimpan di memori proses saja (cukup untuk deployment
# single-replica, pola NetraVision saat ini). Maksimal 10 job terakhir;
# job selesai dihapus setelah 10 menit.
_jobs: dict[str, _ScanJob] = {}
_jobs_lock = asyncio.Lock()
_MAX_JOBS = 10
_JOB_TTL = 600.0  # detik


def _prune_jobs_locked() -> None:
    """Buang job selesai yang kedaluwarsa, lalu pangkas ke 10 job terakhir.

    Harus dipanggil sambil memegang _jobs_lock."""
    now = time.monotonic()
    for jid in [
        jid
        for jid, job in _jobs.items()
        if job.status != "running"
        and job.finished_at is not None
        and now - job.finished_at > _JOB_TTL
    ]:
        del _jobs[jid]
    while len(_jobs) > _MAX_JOBS:
        finished = sorted(
            (j for j in _jobs.values() if j.status != "running"),
            key=lambda j: j.finished_at or 0,
        )
        victim = (
            finished[0]
            if finished
            else min(_jobs.values(), key=lambda j: j.created_at)
        )
        del _jobs[victim.job_id]


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
        except Exception as e:  # noqa: BLE001 - A-R6: satu host error tak
            # boleh menggugurkan seluruh scan; laporkan sebagai error.
            log.warning("scan host %s gagal: %s", host, e)
            return SubnetHost(
                host=host, port=port, status="error",
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


async def _run_scan(
    job: _ScanJob,
    hosts: list[str],
    port: int,
    username: str,
    password: str,
) -> None:
    """Jalankan pemindaian di background sebagai asyncio task.

    Perbaikan H1 tetap berlaku di sini: timeout global, batas host sudah
    ditegakkan di POST sebelum job dibuat, dan satu host error tidak
    menggugurkan scan (return_exceptions setara: tiap task dijamin
    menghasilkan SubnetHost). Hasil parsial ditulis ke job selagi jalan
    supaya GET bisa menampilkan progres."""
    sem = asyncio.Semaphore(_HOST_CONCURRENCY)
    tasks = [
        asyncio.create_task(
            _scan_host(h, port, username, password, sem)
        )
        for h in hosts
    ]
    try:
        async def _collect() -> None:
            for coro in asyncio.as_completed(tasks):
                result = await coro
                async with _jobs_lock:
                    job.hosts.append(result)
                    job.scanned += 1

        await asyncio.wait_for(_collect(), timeout=_SCAN_GLOBAL_TIMEOUT)
    except asyncio.TimeoutError:
        # H1: timeout global, kembalikan hasil parsial, sisanya timeout.
        for h, t in zip(hosts, tasks):
            if not t.done():
                t.cancel()
                async with _jobs_lock:
                    job.hosts.append(SubnetHost(
                        host=h, port=port, status="timeout",
                        best_main=None, best_sub=None, paths=[],
                    ))
                    job.scanned += 1
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:  # noqa: BLE001 - pengaman terakhir job
        log.warning("scan-subnet job %s gagal: %s", job.job_id, e)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with _jobs_lock:
            job.status = "error"
            job.error = str(e) or "Scan gagal"
            job.finished_at = time.monotonic()
        return
    async with _jobs_lock:
        # Urutkan hasil mengikuti urutan subnet, bukan urutan selesai.
        order = {h: i for i, h in enumerate(hosts)}
        job.hosts.sort(key=lambda h: order.get(h.host, 0))
        # A-R6: host unreachable tetap muncul di hasil (bukan disaring).
        found = [h for h in job.hosts if h.status != "unreachable"]
        job.candidates = [
            SubnetCandidate(
                host=h.host, port=h.port, brand="auto",
                main_url=h.best_main or "", sub_url=h.best_sub,
            )
            for h in found
            if h.best_main
        ]
        job.status = "done"
        job.finished_at = time.monotonic()
    log.info(
        "scan-subnet job %s: %d host terjangkau, %d dengan video",
        job.job_id, len(found), len(job.candidates),
    )


@router.post(
    "/admin/scan-subnet",
    response_model=SubnetScanJobCreated,
    status_code=202,
    dependencies=[Depends(rate_limited(10, 60))],
)
async def scan_subnet(data: SubnetScanRequest):
    """Terima subnet CIDR, langsung kembalikan 202 + job_id, dan mulai
    pemindaian di background. Validasi CIDR dan batas 256 host tetap di
    sini, sebelum job dibuat. Hasil diambil via GET job status."""
    try:
        network = ipaddress.ip_network(data.ip_range, strict=False)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"Format CIDR IP tidak valid: {e}"
        )
    # H1: tegakkan batas 256 host SEBELUM mematerialisasi daftar host.
    # Hitung dari prefix saja, CIDR /16 atau IPv6 /64 tidak boleh sempat
    # membangun daftar raksasa (hang/OOM) sebelum batas berlaku.
    if network.version == 4:
        n_hosts = (
            network.num_addresses
            if network.prefixlen >= 31
            else network.num_addresses - 2  # network + broadcast
        )
    else:
        n_hosts = network.num_addresses  # batas atas (tanpa broadcast)
    if n_hosts > _MAX_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Demi keamanan, batas pemindaian maksimum adalah 256 IP "
                "(misal subnet /24)"
            ),
        )
    hosts = [str(h) for h in network.hosts()]
    job = _ScanJob(job_id=uuid.uuid4().hex, total=len(hosts))
    async with _jobs_lock:
        _prune_jobs_locked()
        _jobs[job.job_id] = job
    asyncio.create_task(
        _run_scan(job, hosts, data.port, data.username, data.password)
    )
    log.info(
        "scan-subnet job %s dimulai: %s (%d host)",
        job.job_id, data.ip_range, len(hosts),
    )
    return SubnetScanJobCreated(job_id=job.job_id)


@router.get(
    "/admin/scan-subnet/{job_id}",
    response_model=SubnetScanJobStatus,
)
async def scan_subnet_status(job_id: str):
    """Status + hasil satu job scan. Saat running, hosts/candidates
    berisi hasil parsial sejauh ini (boleh kosong)."""
    async with _jobs_lock:
        _prune_jobs_locked()
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404, detail="Job scan tidak ditemukan"
            )
        return SubnetScanJobStatus(
            status=job.status,
            scanned=job.scanned,
            total=job.total,
            hosts=list(job.hosts),
            candidates=list(job.candidates),
            error=job.error,
        )
