"""Router admin: network subnet scan (CIDR) untuk tab Camera Scanner.

POST /api/admin/scan-subnet, pindai satu subnet (maks 256 host, pola v2.0):
funnel 3 tahap, baru discovery path RTSP + verifikasi video
(rtsp_discovery). Rate limit sama seperti /admin/scan (10/menit).

Alur 3 tahap (perintah user 2026-11-13 17:57 WIB, "buat scanner lebih
pintar"):
  Tahap 1, IP reachable: cek cepat tiap host, ICMP ping singkat
    (timeout 1 detik). Banyak kamera memblokir ICMP, jadi bila ping
    tidak menjawab JANGAN langsung buang host itu: fallback TCP connect
    singkat (1 detik) ke port RTSP yang diminta, lalu ke port 80 (UI web
    kamera). Lolos bila salah satu menjawab. Ketiga probe jalan
    BERSAMAAN (bukan berurutan) supaya IP mati hanya makan ~1 dtk.
  Tahap 2, port RTSP: hanya dari IP yang lolos tahap 1, cek port RTSP
    (port yang diminta, default 554) via TCP connect singkat (1 detik).
  Tahap 3, cek kamera: HANYA IP yang lolos tahap 1 DAN 2 menjalani
    discovery kamera penuh (rtsp_discovery.discover_host, termasuk
    verifikasi video, timeout 30 detik per host, konkurensi 12).
    Kamera yang sudah terdaftar + sedang online di database memakai
    jalur cepat (tanpa ffprobe bila path main yang dikenal terbuka)
    dan ditandai "Sudah terdaftar" di hasil.

IP yang gagal tahap 1 dicatat status 'unreachable', yang gagal tahap 2
dicatat status BARU 'port_closed' (port RTSP tertutup). Keduanya tetap
dikembalikan API (bukan disaring) supaya hitungan funnel tetap benar,
tapi FRONTEND tidak menampilkan baris 'unreachable' (hanya noise saat
scan /24) — jumlahnya tetap tampil di ringkasan sebagai "tidak
terjangkau (disembunyikan)". Frontend sudah punya fallback (status tak
dikenal tampil "Gagal"), tapi label 'port_closed' ditambahkan di
scanner/page.tsx supaya tampil "Port RTSP tertutup".

Klasifikasi main/sub PINTAR (perintah user 2026-11-13 19:19 WIB):
rtsp_discovery memilih main/sub dari resolusi ffprobe (terbesar =
main, lebih kecil = sub) + pola nama path sebagai tiebreaker saat
resolusi seri (101/102, subtype=0/1, stream1/2, s0/s1, main/sub,
ch00_0/1, av0_0/1, /0 vs /1, /11 vs /12), dan menandai role
'main'/'sub' di tiap path terpilih supaya UI menampilkan keduanya.

Scan berjalan ASYNC: POST langsung mengembalikan 202 + job_id dan
pemindaian jalan di background sebagai asyncio task, supaya request
tidak kena timeout Cloudflare 100 detik (HTTP 524) saat diakses via
domain. Progres dan hasil diambil lewat GET /admin/scan-subnet/{job_id}.
GET juga mengembalikan `stage` (reachability | port_check | discovery |
done), `reachable_count` (lolos tahap 1) dan `port_open_count` (lolos
tahap 2) supaya UI bisa menampilkan funnel-nya; field baru ini
opsional (default) sehingga klien lama tetap jalan.
"""

import asyncio
import ipaddress
import logging
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limited
from app.core.rbac import require_roles
from app.db.session import get_db
from app.models.streams import Stream
from app.schemas.stream import ScanPath
from app.services import rtsp_discovery

router = APIRouter(
    # E-K1 (backend): Scanner hanya super_admin, bukan admin biasa.
    tags=["admin-scan"], dependencies=[Depends(require_roles("super_admin"))]
)
log = logging.getLogger("netravision.admin_scan")

_MAX_HOSTS = 256
# Tahap 3: konkurensi 4 -> 12 (diukur: kamera palsu 2 path open butuh
# 12,7 dtk/host serial-ffprobe; discovery didominasi tunggu jaringan,
# ffprobe hanya membaca paket tanpa decode, jadi 12 host bersamaan
# (~24 proses ffprobe ringan) aman di server 8 core yang memang sudah
# menjalankan 49 transcode; tiap host tetap dibatasi 2 sesi ffprobe).
_HOST_CONCURRENCY = 12
_HOST_TIMEOUT = 30.0  # detik maksimum discovery per host (tahap 3)
# H1: batas waktu global seluruh scan, satu /24 tak boleh menggantung
# sampai puluhan menit walau tiap host dibatasi 30 detik.
_SCAN_GLOBAL_TIMEOUT = 300.0  # detik
# Funnel tahap 1-2: probe singkat + konkurensi tinggi supaya /24 penuh
# selesai dalam hitungan detik, bukan menit. Tahap 1: ping + 2 TCP
# fallback jalan bersamaan (IP mati ~1 dtk, bukan ~3 dtk berurutan).
_STAGE1_CONCURRENCY = 64
_STAGE2_CONCURRENCY = 32
_PING_TIMEOUT = 1.0  # detik per host (ICMP, satu echo)
_TCP_FALLBACK_TIMEOUT = 1.0  # detik per TCP connect fallback tahap 1
_PORT_TIMEOUT = 1.0  # detik TCP connect port RTSP (tahap 2, LAN: ms)
_FALLBACK_HTTP_PORT = 80  # UI web kamera, fallback kedua tahap 1


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
    # video | no_video | auth_failed | not_found | timeout | error |
    # unreachable (tahap 1 gagal: IP tak menjawab ping maupun TCP) |
    # port_closed (tahap 2 gagal: IP hidup tapi port RTSP tertutup)
    status: str
    best_main: str | None
    best_sub: str | None
    paths: list[ScanPath]
    # Kamera sudah terdaftar (aktif) di database pada IP:port ini.
    # Frontend menampilkan lencana "Sudah terdaftar" dan tidak
    # menawarkannya untuk ditambah lagi (cegah duplikat).
    known: bool = False


class SubnetScanJobCreated(BaseModel):
    job_id: str


class SubnetScanJobStatus(BaseModel):
    status: str  # running | done | error
    scanned: int
    total: int
    hosts: list[SubnetHost]
    candidates: list[SubnetCandidate]
    error: str | None = None
    # Progres funnel 3 tahap (field baru, default 0/"reachability"
    # supaya klien lama tetap bisa membaca respons ini).
    stage: str = "reachability"  # reachability | port_check | discovery | done
    reachable_count: int = 0  # host lolos tahap 1 (IP reachable)
    port_open_count: int = 0  # host lolos tahap 2 (port RTSP terbuka)


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
    stage: str = "reachability"  # reachability | port_check | discovery | done
    reachable_count: int = 0
    port_open_count: int = 0


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


def _dead_host(host: str, port: int, status: str, known: bool = False) -> SubnetHost:
    """Host yang tersaring funnel (tahap 1/2) atau kehabisan waktu:
    tetap muncul di hasil, tanpa paths dan tanpa discovery."""
    return SubnetHost(
        host=host, port=port, status=status,
        best_main=None, best_sub=None, paths=[], known=known,
    )


async def _ping_alive(host: str, timeout: float = _PING_TIMEOUT) -> bool:
    """Satu ICMP echo (ping -c 1). False bila tak menjawab, timeout,
    atau ping tak tersedia / tak diizinkan (mis. tanpa CAP_NET_RAW):
    pemanggil wajib lanjut ke fallback TCP, bukan membuang host."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(max(1, int(timeout))), host,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        return False
    except Exception:  # noqa: BLE001 - ping bukan penentu akhir
        return False
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=timeout + 0.5)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        await proc.wait()
        return False
    return rc == 0


async def _tcp_connect(host: str, port: int, timeout: float) -> bool:
    """TCP connect singkat. True bila ada yang menerima koneksi."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001 - connect gagal = port tertutup/mati
        return False


async def _host_reachable(host: str, port: int) -> bool:
    """Tahap 1: IP hidup? Ping + fallback TCP connect (port RTSP yang
    diminta, lalu port 80) jalan BERSAMAAN, bukan berurutan, dan
    berhenti begitu SATU probe berhasil (FIRST_COMPLETED): IP mati
    yang tadinya makan ~3 dtk (1+1+1) kini ~1 dtk (maks ketiganya),
    sementara IP hidup yang ping-nya menjawab tetap selesai dalam
    hitungan milidetik tanpa menunggu TCP. Kamera yang memblokir
    ICMP tetap lolos lewat TCP, jadi tahap ini tidak membuang kamera
    yang valid (hanya IP yang benar-benar diam di semua probe yang
    tersaring)."""
    probes = [
        asyncio.create_task(_ping_alive(host)),
        asyncio.create_task(
            _tcp_connect(host, port, _TCP_FALLBACK_TIMEOUT)),
    ]
    if port != _FALLBACK_HTTP_PORT:
        probes.append(asyncio.create_task(
            _tcp_connect(host, _FALLBACK_HTTP_PORT, _TCP_FALLBACK_TIMEOUT)))
    try:
        pending = set(probes)
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                try:
                    if t.result() is True:
                        return True
                except Exception:  # noqa: BLE001 - probe gagal = False
                    pass
        return False
    finally:
        for t in probes:
            if not t.done():
                t.cancel()


async def _port_open(host: str, port: int) -> bool:
    """Tahap 2: port RTSP terbuka? TCP connect singkat ke port yang
    diminta. Hanya dipanggil untuk host yang lolos tahap 1."""
    return await _tcp_connect(host, port, _PORT_TIMEOUT)


def _url_path(url: str | None) -> str | None:
    """Path (+ query) dari URL RTSP, mis. '/Streaming/Channels/101'
    atau '/cam/realmonitor?channel=1&subtype=0'. Dipakai untuk
    mencocokkan path kamera terdaftar dengan path kandidat scan
    (kredensial diabaikan, bisa berbeda dengan yang dimasukkan user)."""
    if not url:
        return None
    parts = urlparse(url)
    if not parts.path:
        return None
    return parts.path + (f"?{parts.query}" if parts.query else "")


async def _load_known_cameras(
    db: AsyncSession,
) -> tuple[set[tuple[str, int]], dict[tuple[str, int], tuple[str | None, str | None]]]:
    """Kamera terdaftar (aktif) -> dua peta ber kunci (host, port).

    known_hosts: semua kamera aktif (untuk lencana 'Sudah terdaftar').
    known_online: hanya yang sedang online + path main/sub yang dikenal
    (untuk jalur cepat discovery tanpa ffprobe). Satu query di awal
    job; bila baca DB gagal, scan tetap jalan tanpa jalur cepat
    (kedua peta kosong) dan bukan menggugurkan scan."""
    known_hosts: set[tuple[str, int]] = set()
    known_online: dict[tuple[str, int], tuple[str | None, str | None]] = {}
    try:
        rows = (
            await db.execute(
                select(
                    Stream.rtsp_url, Stream.main_url, Stream.sub_url,
                    Stream.is_online,
                ).where(Stream.is_active.is_(True))
            )
        ).all()
    except Exception as e:  # noqa: BLE001 - scan jalan tanpa jalur cepat
        log.warning("scan-subnet: gagal baca kamera terdaftar: %s", e)
        return known_hosts, known_online
    for rtsp_url, main_url, sub_url, is_online in rows:
        base = main_url or rtsp_url
        if not base:
            continue
        try:
            parts = urlparse(base)
            host = parts.hostname
            if not host:
                continue
            ipaddress.ip_address(host)  # hanya IP literal, bukan hostname
            port = parts.port or 554
        except ValueError:
            continue
        key = (host, port)
        known_hosts.add(key)
        if is_online:
            known_online[key] = (
                _url_path(main_url) or _url_path(rtsp_url),
                _url_path(sub_url),
            )
    return known_hosts, known_online


async def _scan_host(
    host: str,
    port: int,
    username: str,
    password: str,
    sem: asyncio.Semaphore,
    known: bool = False,
    known_paths: tuple[str | None, str | None] | None = None,
) -> SubnetHost:
    async with sem:
        try:
            disc = await asyncio.wait_for(
                rtsp_discovery.discover_host(
                    host, port, username or None, password or None,
                    known_paths=known_paths,
                ),
                timeout=_HOST_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return _dead_host(host, port, "timeout", known=known)
        except Exception as e:  # noqa: BLE001 - A-R6: satu host error tak
            # boleh menggugurkan seluruh scan; laporkan sebagai error.
            log.warning("scan host %s gagal: %s", host, e)
            return _dead_host(host, port, "error", known=known)
    paths = [
        ScanPath(
            path=p.path, url=p.url, status=p.status, codec=p.codec,
            width=p.width, height=p.height, fps=p.fps,
            gop_seconds=p.gop_seconds,
            # Peran main/sub sudah diklasifikasikan secara pintar di
            # rtsp_discovery (resolusi ffprobe + pola nama path).
            role=p.role,
        )
        for p in disc.paths
    ]
    return SubnetHost(
        host=host, port=port, status=_host_status(disc),
        best_main=disc.best_main, best_sub=disc.best_sub, paths=paths,
        known=known,
    )


async def _run_scan(
    job: _ScanJob,
    hosts: list[str],
    port: int,
    username: str,
    password: str,
    known_hosts: set[tuple[str, int]] | None = None,
    known_online: dict[tuple[str, int], tuple[str | None, str | None]] | None = None,
) -> None:
    """Jalankan pemindaian di background sebagai asyncio task.

    Funnel 3 tahap: (1) reachability cepat per host, (2) port RTSP
    hanya untuk yang lolos tahap 1, (3) discovery penuh hanya untuk
    yang lolos tahap 1 dan 2. Host yang gagal tahap 1/2 langsung
    dicatat (unreachable / port_closed) tanpa discovery penuh.
    Perbaikan H1 tetap berlaku: timeout global, batas host sudah
    ditegakkan di POST sebelum job dibuat, dan satu host error tidak
    menggugurkan scan (tiap task dijamin menghasilkan SubnetHost).
    Hasil parsial ditulis ke job selagi jalan supaya GET bisa
    menampilkan progres, termasuk hitungan tiap tahap funnel.
    known_hosts/known_online: peta kamera terdaftar dari POST
    (lencana 'Sudah terdaftar' + jalur cepat tanpa ffprobe)."""
    known_hosts = known_hosts or set()
    known_online = known_online or {}
    recorded: set[str] = set()

    async def record(result: SubnetHost) -> None:
        async with _jobs_lock:
            job.hosts.append(result)
            job.scanned += 1
        recorded.add(result.host)

    try:
        # ---- Tahap 1: IP reachable (cepat, konkurensi tinggi) ----
        sem1 = asyncio.Semaphore(_STAGE1_CONCURRENCY)

        async def check_reachable(h: str) -> tuple[str, bool]:
            async with sem1:
                return h, await _host_reachable(h, port)

        reachable: list[str] = []
        for h, ok in await asyncio.gather(
            *(check_reachable(h) for h in hosts)
        ):
            if ok:
                reachable.append(h)
            else:
                await record(_dead_host(
                    h, port, "unreachable", known=(h, port) in known_hosts,
                ))
        async with _jobs_lock:
            job.reachable_count = len(reachable)
            job.stage = "port_check"

        # ---- Tahap 2: port RTSP (hanya yang lolos tahap 1) ----
        sem2 = asyncio.Semaphore(_STAGE2_CONCURRENCY)

        async def check_port(h: str) -> tuple[str, bool]:
            async with sem2:
                return h, await _port_open(h, port)

        port_open: list[str] = []
        for h, ok in await asyncio.gather(
            *(check_port(h) for h in reachable)
        ):
            if ok:
                port_open.append(h)
            else:
                await record(_dead_host(
                    h, port, "port_closed", known=(h, port) in known_hosts,
                ))
        async with _jobs_lock:
            job.port_open_count = len(port_open)
            job.stage = "discovery"

        # ---- Tahap 3: discovery penuh (hanya yang lolos 1 dan 2) ----
        sem = asyncio.Semaphore(_HOST_CONCURRENCY)
        tasks = [
            asyncio.create_task(
                _scan_host(
                    h, port, username, password, sem,
                    known=(h, port) in known_hosts,
                    known_paths=known_online.get((h, port)),
                )
            )
            for h in port_open
        ]
        # Sisa anggaran global: tahap 1-2 sudah memakai sebagian.
        remaining = _SCAN_GLOBAL_TIMEOUT - (
            time.monotonic() - job.created_at
        )
        try:
            async def _collect() -> None:
                for coro in asyncio.as_completed(tasks):
                    await record(await coro)

            await asyncio.wait_for(_collect(), timeout=max(1.0, remaining))
        except asyncio.TimeoutError:
            # H1: timeout global, kembalikan hasil parsial, sisanya timeout.
            for h, t in zip(port_open, tasks):
                if not t.done():
                    t.cancel()
                    await record(_dead_host(
                        h, port, "timeout", known=(h, port) in known_hosts,
                    ))
            await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 - pengaman terakhir job
        log.warning("scan-subnet job %s gagal: %s", job.job_id, e)
        async with _jobs_lock:
            job.status = "error"
            job.error = str(e) or "Scan gagal"
            job.finished_at = time.monotonic()
        return
    async with _jobs_lock:
        # Urutkan hasil mengikuti urutan subnet, bukan urutan selesai.
        order = {h: i for i, h in enumerate(hosts)}
        job.hosts.sort(key=lambda h: order.get(h.host, 0))
        # A-R6: host unreachable / port_closed tetap dikembalikan API
        # (bukan disaring) supaya hitungan funnel benar; frontend yang
        # menyembunyikan baris 'unreachable' dari tampilan.
        # Candidates hanya host yang punya video.
        job.candidates = [
            SubnetCandidate(
                host=h.host, port=h.port, brand="auto",
                main_url=h.best_main or "", sub_url=h.best_sub,
            )
            for h in job.hosts
            if h.best_main
        ]
        job.stage = "done"
        job.status = "done"
        job.finished_at = time.monotonic()
    log.info(
        "scan-subnet job %s: %d/%d reachable, %d/%d port RTSP terbuka, "
        "%d dengan video",
        job.job_id, job.reachable_count, job.total,
        job.port_open_count, job.reachable_count, len(job.candidates),
    )


@router.post(
    "/admin/scan-subnet",
    response_model=SubnetScanJobCreated,
    status_code=202,
    dependencies=[Depends(rate_limited(10, 60))],
)
async def scan_subnet(data: SubnetScanRequest, db: AsyncSession = Depends(get_db)):
    """Terima subnet CIDR, langsung kembalikan 202 + job_id, dan mulai
    pemindaian di background. Validasi CIDR dan batas 256 host tetap di
    sini, sebelum job dibuat. Hasil diambil via GET job status.
    Kamera terdaftar dibaca sekali di sini (sesi DB masih hidup) dan
    diteruskan sebagai data polos ke background task."""
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
    # Kamera terdaftar: lencana 'Sudah terdaftar' + jalur cepat
    # discovery (tanpa ffprobe untuk yang sedang online).
    known_hosts, known_online = await _load_known_cameras(db)
    async with _jobs_lock:
        _prune_jobs_locked()
        _jobs[job.job_id] = job
    asyncio.create_task(
        _run_scan(
            job, hosts, data.port, data.username, data.password,
            known_hosts, known_online,
        )
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
    berisi hasil parsial sejauh ini (boleh kosong); stage,
    reachable_count dan port_open_count menunjukkan progres funnel."""
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
            stage=job.stage,
            reachable_count=job.reachable_count,
            port_open_count=job.port_open_count,
        )
