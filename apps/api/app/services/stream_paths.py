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
                     Merekam HANYA bila kamera tidak punya sub
                     (fallback, perintah user 2026-11-14: rekaman dari
                     substream bila ada).
- stream_{id}_sub  = SUB (hanya bila kamera punya sub_url): source RTSP
                     sub asli kamera (sub_url), rtspTransport tcp, selalu
                     tersambung (sourceOnDemand false). Bukan publisher,
                     bukan ffmpeg. Bila kamera tidak punya sub_url, path
                     ini tidak dibuat (dan yang lama dihapus saat sync)
                     supaya tidak ada lagi proses ffmpeg yang berjalan.
                     SUB ADALAH SUMBER REKAMAN bila ada (perintah user
                     2026-11-14: yang disimpan untuk playback adalah
                     substream, bukan mainstream; hemat disk karena
                     resolusi sub lebih kecil). Segmen sub masuk ke
                     direktori stream_{id}_sub/ (recordPath %path);
                     pembaca segmen (recording.list_segments, uploader
                     Drive) membaca stream_{id}/ DAN stream_{id}_sub/
                     sehingga rekaman lama dari main tetap bisa diputar.

Konsekuensi: kamera tanpa sub_url hanya punya MAIN dan main yang
merekam. Frontend (CameraTile) menampilkan MAIN sebagai fallback
bila tidak ada sub, supaya tile tidak hitam. Keputusan lama "grid
tidak pernah fallback ke main" SUDAH TIDAK BERLAKU lagi (keputusan
itu dibuat saat sub selalu ada via transcode).

Konsekuensi: kamera tanpa sub_url hanya punya MAIN. Frontend (CameraTile)
menampilkan MAIN sebagai fallback bila tidak ada sub, supaya tile tidak
hitam. Keputusan lama "grid tidak pernah fallback ke main" SUDAH TIDAK
BERLAKU lagi (keputusan itu dibuat saat sub selalu ada via transcode).

Pemakaian (frontend):
- tile grid / embed / layar monitor = SUB bila ada, MAIN bila tidak ada
- modal fokus (popup) = SUB dulu (bila ada), lalu MAIN (HD)
"""

from __future__ import annotations

import logging

log = logging.getLogger("netravision.stream_paths")


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


def sub_conf(sub_source: str, record: bool = False,
             retention_days: int | None = None,
             record_path: str | None = None) -> dict:
    """Konfigurasi path sub native sebuah kamera.

    Sub HANYA dari sub_url asli kamera (RTSP source, bukan publisher,
    bukan ffmpeg). Path ini hanya dibuat bila sub_source ada; pemanggil
    (register_stream) yang memastikan itu. ``runOnDemand`` dikosongkan
    ("") supaya konfigurasi lama (runOnDemand + closeAfter 15 detik)
    yang masih menempel di MediaMTX ikut terhapus saat sync.

    Rekaman (perintah user 2026-11-14): SUB adalah sumber rekaman bila
    ada. ``record=True`` di sini hanya dipakai bila register_stream
    memutuskan sub yang merekam (kamera punya sub + recording aktif);
    recordDeleteAfter/recordPath mengikuti aturan yang sama seperti
    main_conf. ``record_path`` memakai placeholder %path MediaMTX,
    sehingga segmen sub masuk ke direktori stream_{id}_sub/.
    """
    conf = {
        "source": sub_source,
        "rtspTransport": "tcp",
        "sourceOnDemand": False,
        "runOnDemand": "",
        "record": bool(record),
    }
    if record and retention_days:
        conf["recordDeleteAfter"] = f"{int(retention_days) * 24}h"
    if record and record_path:
        conf["recordPath"] = record_path
    return conf


async def register_stream(mediamtx, stream_id: int, source: str,
                          record: bool, retention_days: int | None = None,
                          record_path: str | None = None,
                          sub_source: str | None = None) -> None:
    """Daftarkan/selaraskan main + sub sebuah kamera (idempoten).

    Main selalu didaftarkan (tanpa runOnReady ffmpeg). Sub HANYA
    didaftarkan bila sub_source (sub_url asli kamera) ada; bila tidak
    ada, path sub yang lama DIHAPUS supaya tidak ada lagi transcode
    yang berjalan dan tidak ada path sub yatim.

    Sumber rekaman (perintah user 2026-11-14): SUB bila kamera punya
    sub_url, MAIN sebagai fallback bila tidak punya sub. Jadi main
    hanya merekam bila tidak ada sub; bila sub ada, main record=False
    dan sub yang record=True. Segmen lama di stream_{id}/ tetap ada
    di disk dan tetap bisa diputar (pembaca segmen membaca kedua
    direktori); peralihan tidak menghapus rekaman lama.

    Mutasi path (ensure_path/delete_path) sudah ter-serialisasi oleh
    MEDIA_PATH_LOCK di MediaMTXClient, jangan tambah lock kedua di sini.
    """
    has_sub = bool(sub_source)
    await mediamtx.ensure_path(
        main_path(stream_id),
        main_conf(source, record and not has_sub, retention_days,
                  record_path),
    )
    if has_sub:
        await mediamtx.ensure_path(
            sub_path(stream_id),
            sub_conf(sub_source, record=record,
                     retention_days=retention_days,
                     record_path=record_path),
        )
    else:
        # Tanpa sub asli: hapus path sub lama (transcode dulu / native
        # yang sudah tidak berlaku). delete_path menoleransi 404.
        try:
            await mediamtx.delete_path(sub_path(stream_id))
        except Exception as exc:  # noqa: BLE001 - hapus best-effort
            log.warning(
                "register_stream: gagal menghapus path sub lama %s "
                "(best-effort, diabaikan): %s",
                sub_path(stream_id),
                exc,
            )


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
    # Sub native: source RTSP kamera, selalu tersambung, tanpa rekaman
    # bila record=False; merekam (dengan retensi + recordPath) bila
    # record=True (sumber rekaman bila kamera punya sub).
    s = sub_conf("rtsp://kamera/sub")
    assert s["source"] == "rtsp://kamera/sub"
    assert s["rtspTransport"] == "tcp"
    assert s["sourceOnDemand"] is False
    assert s["runOnDemand"] == ""
    assert s["record"] is False
    assert "runOnReady" not in s
    assert "recordDeleteAfter" not in sub_conf("rtsp://kamera/sub", True)
    assert sub_conf("rtsp://kamera/sub", True, 30)["recordDeleteAfter"] == "720h"
    assert sub_conf("rtsp://kamera/sub", True, 30, rp)["recordPath"] == rp
    assert "recordPath" not in sub_conf("rtsp://kamera/sub", True)
    assert "recordPath" not in sub_conf("rtsp://kamera/sub", False, 30, rp)


if __name__ == "__main__":
    _selftest()
    print("ok")
