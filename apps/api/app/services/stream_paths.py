"""Konfigurasi path MediaMTX per kamera.

Aturan user (2026-11-14, mengikat, menggantikan aturan transcode 2026-11-13):
TRANSCODER MATI TOTAL. Tidak ada lagi ffmpeg transcode untuk sub stream,
bukan sebagai fallback sekalipun. Sub stream HANYA dari sub_url asli
kamera. Bila kamera tidak punya sub_url, path sub TIDAK dibuat sama
sekali.

Desain:
- stream_{id}      = MAIN: source RTSP kamera, rtspTransport tcp, selalu
                     tersambung (sourceOnDemand false, mode "preloaded").
                     Satu-satunya sesi RTSP ke kamera bila tanpa sub.
                     Rekaman di path ini.
- stream_{id}_sub  = SUB (hanya bila kamera punya sub_url): source RTSP
                     sub asli kamera (sub_url), rtspTransport tcp, selalu
                     tersambung (sourceOnDemand false). Bukan publisher,
                     bukan ffmpeg. Bila kamera tidak punya sub_url, path
                     ini tidak dibuat (dan yang lama dihapus saat sync)
                     supaya tidak ada lagi proses ffmpeg yang berjalan.

Konsekuensi: kamera tanpa sub_url hanya punya MAIN. Frontend (CameraTile)
menampilkan MAIN sebagai fallback bila tidak ada sub, supaya tile tidak
hitam. Keputusan lama "grid tidak pernah fallback ke main" SUDAH TIDAK
BERLAKU lagi (keputusan itu dibuat saat sub selalu ada via transcode).

Pemakaian (frontend):
- tile grid / embed / layar monitor = SUB bila ada, MAIN bila tidak ada
- modal fokus (popup) = SUB dulu (bila ada), lalu MAIN (HD)
"""

from __future__ import annotations


def main_path(stream_id: int) -> str:
    return f"stream_{stream_id}"


def sub_path(stream_id: int) -> str:
    return f"stream_{stream_id}_sub"


def main_conf(source: str, record: bool, retention_days: int | None = None,
              record_path: str | None = None) -> dict:
    """Konfigurasi path main sebuah kamera (always-on, tanpa transcode).

    TIDAK ada lagi runOnReady/runOnAvailable ffmpeg: transcoder mati
    total (perintah user 2026-11-14). Main hanya menarik RTSP kamera.
    """
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


def sub_conf(sub_source: str) -> dict:
    """Konfigurasi path sub native sebuah kamera.

    Sub HANYA dari sub_url asli kamera (RTSP source, bukan publisher,
    bukan ffmpeg). Path ini hanya dibuat bila sub_source ada; pemanggil
    (register_stream) yang memastikan itu. ``runOnDemand`` dikosongkan
    ("") supaya konfigurasi lama (runOnDemand + closeAfter 15 detik)
    yang masih menempel di MediaMTX ikut terhapus saat sync.
    """
    return {
        "source": sub_source,
        "rtspTransport": "tcp",
        "sourceOnDemand": False,
        "runOnDemand": "",
        "record": False,
    }


async def register_stream(mediamtx, stream_id: int, source: str,
                          record: bool, retention_days: int | None = None,
                          record_path: str | None = None,
                          sub_source: str | None = None) -> None:
    """Daftarkan/selaraskan main + sub sebuah kamera (idempoten).

    Main selalu didaftarkan (tanpa runOnReady ffmpeg). Sub HANYA
    didaftarkan bila sub_source (sub_url asli kamera) ada; bila tidak
    ada, path sub yang lama DIHAPUS supaya tidak ada lagi transcode
    yang berjalan dan tidak ada path sub yatim.
    """
    await mediamtx.ensure_path(
        main_path(stream_id),
        main_conf(source, record, retention_days, record_path),
    )
    if sub_source:
        await mediamtx.ensure_path(sub_path(stream_id), sub_conf(sub_source))
    else:
        # Tanpa sub asli: hapus path sub lama (transcode dulu / native
        # yang sudah tidak berlaku). delete_path menoleransi 404.
        try:
            await mediamtx.delete_path(sub_path(stream_id))
        except Exception:  # noqa: BLE001 - hapus best-effort
            pass


def _selftest() -> None:
    # Main: tanpa runOnReady/runOnAvailable (transcoder mati total).
    m = main_conf("rtsp://x", True)
    assert m["sourceOnDemand"] is False
    assert "runOnReady" not in m
    assert "runOnReadyRestart" not in m
    assert "runOnAvailable" not in m
    assert m["source"] == "rtsp://x"
    assert main_conf("rtsp://x", True, 30)["recordDeleteAfter"] == "720h"
    assert "recordDeleteAfter" not in main_conf("rtsp://x", True)
    assert "recordDeleteAfter" not in main_conf("rtsp://x", False, 30)
    rp = "/mnt/disk2/recordings/Gedung_A/Kamera_1/%path/%Y-%m-%d_%H-%M-%S-%f.mp4"
    assert main_conf("rtsp://x", True, 30, rp)["recordPath"] == rp
    assert "recordPath" not in main_conf("rtsp://x", True)
    assert "recordPath" not in main_conf("rtsp://x", True, 30)
    assert "recordPath" not in main_conf("rtsp://x", False, 30, rp)
    # Sub native: source RTSP kamera, selalu tersambung, tanpa rekaman.
    s = sub_conf("rtsp://kamera/sub")
    assert s["source"] == "rtsp://kamera/sub"
    assert s["rtspTransport"] == "tcp"
    assert s["sourceOnDemand"] is False
    assert s["runOnDemand"] == ""
    assert s["record"] is False
    assert "runOnReady" not in s


if __name__ == "__main__":
    _selftest()
    print("ok")
