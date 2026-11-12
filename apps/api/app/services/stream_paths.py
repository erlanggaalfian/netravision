"""Konfigurasi path MediaMTX per kamera, pola v2 (cctv-monitoring) persis.

v2 (backend/main.py register_stream_in_mediamtx):
- stream_{id}      = MAIN: source RTSP kamera, rtspTransport tcp, selalu
                     tersambung (sourceOnDemand false, mode "preloaded").
                     Satu-satunya sesi RTSP ke kamera. Rekaman di path ini.
- stream_{id}_sub  = SUB: TIDAK ditarik dari kamera. ffmpeg mentranskode
                     stream_{id} (lokal) -> 480x270, 8 fps, 120 kbps, GOP 16
                     (keyframe tiap 2 dtk), tanpa audio; dinyalakan saat ada
                     penonton (runOnDemand) dan dimatikan 15 dtk setelahnya.

Akibatnya kamera cukup melayani 1 sesi RTSP (kamera yang membatasi sesi tidak
lagi menolak main -> 454 Session Not Found), main selalu siap -> video tampil
tanpa menunggu kamera disambung.

Pemakaian (frontend, juga sama dengan v2):
- tile grid / embed / layar monitor = SUB
- modal fokus = SUB dulu (instan), lalu ganti ke MAIN di latar (HD)
"""

from __future__ import annotations

# Parameter transkode v2 (register_transcoded_mediamtx_path). Jangan diubah
# tanpa alasan: dipakai identik di produksi lama.
SUB_FFMPEG = (
    "ffmpeg -rtsp_transport tcp -i rtsp://127.0.0.1:$RTSP_PORT/{main} "
    "-vf scale=480:270 -c:v libx264 -preset ultrafast -tune zerolatency "
    "-b:v 120k -maxrate 120k -bufsize 240k "
    "-r 8 -g 16 -an -f rtsp rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH"
)


def main_path(stream_id: int) -> str:
    return f"stream_{stream_id}"


def sub_path(stream_id: int) -> str:
    return f"stream_{stream_id}_sub"


def main_conf(source: str, record: bool, retention_days: int | None = None,
              record_path: str | None = None) -> dict:
    conf = {
        "source": source,
        "rtspTransport": "tcp",
        "sourceOnDemand": False,
        "record": bool(record),
    }
    # B-T3: setel recordDeleteAfter per kamera dari retention_days-nya, agar
    # retensi > 7 hari tidak dipangkas default 168 jam di pathDefaults.
    # None = biarkan default MediaMTX (168 jam).
    if record and retention_days:
        conf["recordDeleteAfter"] = f"{int(retention_days) * 24}h"
    # Rekaman multi-disk: recordPath per kamera dari record_disk-nya
    # (record_path_for). None = biarkan default MediaMTX (recordings_dir).
    if record and record_path:
        conf["recordPath"] = record_path
    return conf


def sub_conf(stream_id: int) -> dict:
    return {
        "source": "publisher",
        "runOnDemand": SUB_FFMPEG.format(main=main_path(stream_id)),
        "runOnDemandCloseAfter": "15s",
        "runOnDemandRestart": True,
        "record": False,
    }


async def register_stream(mediamtx, stream_id: int, source: str,
                          record: bool, retention_days: int | None = None,
                          record_path: str | None = None) -> None:
    """Daftarkan/selaraskan main + sub sebuah kamera (idempoten)."""
    await mediamtx.ensure_path(
        main_path(stream_id),
        main_conf(source, record, retention_days, record_path),
    )
    await mediamtx.ensure_path(sub_path(stream_id), sub_conf(stream_id))


def _selftest() -> None:
    c = sub_conf(7)
    assert "rtsp://127.0.0.1:$RTSP_PORT/stream_7 " in c["runOnDemand"]
    assert c["runOnDemand"].endswith("rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH")
    assert "-g 16" in c["runOnDemand"] and "-r 8" in c["runOnDemand"]
    assert main_conf("rtsp://x", True)["sourceOnDemand"] is False
    assert main_conf("rtsp://x", True, 30)["recordDeleteAfter"] == "720h"
    assert "recordDeleteAfter" not in main_conf("rtsp://x", True)
    assert "recordDeleteAfter" not in main_conf("rtsp://x", False, 30)
    rp = "/mnt/disk2/recordings/Gedung_A/Kamera_1/%path/%Y-%m-%d_%H-%M-%S-%f.mp4"
    assert main_conf("rtsp://x", True, 30, rp)["recordPath"] == rp
    assert "recordPath" not in main_conf("rtsp://x", True)
    assert "recordPath" not in main_conf("rtsp://x", True, 30)
    assert "recordPath" not in main_conf("rtsp://x", False, 30, rp)


if __name__ == "__main__":
    _selftest()
    print("ok")
