"""Discovery path RTSP: cari path yang benar-benar mengirim video.

Tahap 1 (cepat, paralel): DESCRIBE per path kandidat umum + template brand
(auth Basic/Digest via probe_rtsp). Host tak bisa TCP connect -> berhenti.
Tahap 2 (verifikasi, paralel 2 per host, dibatasi 8 path open pertama):
ffprobe baca frame video nyata dari path yang DESCRIBE-nya OK. Jalur
cepat: kamera yang sudah terdaftar + sedang online di database
dilewati ffprobe-nya bila path main yang dikenal terbuka di DESCRIBE.

Status per path: video | no_video | auth_failed | not_found | timeout | error.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from app.services.stream_resolver import probe_rtsp

FFPROBE = "ffprobe"
_PROBE_TIMEOUT = 3.0
_FFPROBE_TIMEOUT = 15.0  # read window 6 dtk + sambung; 10 dtk sempit di kamera lambat
# Kecepatan scan (2026-11-13): jendela baca ffprobe 6 -> 3 dtk (cukup
# untuk memastikan ada video + codec/resolusi/fps; gop_seconds memang
# sudah None lewat demuxer concat, jadi tidak ada yang hilang), dan
# ffprobe dijalankan PARALEL 2 per host, bukan serial (terukur: kamera
# palsu 2 path open 12,7 dtk serial -> ~6,5 dtk paralel; jendela 6 dtk
# butuh 6,4 dtk/path, jendela 3 dtk 5,5 dtk/path).
_FFPROBE_READ_SECONDS = 3.0
_SEM_PROBES = 8
_SEM_FFPROBE = 2  # sesi RTSP paralel per host (DESCRIBE saja sudah 8)
# Batas path open yang diverifikasi per host (urutan kandidat =
# paling mungkin dulu). Tanpa batas, kamera yang menjawab 200 untuk
# SEMUA path membuat 38 ffprobe serial (~4 menit) lalu host timeout
# 45 dtk tanpa hasil apa pun. Dengan batas ini, kasus terburuk
# 8 path x ~5,5 dtk / 2 paralel = ~22 dtk, masih di bawah budget host.
# Main/sub hampir selalu di 8 pertama (Hikvision 101/102, Dahua
# subtype 0/1, unicast s0/s1, stream1/2); bila hanya sedikit path
# yang open, batas ini tidak memotong apa pun.
_MAX_VERIFY_PATHS = 8
_HOST_BUDGET = 45.0  # detik maksimum seluruh discovery per host

# Path umum vendor besar + generik (dedupe di candidate_paths).
_COMMON_PATHS: tuple[str, ...] = (
    "/Streaming/Channels/101",
    "/Streaming/Channels/102",
    "/cam/realmonitor?channel=1&subtype=0",
    "/cam/realmonitor?channel=1&subtype=1",
    "/unicast/c1/s0/live",
    "/unicast/c1/s1/live",
    "/stream1",
    "/stream2",
    "/h264Preview_01_main",
    "/h264Preview_01_sub",
    "/H.264",
    "/H.264_sub",
    "/H.265",
    "/h264",
    "/live",
    "/live/ch00_0",
    "/live/ch00_1",
    "/ch01.264",
    "/11",
    "/12",
    "/onvif1",
    "/media/video1",
    "/av0_0",
    "/av0_1",
    "/0",
    "/1",
    "/video1",
    "/live.sdp",
)


def candidate_paths(channel: int = 1) -> list[str]:
    """Path kandidat (umum + template brand), dedupe, urutan stabil."""
    from app.services.brands import BRAND_PROFILES

    out: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        if p and p not in seen:
            seen.add(p)
            out.append(p)

    for p in _COMMON_PATHS:
        add(p)
    for prof in BRAND_PROFILES.values():
        for key in ("main", "sub"):
            tpl = prof.get(key)
            if not tpl:
                continue
            url = str(tpl).format(
                user="u", password="p", host="h", port=554, channel=channel
            )
            parts = urlparse(url)
            add(parts.path + (f"?{parts.query}" if parts.query else ""))
    return out


def build_url(host: str, port: int, user: str | None,
              password: str | None, path: str) -> str:
    auth = ""
    if user:
        auth = quote(user, safe="") + ":" + quote(password or "", safe="") + "@"
    return f"rtsp://{auth}{host}:{port}{path}"


@dataclass
class VideoProbe:
    status: str  # video | no_video | auth_failed | not_found | timeout | error
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    gop_seconds: float | None = None


@dataclass
class PathResult:
    path: str
    url: str
    status: str  # video | no_video | auth_failed | not_found | timeout | error
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    gop_seconds: float | None = None


@dataclass
class DiscoveryResult:
    host: str
    port: int
    reachable: bool
    paths: list[PathResult]
    best_main: str | None = None
    best_sub: str | None = None

    def ringkasan(self) -> str:
        if not self.reachable:
            return "host tidak terjangkau"
        if not self.paths:
            return "tidak ada path yang dicoba"
        counts: dict[str, int] = {}
        for p in self.paths:
            counts[p.status] = counts.get(p.status, 0) + 1
        return ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))


def _parse_rate(value: str | None) -> float | None:
    if not value or "/" not in value:
        return None
    num, den = value.split("/", 1)
    try:
        n, d = float(num), float(den)
    except ValueError:
        return None
    return round(n / d, 2) if d else None


def parse_ffprobe_output(text: str) -> VideoProbe:
    """Hasil ffprobe JSON (stream + packet) -> VideoProbe.

    Pakai packet (bukan frame): tak perlu decode, dan tidak false-negative
    saat ffprobe bergabung di tengah GOP panjang.
    """
    data = json.loads(text)
    streams = data.get("streams") or []
    packets = data.get("packets") or []
    if not streams or not packets:
        return VideoProbe(status="no_video")
    s = streams[0]
    key_pts = sorted(
        float(p["pts_time"]) for p in packets
        if "K" in (p.get("flags") or "")
        and p.get("pts_time") not in (None, "N/A")
    )
    gop = (
        round((key_pts[-1] - key_pts[0]) / (len(key_pts) - 1), 2)
        if len(key_pts) > 1 else None
    )
    return VideoProbe(
        status="video",
        codec=s.get("codec_name"),
        width=s.get("width"),
        height=s.get("height"),
        # HEVC sering avg_frame_rate "0/0" -> pakai r_frame_rate.
        fps=_parse_rate(s.get("avg_frame_rate")) or _parse_rate(s.get("r_frame_rate")),
        gop_seconds=gop,
    )


async def _run_ffprobe(url: str, timeout: float = _FFPROBE_TIMEOUT) -> VideoProbe:
    """Jalankan ffprobe singkat (3 dtk baca) ke satu URL RTSP.

    M3: URL RTSP lengkap (berisi kredensial kamera) TIDAK PERNAH dilewatkan
    sebagai argv ffprobe, argv terlihat di `ps` oleh semua user di server
    (diverifikasi: wrapper env-var saja TIDAK cukup, karena ffprobe hasil
    exec tetap menampilkan URL di argv-nya). Sebagai gantinya URL ditulis ke
    file concat sementara (0600, dihapus di finally) dan ffprobe membacanya
    lewat demuxer concat; argv hanya berisi path file temp itu. stderr
    ffprobe tidak pernah di-log (pesan error concat bisa memuat URL).
    Terverifikasi terhadap MediaMTX lokal: status video, codec, resolusi,
    dan fps sama seperti pemanggilan langsung. Batasan yang diketahui:
    flag keyframe tidak diteruskan demuxer concat sehingga gop_seconds
    menjadi None, dan negosiasi transport bisa jatuh dulu ke UDP sebelum
    TCP (dibatasi timeout yang sama).
    """
    fd, list_path = tempfile.mkstemp(prefix="ffprobe-", suffix=".txt")
    try:
        safe_url = url.replace("'", "'\\''")
        with os.fdopen(fd, "w") as f:
            f.write(f"file '{safe_url}'\n")
        cmd = [
            FFPROBE, "-rtsp_transport", "tcp", "-v", "error",
            "-protocol_whitelist", "file,rtsp,tcp,udp,rtp,crypto",
            "-select_streams", "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,r_frame_rate:packet=pts_time,flags",
            "-read_intervals", f"%+{int(_FFPROBE_READ_SECONDS)}", "-of", "json",
            "-f", "concat", "-safe", "0", "-i", list_path,
        ]
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            return VideoProbe(status="timeout")
        except (FileNotFoundError, OSError):
            return VideoProbe(status="error")
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass
    text = out.decode("utf-8", "replace")
    if proc.returncode != 0 or not text.strip():
        stderr = err.decode("utf-8", "replace").lower()
        if "401" in stderr or "unauthorized" in stderr:
            return VideoProbe(status="auth_failed")
        return VideoProbe(status="no_video")
    try:
        return parse_ffprobe_output(text)
    except Exception:  # noqa: BLE001
        return VideoProbe(status="no_video")


async def probe_path(url: str, timeout: float = _PROBE_TIMEOUT) -> str:
    """DESCRIBE singkat. 'open' = path ada & auth OK (video belum tentu ada)."""
    r = await probe_rtsp(url, timeout=timeout)
    if r.status == "ok":
        return "open"
    if r.status in ("auth_failed", "auth_required"):
        return "auth_failed"
    if r.status == "not_found":
        return "not_found"
    if r.status == "timeout":
        return "timeout"
    return "error"


async def verify_url(url: str) -> VideoProbe:
    """Verifikasi satu URL RTSP: DESCRIBE lalu ffprobe (video / no_video / ...)."""
    st = await probe_path(url)
    if st != "open":
        return VideoProbe(status=st if st in ("auth_failed", "not_found", "timeout") else "error")
    return await _run_ffprobe(url)


async def _tcp_alive(host: str, port: int) -> bool:
    try:
        _r, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=2.0
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


def select_main_sub(paths: list[PathResult]) -> tuple[str | None, str | None]:
    """main = video resolusi terbesar; sub = video resolusi terkecil != main."""
    vids = [p for p in paths if p.status == "video"]
    if not vids:
        return None, None

    def area(p: PathResult) -> int:
        return (p.width or 0) * (p.height or 0)

    # max/min mengambil yang PERTAMA bila seri -> urutan kandidat (template
    # brand dulu) menang. Banyak kamera menjawab path apa pun dengan stream
    # yang sama: sub hanya sah bila resolusinya benar-benar lebih kecil.
    main = max(vids, key=lambda p: (area(p), p.fps or 0.0))
    subs = [p for p in vids if area(p) < area(main)]
    sub = min(subs, key=lambda p: (area(p), -(p.fps or 0.0))) if subs else None
    return main.url, (sub.url if sub else None)


async def discover_host(
    host: str,
    port: int = 554,
    user: str | None = None,
    password: str | None = None,
    channel: int = 1,
    known_paths: tuple[str | None, str | None] | None = None,
) -> DiscoveryResult:
    """Coba semua path kandidat, verifikasi video, pilih main/sub otomatis.

    known_paths = (main_path, sub_path) kamera yang SUDAH terdaftar
    dan sedang online di database (mis. "/Streaming/Channels/101",
    "/Streaming/Channels/102"). Bila path main yang dikenal terbuka
    di DESCRIBE, video dianggap terverifikasi tanpa ffprobe (jalur
    cepat): kamera itu sudah terbukti mengirim video dan status
    online-nya dipantau terpisah. Bila tidak ada path dikenal yang
    terbuka, discovery penuh seperti biasa."""
    try:
        return await asyncio.wait_for(
            _discover(host, port, user, password, channel, known_paths),
            timeout=_HOST_BUDGET,
        )
    except asyncio.TimeoutError:
        return DiscoveryResult(host=host, port=port, reachable=True, paths=[])


async def _discover(
    host: str, port: int, user: str | None, password: str | None, channel: int,
    known_paths: tuple[str | None, str | None] | None = None,
) -> DiscoveryResult:
    if not await _tcp_alive(host, port):
        return DiscoveryResult(host=host, port=port, reachable=False, paths=[])

    cands = [
        (p, build_url(host, port, user, password, p))
        for p in candidate_paths(channel)
    ]
    sem = asyncio.Semaphore(_SEM_PROBES)

    async def probe_one(path: str, url: str) -> PathResult:
        async with sem:
            st = await probe_path(url)
        return PathResult(path=path, url=url, status=st)

    probed = list(await asyncio.gather(*(probe_one(p, u) for p, u in cands)))

    # Jalur cepat kamera dikenal: path main yang terdaftar terbuka di
    # DESCRIBE -> video terverifikasi tanpa ffprobe (hemat ~6-13 dtk
    # per kamera yang sudah terdaftar). Path sub yang dikenal ikut
    # ditandai bila terbuka. Path open lain yang tak dikenal tidak
    # diverifikasi di jalur ini (tidak ditebak statusnya).
    if known_paths and known_paths[0]:
        by_path = {pr.path: pr for pr in probed if pr.status == "open"}
        known_main = by_path.get(known_paths[0])
        if known_main is not None:
            known_main.status = "video"
            known_sub = None
            if known_paths[1]:
                known_sub = by_path.get(known_paths[1])
                if known_sub is not None:
                    known_sub.status = "video"
            kept = [pr for pr in probed if pr.status != "open"]
            return DiscoveryResult(
                host=host, port=port, reachable=True, paths=kept,
                best_main=known_main.url,
                best_sub=known_sub.url if known_sub is not None else None,
            )

    # Tahap 2: ffprobe PARALEL (maks 2 per host) dan DIBATASI
    # (_MAX_VERIFY_PATHS path open pertama, urutan kandidat). Serial
    # + tanpa batas adalah bottleneck tahap 3: 2 path open saja sudah
    # ~13 dtk, kamera yang menjawab 200 untuk semua path timeout
    # tanpa hasil. Paralel 2 aman: DESCRIBE saja sudah membuka 8
    # koneksi bersamaan ke kamera yang sama.
    open_paths = [pr for pr in probed if pr.status == "open"]
    to_verify = open_paths[:_MAX_VERIFY_PATHS]
    sem_v = asyncio.Semaphore(_SEM_FFPROBE)

    async def verify_one(pr: PathResult) -> None:
        async with sem_v:
            vp = await _run_ffprobe(pr.url)
        pr.status = "video" if vp.status == "video" else vp.status
        pr.codec, pr.width, pr.height = vp.codec, vp.width, vp.height
        pr.fps, pr.gop_seconds = vp.fps, vp.gop_seconds

    await asyncio.gather(*(verify_one(pr) for pr in to_verify))

    best_main, best_sub = select_main_sub(probed)
    return DiscoveryResult(
        host=host, port=port, reachable=True, paths=probed,
        best_main=best_main, best_sub=best_sub,
    )
