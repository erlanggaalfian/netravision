"""Discovery path RTSP: cari path yang benar-benar mengirim video.

Tahap 1 (cepat, paralel): DESCRIBE per path kandidat umum + template brand
(auth Basic/Digest via probe_rtsp). Host tak bisa TCP connect -> berhenti.
Tahap 2 (verifikasi, paralel 2 per host, dibatasi 8 path open pertama):
ffprobe baca frame video nyata dari path yang DESCRIBE-nya OK. Jalur
cepat: kamera yang sudah terdaftar + sedang online di database
dilewati ffprobe-nya bila path main yang dikenal terbuka di DESCRIBE.

Klasifikasi main/sub PINTAR (perintah user 2026-11-13 19:19 WIB):
resolusi ffprobe adalah sinyal terkuat (terbesar = main, lebih kecil
= sub); bila beberapa path beresolusi sama (kamera menjawab path apa
pun dengan stream yang sama), nama path dipakai sebagai tiebreaker
(pola umum lintas merek: 101/102, subtype=0/1, stream1/2, s0/s1,
main/sub, ch00_0/1, av0_0/1, /0 vs /1, /11 vs /12). Path terpilih
ditandai role 'main'/'sub' di PathResult supaya API + UI bisa
menampilkan keduanya dengan jelas.

Daftar path kandidat (riset web 2026-11-13, report.md): ~55 merek +
pola generik/ONVIF, total ~125 path (lihat _COMMON_PATHS +
BRAND_PROFILES). Bila sumber berkonflik, SEMUA varian dimasukkan
sebagai kandidat. Port non-554 (Foscam 88, GeoVision 8554, ACTi
7070, Zmodo/V380 10554, Hiseeu 80, UniFi Protect 7441/7447,
CamHi 5544) TIDAK dipindai otomatis — scanner memakai port yang
dimasukkan user (default 554); merek tanpa RTSP native (Ring,
Google Nest) dan UniFi Protect (token rtsps, bukan path tetap)
sengaja tidak didukung. DESCRIBE semua path murah (~0,01 dtk
untuk 38 path), jadi penambahan path tidak melambatkan scan;
verifikasi ffprobe tetap dibatasi 8 path open pertama.

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
# Main/sub hampir selalu di 8 pertama (/live/0/MAIN+SUB, Hikvision
# 101/102, Dahua subtype 0/1, unicast s0/s1); bila hanya sedikit path
# yang open, batas ini tidak memotong apa pun.
_MAX_VERIFY_PATHS = 8
_HOST_BUDGET = 45.0  # detik maksimum seluruh discovery per host
# Jeda coba ulang bila semua path gagal auth (kemungkinan kunci
# sementara anti-brute-force kamera, BUKAN password salah).
# Dipakai _discover; tes boleh monkeypatch ke nilai kecil supaya
# suite tetap cepat.
_AUTH_RETRY_DELAY = 12.0

# Path umum vendor besar + generik (dedupe di candidate_paths).
# Daftar ini + template BRAND_PROFILES = seluruh kandidat yang
# di-DESCRIBE per host. Sumber: riset web 2026-11-13 (report.md,
# ~55 merek + pola generik/ONVIF). Urutan (perintah user 2026-11-13
# 20:04): /live/0/MAIN dan /live/0/SUB PALING AWAL, lalu merek
# mainstream dulu (Hikvision, Dahua, Uniview, TP-Link VIGI/Tapo +
# stream1/2, Reolink), lalu pola generik paling umum, baru merek
# lain. Urutan ini penting karena _discover berhenti dini begitu
# main+sub terverifikasi: kamera mainstream ketemu di gelombang 1-2,
# jadi burst login per kamera tinggal ~8-16 percobaan, bukan 126
# path x 2 login yang memicu kunci anti-brute-force kamera
# ('Login salah' palsu). JANGAN hapus path, hanya ubah urutan.
# Bila sumber berkonflik, SEMUA varian dimasukkan (mis. Ezviz
# /h264/ch01/... vs /ch1/main vs /h264_stream; Hanwha profile1/2
# vs profile2/3; Vivotek /live2.sdp vs /live1s.sdp).
_COMMON_PATHS: tuple[str, ...] = (
    # 1-2: pola /live/0/MAIN + /live/0/SUB (paling awal).
    "/live/0/MAIN",
    "/live/0/SUB",
    # 3-4: Hikvision.
    "/Streaming/Channels/101",
    "/Streaming/Channels/102",
    # 5-6: Dahua.
    "/cam/realmonitor?channel=1&subtype=0",
    "/cam/realmonitor?channel=1&subtype=1",
    # 7-10: Uniview (unicast NVR + media IPC).
    "/unicast/c1/s0/live",
    "/unicast/c1/s1/live",
    "/media/video1",
    "/media/video2",
    # 11-12: TP-Link VIGI/Tapo + pola generik stream1/2.
    "/stream1",
    "/stream2",
    # 13-14: Reolink.
    "/h264Preview_01_main",
    "/h264Preview_01_sub",
    # Pola generik paling umum.
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
    "/onvif2",
    "/av0_0",
    "/av0_1",
    "/0",
    "/1",
    "/video1",
    "/live.sdp",
    # --- Tambahan riset 2026-11-13 (report.md) ---
    # Bentuk lama/varian konflik: Hikvision lama, Ezviz (OmniNVR),
    # Annke lama, Reolink tanpa prefix h264.
    "/h264/ch1/main/av_stream",
    "/h264/ch1/sub/av_stream",
    "/H264/ch1/main/av_stream",
    "/H264/ch1/sub/av_stream",
    "/ch1/main",
    "/ch1/sub",
    "/h264_stream",
    "/Preview_01_main",
    "/Preview_01_sub",
    # Hanwha: profil ketiga + bentuk NVR/ONVIF (konflik penomoran
    # profil: SmartRTSP profile1=main/profile2=sub, OmniNVR
    # profile2=main/profile3=sub — semua dimasukkan).
    "/profile3/media.smp",
    "/onvif/profile2/media.smp",
    "/LiveChannel/0/media.smp",
    # Panasonic: bentuk dasar + mpeg4.
    "/MediaInput/h264",
    "/MediaInput/mpeg4",
    # Vivotek alt sub, Tiandy (ch/stream), Infinova PTZ.
    "/live1s.sdp",
    "/1/1",
    "/1/2",
    "/1/1080p",
    "/1/D1",
    # Tapo dual-lens, Milesight (third + dual-sensor +
    # multi-directional), FLIR alt.
    "/stream6",
    "/stream7",
    "/third",
    "/channel1/main",
    "/channel1/sub",
    "/sensor1/main",
    "/sensor1/sub",
    "/ch0",
    "/vis",
    # Bosch alt, Axis alt (bentuk dasar axis-media tanpa query).
    "/rtsp_tunnel",
    "/rtsp_tunnel?p=0&h26x=4",
    "/video?inst=1",
    "/axis-media/media.amp",
    "/mpeg4/media.amp",
    "/onvif-media/media.amp?profile=profile_1_h264",
    # Huawei NVR, Honeywell alt, ACTi ONVIF, Hiseeu alt, Swann
    # standalone, Pelco stream ketiga, Uniview stream ketiga.
    "/rtsp/streaming?channel=1&subtype=0",
    "/rtsp/streaming?channel=1&subtype=1",
    "/channel=1_stream=0.sdp?real_stream",
    "/onvif-stream1",
    "/onvif&event&video1",
    "/live/ch0",
    "/live/h264",
    "/h264_3",
    "/media/video3",
    # Bare (tanpa path): alt model lama ACTi, Tiandy, Avigilon.
    # Paling akhir supaya tidak merebut slot verifikasi dari path
    # yang lebih spesifik.
    "/",
)


# Urutan brand saat mengambil template dari BRAND_PROFILES di
# candidate_paths (perintah user 2026-11-13 20:04): mainstream dulu
# (Hikvision, Dahua, Uniview, Reolink, TP-Link, Foscam, Ezviz, ...),
# baru merek lain. Brand yang tidak ada di daftar ini tetap
# disertakan setelahnya sesuai urutan dict (jaga-jaga bila ada
# profil baru yang belum didaftarkan).
_BRAND_ORDER = (
    "hikvision", "dahua", "uniview_ipc", "uniview_nvr", "reolink",
    "tplink_vigi", "foscam", "ezviz", "milesight", "hanwha", "axis",
    "panasonic", "vivotek", "pelco", "bosch", "avigilon", "arecont",
    "provision_isr", "tvt", "hiseeu", "zosi", "swann", "geovision",
    "huawei", "dlink", "digital_watchdog", "zmodo", "kedacom",
    "infinova", "raysharp", "canon", "lg", "jvs", "xiaomi", "eufy",
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
    # Template brand diambil mainstream dulu; brand yang tidak ada
    # di _BRAND_ORDER tetap disertakan setelahnya (urutan dict).
    ordered = [k for k in _BRAND_ORDER if k in BRAND_PROFILES]
    ordered += [k for k in BRAND_PROFILES if k not in _BRAND_ORDER]
    for brand in ordered:
        prof = BRAND_PROFILES[brand]
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
    # Peran stream bila path ini terpilih: 'main' | 'sub' | None.
    # Diisi select_main_sub (atau jalur cepat kamera dikenal); hanya
    # path video yang bisa punya peran.
    role: str | None = None


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


def _path_segments(path: str) -> list[str]:
    """Segmen path (tanpa query), mis. '/Streaming/Channels/101' ->
    ['streaming', 'channels', '101']. Dipakai supaya angka seperti
    '101' hanya cocok sebagai segmen utuh, bukan di dalam '1101'
    atau 'ch01'."""
    base = path.split("?", 1)[0]
    return [s for s in base.lower().split("/") if s]


def classify_path_name(path: str) -> str | None:
    """Petunjuk main/sub dari NAMA path saja (tanpa info video).

    Pola umum lintas merek (riset web 2026-11-13, report.md):
      main: subtype=0, inst=1 (Bosch), segmen 101, /Streaming/Channels/1
        (Digital Watchdog), profile1, 'main', stream1, stream_1,
        defaultPrimary (Avigilon), Master (LG), Media1 (Huawei),
        h264major (Infinova), 1080p, s0, ch00_0, av0_0, ch0_0,
        live0, segmen /N/1 (Tiandy /1/1), segmen 0, segmen 11
      sub:  subtype=1, inst=2 (Bosch), segmen 102, profile2, profile3,
        profile1=r (Canon), 'sub', stream2, stream_2, h264_2 (Pelco),
        defaultSecondary (Avigilon), Slave (LG), Media2 (Huawei),
        h264minor (Infinova), D1, s1, ch00_1, av0_1, ch0_1,
        live1, segmen /N/2 (Tiandy /1/2), segmen 1, segmen 12
    Kembalikan 'main' | 'sub' | None (tanpa petunjuk, mis. '/live',
    '/H.264', '/media/video1'). Urutan penting: 'subtype=0' dicek
    sebelum 'sub' generik karena keduanya mengandung kata 'sub';
    'profile1=r' dicek sebelum 'profile1'; pola spesifik (inst,
    profile, h264major/minor, 1080p/D1) dicek sebelum segmen generik
    '0'/'1' supaya tidak salah (mis. /1/h264major adalah main,
    bukan sub karena segmen '1').
    """
    p = path.lower()
    if "subtype=0" in p:
        return "main"
    if "subtype=1" in p:
        return "sub"
    if "inst=1" in p:
        return "main"
    if "inst=2" in p:
        return "sub"
    segs = _path_segments(p)
    if "101" in segs:
        return "main"
    if "102" in segs:
        return "sub"
    if p == "/streaming/channels/1":
        return "main"
    if "profile1=r" in p:
        return "sub"
    if "profile1" in p:
        return "main"
    if "profile2" in p or "profile3" in p:
        return "sub"
    if "main" in p:
        return "main"
    if "sub" in p:
        return "sub"
    if "stream1" in p:
        return "main"
    if "stream2" in p:
        return "sub"
    if "stream_1" in p:
        return "main"
    if "stream_2" in p:
        return "sub"
    if "h264_2" in p:
        return "sub"
    if "defaultprimary" in p:
        return "main"
    if "defaultsecondary" in p:
        return "sub"
    if "master" in p:
        return "main"
    if "slave" in p:
        return "sub"
    if "media1" in segs:
        return "main"
    if "media2" in segs:
        return "sub"
    if "h264major" in p:
        return "main"
    if "h264minor" in p:
        return "sub"
    if "1080p" in segs:
        return "main"
    if "d1" in segs:
        return "sub"
    if "s0" in segs or "ch00_0" in p or "av0_0" in p or "ch0_0" in p:
        return "main"
    if "s1" in segs or "ch00_1" in p or "av0_1" in p or "ch0_1" in p:
        return "sub"
    if "live0" in p:
        return "main"
    if "live1" in p:
        return "sub"
    # Tiandy /{channel}/{stream}: segmen pertama angka (channel),
    # segmen kedua 1=main, 2=sub. Dicek sebelum segmen generik '0'/'1'
    # (kalau tidak, /1/1 akan salah jadi sub). Bentuk /ch01/0 dan
    # /ch01/1 (Swann) tidak kena aturan ini karena segmen pertamanya
    # 'ch01', bukan angka murni.
    if len(segs) == 2 and segs[0].isdigit() and segs[1] in ("1", "2"):
        return "main" if segs[1] == "1" else "sub"
    if "0" in segs:
        return "main"
    if "1" in segs:
        return "sub"
    if "11" in segs:
        return "main"
    if "12" in segs:
        return "sub"
    return None


def select_main_sub(paths: list[PathResult]) -> tuple[str | None, str | None]:
    """main = video resolusi terbesar; sub = video resolusi terkecil
    yang benar-benar lebih kecil (atau, bila semua resolusi sama,
    path yang namanya menandai sub).

    Sinyal (terkuat dulu): (1) resolusi ffprobe — main selalu yang
    terbesar, sub yang lebih kecil; (2) nama path — tiebreaker saat
    resolusi seri (kamera menjawab banyak path dengan stream yang
    sama: /stream1 vs /stream2, 101 vs 102, subtype=0 vs 1) dan
    untuk memilih sub terkecil saat ada beberapa kandidat;
    (3) fps, lalu urutan kandidat. Juga menandai role ('main'/'sub')
    pada PathResult yang terpilih supaya pemanggil (API) bisa
    menampilkan keduanya. Tanpa sub bila hanya satu video, atau bila
    semua resolusi sama dan tidak ada nama yang menandai sub (tanpa
    sub palsu beresolusi sama)."""
    vids = [p for p in paths if p.status == "video"]
    if not vids:
        return None, None

    def area(p: PathResult) -> int:
        return (p.width or 0) * (p.height or 0)

    # max/min mengambil yang PERTAMA bila seri -> urutan kandidat
    # (template brand dulu) menang bila area dan petunjuk nama seri.
    main = max(vids, key=lambda p: (
        area(p),
        1 if classify_path_name(p.path) == "main" else 0,
        p.fps or 0.0,
    ))
    main.role = "main"
    smaller = [p for p in vids if p is not main and area(p) < area(main)]
    sub: PathResult | None = None
    if smaller:
        # Path yang namanya menandai sub DIDAHULUKAN atas yang
        # resolusinya lebih kecil: kamera bisa punya stream KETIGA
        # (/third, /media/video3, /h264_3, /profile3/media.smp)
        # yang resolusinya lebih kecil dari sub — tanpa ini, stream
        # ketiga yang paling kecil akan salah terpilih jadi sub.
        # Bila tidak ada yang bernama sub, jatuh ke resolusi terkecil
        # (perilaku lama).
        sub = min(smaller, key=lambda p: (
            0 if classify_path_name(p.path) == "sub" else 1,
            area(p),
            -(p.fps or 0.0),
        ))
    else:
        # Semua resolusi sama: sub hanya sah bila namanya menandai
        # sub (tanpa ini, kamera yang menjawab semua path dengan
        # stream sama akan dapat sub palsu).
        named = [
            p for p in vids
            if p is not main and classify_path_name(p.path) == "sub"
        ]
        sub = named[0] if named else None
    if sub is not None:
        sub.role = "sub"
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
    _allow_auth_retry: bool = True,
) -> DiscoveryResult:
    if not await _tcp_alive(host, port):
        return DiscoveryResult(host=host, port=port, reachable=False, paths=[])

    cands = [
        (p, build_url(host, port, user, password, p))
        for p in candidate_paths(channel)
    ]
    sem = asyncio.Semaphore(_SEM_PROBES)
    sem_v = asyncio.Semaphore(_SEM_FFPROBE)

    async def probe_one(path: str, url: str) -> PathResult:
        async with sem:
            st = await probe_path(url)
        return PathResult(path=path, url=url, status=st)

    async def verify_one(pr: PathResult) -> None:
        async with sem_v:
            vp = await _run_ffprobe(pr.url)
        pr.status = "video" if vp.status == "video" else vp.status
        pr.codec, pr.width, pr.height = vp.codec, vp.width, vp.height
        pr.fps, pr.gop_seconds = vp.fps, vp.gop_seconds

    # Probe per GELOMBANG (ukuran = _SEM_PROBES, urutan kandidat
    # mainstream dulu). Setelah tiap gelombang: (1) jalur cepat bila
    # path main dikenal terbuka, (2) ffprobe path open yang baru
    # (dibatasi _MAX_VERIFY_PATHS total), (3) BERHENTI DINI bila
    # main+sub sudah terverifikasi video. Ini yang memangkas burst
    # login: kamera mainstream ketemu di gelombang 1-2 (~8-16
    # percobaan login), bukan 126 path x 2 login (~250) yang memicu
    # kunci anti-brute-force kamera ('Login salah' palsu). Urutan
    # kandidat mainstream dulu memastikan pasangan yang ketemu duluan
    # hampir selalu yang terbaik; resolusi ffprobe tetap penentu
    # utama main/sub (select_main_sub), jadi berhenti dini tidak
    # merusak pemilihan. _SEM_PROBES tetap 8: yang memicu kunci
    # adalah TOTAL percobaan, bukan 8 koneksi bersamaan (DESCRIBE
    # singkat, bukan sesi media), dan 8 menjaga kecepatan DESCRIBE
    # + perilaku ffprobe paralel yang sudah terverifikasi.
    probed: list[PathResult] = []
    verified_count = 0  # jumlah path open yang sudah di-ffprobe
    saw_open = False  # ada DESCRIBE yang lolos auth (200)
    idx = 0
    while idx < len(cands):
        wave = cands[idx:idx + _SEM_PROBES]
        idx += len(wave)
        results = await asyncio.gather(*(probe_one(p, u) for p, u in wave))
        probed.extend(results)
        # Catat SEBELUM ffprobe mengubah status open -> video/no_video.
        if any(pr.status == "open" for pr in results):
            saw_open = True

        # Jalur cepat kamera dikenal: path main yang terdaftar terbuka
        # di DESCRIBE -> video terverifikasi tanpa ffprobe (hemat
        # ~6-13 dtk per kamera yang sudah terdaftar). Path sub yang
        # dikenal ikut ditandai bila terbuka. Dicek tiap gelombang
        # supaya langsung berhenti begitu path main terdaftar terbuka.
        if known_paths and known_paths[0]:
            by_path = {
                pr.path: pr for pr in probed
                if pr.status in ("open", "video")
            }
            known_main = by_path.get(known_paths[0])
            if known_main is not None:
                known_main.status = "video"
                known_main.role = "main"
                known_sub = None
                if known_paths[1]:
                    known_sub = by_path.get(known_paths[1])
                    if known_sub is not None:
                        known_sub.status = "video"
                        known_sub.role = "sub"
                kept = [pr for pr in probed if pr.status != "open"]
                return DiscoveryResult(
                    host=host, port=port, reachable=True, paths=kept,
                    best_main=known_main.url,
                    best_sub=known_sub.url if known_sub is not None else None,
                )

        # ffprobe path open yang baru, dibatasi total _MAX_VERIFY_PATHS
        # (paralel 2 per host; tanpa batas, kamera yang menjawab 200
        # untuk semua path timeout tanpa hasil).
        newly_open = [pr for pr in results if pr.status == "open"]
        room = _MAX_VERIFY_PATHS - verified_count
        to_verify = newly_open[:room] if room > 0 else []
        if to_verify:
            await asyncio.gather(*(verify_one(pr) for pr in to_verify))
            verified_count += len(to_verify)

        # Berhenti dini: main+sub sudah terverifikasi video.
        # (Reset role dulu: select_main_sub menandai role dan tidak
        # membersihkan pilihan gelombang sebelumnya.)
        for p in probed:
            p.role = None
        best_main, best_sub = select_main_sub(probed)
        if best_main is not None and best_sub is not None:
            break

    # Bila TIDAK ADA satu pun path yang lolos auth (semua auth_failed)
    # kemungkinan kamera mengunci login sementara (anti-brute-force)
    # akibat burst percobaan — BUKAN password salah. Coba ulang
    # sekali setelah jeda supaya kunci sempat lepas dalam satu scan
    # yang sama. Bila tetap gagal, barulah 'Login salah' (password
    # memang salah). Syarat saw_open=False penting: bila ada satu pun
    # path yang lolos auth, kamera jelas tidak terkunci, jadi tidak
    # perlu coba ulang.
    if _allow_auth_retry and probed and not saw_open:
        if any(p.status == "auth_failed" for p in probed):
            await asyncio.sleep(_AUTH_RETRY_DELAY)
            return await _discover(
                host, port, user, password, channel, known_paths,
                _allow_auth_retry=False,
            )

    for p in probed:
        p.role = None
    best_main, best_sub = select_main_sub(probed)
    return DiscoveryResult(
        host=host, port=port, reachable=True, paths=probed,
        best_main=best_main, best_sub=best_sub,
    )
