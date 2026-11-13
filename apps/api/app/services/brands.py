"""Registry template URL RTSP per brand kamera.

Dipakai oleh stream_resolver sebagai lapis kedua setelah ONVIF:
bila kamera tidak support ONVIF, URL main/sub diturunkan dari template brand.
Template di sini juga dipakai scanner (candidate_paths di
rtsp_discovery.py) — tiap profil main/sub menjadi path kandidat.

Sumber pola (riset web 2026-11-13, laporan
~/workspace/research_notes/rtsp-paths-all-camera-brands-20261113-1234/report.md):
~55 merek + pola generik/ONVIF. Bila sumber berkonflik, SEMUA varian
dimasukkan sebagai kandidat (bukan dipilih satu): mis. Hanwha
profile1/profile2 vs profile2/profile3, Ezviz /h264/ch01/... vs
/ch1/main vs /h264_stream, Tiandy /h264/ch01/... vs /1/1 vs /1/2.

Port RTSP default 554, KECUALI merek berikut (port alternatif ini
TIDAK dipindai otomatis oleh scanner — scanner memakai port yang
dimasukkan user, default 554; untuk merek di bawah ini masukkan
portnya secara manual saat scan/tambah kamera):
  Foscam 88 (sebagian model 554), GeoVision 8554 (sebagian 554),
  ACTi 7070, Zmodo 10554, V380 10554, Hiseeu 80 (gateway; sebagian
  kamera 554), UniFi Protect 7441 (rtsps) / 7447, CamHi 5544,
  VStarcam/Tuya 10554, XM DVR 10554.
Merek TANPA RTSP native (sengaja TIDAK ada profilnya di sini):
  Ring, Google Nest (cloud-only). UniFi Protect memakai token
  rtsps://:7441/{token} yang digenerate per kamera (bukan path
  tetap) sehingga tidak bisa ditebak/dipindai. Wyze hanya via
  firmware RTSP khusus (stock firmware tidak ada RTSP); Xiaomi
  hanya via custom firmware (yi-hack) — profil xiaomi di bawah
  memakai pola yi-hack tersebut. Bentuk XM dengan kredensial di
  query (/user={user}&password={password}&channel=1&stream=0.sdp)
  tidak didukung pemindaian kandidat (kredensial di query tidak
  cocok dengan arsitektur probe yang memakai auth URL); bentuk
  XM utama (/onvif1, /onvif2, /11, /12) tetap dipindai.
"""

from __future__ import annotations

from urllib.parse import quote

# Tiap profil: {"label", "main", "sub"}. Placeholder: {user} {password} {host}
# {port} {channel}. "sub" boleh None bila brand tidak punya konsep sub stream.
# Aturan: profil ditambahkan bila template main/sub-nya menyumbang
# minimal satu path kandidat BARU (belum ada di _COMMON_PATHS maupun
# profil lain). Merek OEM yang polanya identik dengan merek lain
# (mis. Annke = Hikvision, Amcrest/Imou/Intelbras/CP Plus/Lorex =
# Dahua, Sony = Uniview, Tiandy = Ezviz untuk bentuk /h264/ch01/...,
# Abus = Vivotek /live.sdp, Hanbang = Infinova) TIDAK dibuatkan
# profil duplikat — polanya sudah dipindai lewat profil aslinya.
BRAND_PROFILES: dict[str, dict[str, str | None]] = {
    "hikvision": {
        "label": "Hikvision",
        "main": "rtsp://{user}:{password}@{host}:{port}/Streaming/Channels/{channel}01",
        "sub": "rtsp://{user}:{password}@{host}:{port}/Streaming/Channels/{channel}02",
    },
    "dahua": {
        "label": "Dahua / Amcrest",
        "main": "rtsp://{user}:{password}@{host}:{port}/cam/realmonitor?channel={channel}&subtype=0",
        "sub": "rtsp://{user}:{password}@{host}:{port}/cam/realmonitor?channel={channel}&subtype=1",
    },
    "uniview_ipc": {
        "label": "Uniview (kamera langsung)",
        "main": "rtsp://{user}:{password}@{host}:{port}/media/video1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/media/video2",
    },
    "uniview_nvr": {
        "label": "Uniview (NVR)",
        "main": "rtsp://{user}:{password}@{host}:{port}/unicast/c{channel}/s0/live",
        "sub": "rtsp://{user}:{password}@{host}:{port}/unicast/c{channel}/s1/live",
    },
    "hanwha": {
        "label": "Hanwha / Samsung",
        "main": "rtsp://{user}:{password}@{host}:{port}/profile1/media.smp",
        "sub": "rtsp://{user}:{password}@{host}:{port}/profile2/media.smp",
    },
    "axis": {
        "label": "Axis",
        # Riset 2026-11-13: main memakai ?camera={channel}; tidak ada
        # path sub yang distinct — sub memakai profil/resolusi rendah
        # yang sama (?camera=..&resolution=640x360).
        "main": "rtsp://{user}:{password}@{host}:{port}/axis-media/media.amp?camera={channel}",
        "sub": "rtsp://{user}:{password}@{host}:{port}/axis-media/media.amp?camera={channel}&resolution=640x360",
    },
    "tplink_vigi": {
        "label": "TP-Link Vigi",
        "main": "rtsp://{user}:{password}@{host}:{port}/stream1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/stream2",
    },
    "reolink": {
        "label": "Reolink",
        "main": "rtsp://{user}:{password}@{host}:{port}/h264Preview_01_main",
        "sub": "rtsp://{user}:{password}@{host}:{port}/h264Preview_01_sub",
    },
    "foscam": {
        "label": "Foscam",
        "main": "rtsp://{user}:{password}@{host}:{port}/videoMain",
        "sub": "rtsp://{user}:{password}@{host}:{port}/videoSub",
    },
    "milesight": {
        "label": "Milesight",
        "main": "rtsp://{user}:{password}@{host}:{port}/main",
        "sub": "rtsp://{user}:{password}@{host}:{port}/sub",
    },
    "panasonic": {
        "label": "Panasonic",
        "main": "rtsp://{user}:{password}@{host}:{port}/MediaInput/h264/stream_1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/MediaInput/h264/stream_2",
    },
    # Ezviz (konsumen): bentuk utama menurut riset (SmartRTSP/ZWPlayer)
    # adalah /h264/ch01/main|sub/av_stream. Varian konflik (/ch1/main,
    # /h264_stream, /H.264, /H.264_sub) tetap dipindai sebagai path
    # kandidat di _COMMON_PATHS. Password umumnya = device verification
    # code (6 karakter di stiker perangkat), dan RTSP kadang nonaktif
    # default di firmware baru (aktifkan dulu di aplikasi Ezviz / web
    # perangkat).
    "ezviz": {
        "label": "Ezviz",
        "main": "rtsp://{user}:{password}@{host}:{port}/h264/ch01/main/av_stream",
        "sub": "rtsp://{user}:{password}@{host}:{port}/h264/ch01/sub/av_stream",
    },
    # --- Profil baru dari riset 2026-11-13 (report.md) ---
    "bosch": {
        "label": "Bosch",
        "main": "rtsp://{user}:{password}@{host}:{port}/?h26x=4&line=1&inst=1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/?h26x=4&line=1&inst=2",
    },
    "avigilon": {
        "label": "Avigilon",
        "main": "rtsp://{user}:{password}@{host}:{port}/defaultPrimary?streamType=u",
        "sub": "rtsp://{user}:{password}@{host}:{port}/defaultSecondary?streamType=u",
    },
    "vivotek": {
        "label": "Vivotek",
        "main": "rtsp://{user}:{password}@{host}:{port}/live.sdp",
        "sub": "rtsp://{user}:{password}@{host}:{port}/live2.sdp",
    },
    "pelco": {
        "label": "Pelco",
        "main": "rtsp://{user}:{password}@{host}:{port}/h264",
        "sub": "rtsp://{user}:{password}@{host}:{port}/h264_2",
    },
    "arecont": {
        "label": "Arecont Vision",
        "main": "rtsp://{user}:{password}@{host}:{port}/h264.sdp",
        "sub": None,
    },
    "provision_isr": {
        "label": "Provision-ISR",
        "main": "rtsp://{user}:{password}@{host}:{port}/profile1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/profile2",
    },
    "tvt": {
        "label": "TVT",
        "main": "rtsp://{user}:{password}@{host}:{port}/?chID={channel}&streamType=main&linkType=tcp",
        "sub": "rtsp://{user}:{password}@{host}:{port}/?chID={channel}&streamType=sub&linkType=tcp",
    },
    "hiseeu": {
        "label": "Hiseeu",
        "main": "rtsp://{user}:{password}@{host}:{port}/ch0_0.264",
        "sub": "rtsp://{user}:{password}@{host}:{port}/ch0_1.264",
    },
    "zosi": {
        "label": "Zosi",
        "main": "rtsp://{user}:{password}@{host}:{port}/onvif1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/onvif2",
    },
    "swann": {
        "label": "Swann",
        "main": "rtsp://{user}:{password}@{host}:{port}/ch01/0",
        "sub": "rtsp://{user}:{password}@{host}:{port}/ch01/1",
    },
    "geovision": {
        "label": "GeoVision",
        "main": "rtsp://{user}:{password}@{host}:{port}/CH001.sdp",
        "sub": None,
    },
    "huawei": {
        "label": "Huawei / Holosens",
        "main": "rtsp://{user}:{password}@{host}:{port}/LiveMedia/ch1/Media1",
        "sub": "rtsp://{user}:{password}@{host}:{port}/LiveMedia/ch1/Media2",
    },
    "dlink": {
        "label": "D-Link",
        "main": "rtsp://{user}:{password}@{host}:{port}/play1.sdp",
        "sub": "rtsp://{user}:{password}@{host}:{port}/live1.sdp",
    },
    "digital_watchdog": {
        "label": "Digital Watchdog",
        "main": "rtsp://{user}:{password}@{host}:{port}/Streaming/Channels/1",
        "sub": None,
    },
    "zmodo": {
        "label": "Zmodo",
        "main": "rtsp://{user}:{password}@{host}:{port}/tcp/av0_0",
        "sub": "rtsp://{user}:{password}@{host}:{port}/tcp/av0_1",
    },
    "kedacom": {
        "label": "Kedacom",
        "main": "rtsp://{user}:{password}@{host}:{port}/session0?streamid=main",
        "sub": "rtsp://{user}:{password}@{host}:{port}/session0?streamid=sub",
    },
    "infinova": {
        "label": "Infinova",
        "main": "rtsp://{user}:{password}@{host}:{port}/1/h264major",
        "sub": "rtsp://{user}:{password}@{host}:{port}/1/h264minor",
    },
    "raysharp": {
        "label": "Raysharp",
        "main": "rtsp://{user}:{password}@{host}:{port}/stream0",
        "sub": "rtsp://{user}:{password}@{host}:{port}/stream1",
    },
    "canon": {
        "label": "Canon",
        "main": "rtsp://{user}:{password}@{host}:{port}/stream/profile1=u",
        "sub": "rtsp://{user}:{password}@{host}:{port}/stream/profile1=r",
    },
    "lg": {
        "label": "LG",
        "main": "rtsp://{user}:{password}@{host}:{port}/Master-0",
        "sub": "rtsp://{user}:{password}@{host}:{port}/Slave-0",
    },
    "jvs": {
        "label": "JVS / Jovision",
        "main": "rtsp://{user}:{password}@{host}:{port}/live0.264",
        "sub": "rtsp://{user}:{password}@{host}:{port}/live1.264",
    },
    # Xiaomi: TIDAK ada RTSP resmi di sebagian besar model — pola ini
    # via custom firmware (yi-hack), /ch0_0.h264 main, /ch0_1.h264 sub.
    "xiaomi": {
        "label": "Xiaomi / Mijia (yi-hack)",
        "main": "rtsp://{user}:{password}@{host}:{port}/ch0_0.h264",
        "sub": "rtsp://{user}:{password}@{host}:{port}/ch0_1.h264",
    },
    "eufy": {
        "label": "Eufy Security",
        "main": "rtsp://{user}:{password}@{host}:{port}/live0",
        "sub": "rtsp://{user}:{password}@{host}:{port}/live1",
    },
}


def resolve_brand_urls(
    brand: str,
    user: str,
    password: str,
    host: str,
    port: int = 554,
    channel: int = 1,
) -> tuple[str, str | None]:
    """Format template brand menjadi URL main/sub konkret.

    Raises:
        ValueError: bila brand tidak dikenal.
    """
    key = brand.strip().lower()
    profile = BRAND_PROFILES.get(key)
    if profile is None:
        known = ", ".join(sorted(BRAND_PROFILES))
        raise ValueError(f"Brand '{brand}' tidak dikenal. Pilihan: {known}")

    ctx = {
        "user": user,
        "password": quote(password, safe=""),
        "host": host,
        "port": port,
        "channel": channel,
    }
    main = str(profile["main"]).format(**ctx)
    sub = str(profile["sub"]).format(**ctx) if profile["sub"] else None
    return main, sub
