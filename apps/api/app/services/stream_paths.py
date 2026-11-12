"""Konfigurasi path MediaMTX per kamera.

Aturan user (2026-11-13, mengikat, menggantikan aturan 15 menit sebelumnya):
- SUB dan MAIN dua-duanya SELALU MENYALA 24/7 untuk semua kamera yang
  terjangkau. Tidak ada lagi kondisi mati, baik saat ada user login maupun
  tidak ada user sama sekali. Tidak ada timer idle, tidak ada
  runOnDemandCloseAfter yang mematikan.

Desain always-on:
- stream_{id}      = MAIN: source RTSP kamera, rtspTransport tcp, selalu
                     tersambung (sourceOnDemand false, mode "preloaded").
                     Satu-satunya sesi RTSP ke kamera. Rekaman di path ini.
                     Begitu main SIAP (ready), MediaMTX menjalankan perintah
                     ``runOnReady`` (ffmpeg transcode main -> sub); bila
                     ffmpeg berhenti/crash, ``runOnReadyRestart`` menjalankannya
                     lagi selama main masih siap. Jadi sub hidup sejak awal
                     (saat main online / saat sistem start), BUKAN menunggu
                     ada penonton pertama, dan tidak pernah mati.
- stream_{id}_sub  = SUB: TIDAK ditarik dari kamera. ffmpeg mentranskode
                     stream_{id} (lokal) -> 480x270, 8 fps, 120 kbps, GOP 16
                     (keyframe tiap 2 dtk), tanpa audio. Path ini hanya
                     ``source: publisher`` (ffmpeg yang dijalankan runOnReady
                     main yang publish ke sini). TIDAK ada lagi runOnDemand:
                     sub tidak menunggu penonton dan tidak dimatikan 15 detik
                     setelah penonton pergi.

Akibatnya kamera cukup melayani 1 sesi RTSP (kamera yang membatasi sesi tidak
lagi menolak main -> 454 Session Not Found), main selalu siap, DAN sub selalu
siap -> tile grid tampil tanpa menunggu ffmpeg start dan tanpa balapan 404.

Balapan 404 (2026-11-13): bila ffmpeg start saat main path belum siap,
MediaMTX jawab 404 -> ffmpeg exit 8. Penahan: ``runOnAvailableRestart``
(MediaMTX menjalankan lagi ffmpeg bila exit) sehingga percobaan ulang
terjadi saat main sudah siap. Dengan runOnAvailable, ffmpeg baru dijalankan
saat main sudah ready, jadi balapan ini sudah jauh berkurang. JANGAN tambah
flag -reconnect ke ffmpeg: ffmpeg 8.1.3 di image mediamtx tidak mengenal
opsi itu dan langsung exit code 8 (penyebab sub mati total 04:54 WIB).

Konsekuensi yang diterima user: 52 proses transcode ffmpeg berjalan
terus-menerus (beban CPU konstan).

Pemakaian (frontend, juga sama dengan v2):
- tile grid / embed / layar monitor = SUB (selalu; grid TIDAK PERNAH pakai main)
- modal fokus (popup, dikecualikan) = SUB dulu (instan), lalu ganti ke MAIN
  di latar (HD)
"""

from __future__ import annotations

# Parameter transkode v2 (register_transcoded_mediamtx_path). Jangan diubah
# tanpa alasan: dipakai identik di produksi lama.
# PERINGATAN 2026-11-13: JANGAN tambah flag -reconnect* di sini. ffmpeg 8.1.3
# di image mediamtx TIDAK mengenal opsi "reconnect" ("Option reconnect not
# found") sehingga ffmpeg langsung exit code 8 sebelum membuka input, dan
# SEMUA sub stream mati total (darurat 04:54 WIB). Retry saat main belum
# siap ditangani MediaMTX via runOnAvailableRestart (restart ffmpeg bila
# exit), bukan via flag ffmpeg.
# Codec/parameter transcode TIDAK berubah (480x270, 8 fps, 120 kbps, GOP 16).
# DARURAT WebRTC 2026-11-13: 40 transcode selalu-menyala membebani CPU
# (container mediamtx ~372%, load 7.11/8 core) sehingga MediaMTX
# kekurangan CPU untuk memproses ICE/STUN -> "deadline exceeded".
# `nice -n 10` menurunkan prioritas ffmpeg supaya MediaMTX (dan proses
# lain) didahulukan saat CPU padat; transcode tetap jalan, hanya
# mengalah bila ada yang lebih penting. `-loglevel error` membuang
# baris progres frame= yang membanjiri log MediaMTX.
SUB_FFMPEG = (
    "nice -n 10 ffmpeg -loglevel error -rtsp_transport tcp -i rtsp://127.0.0.1:$RTSP_PORT/{main} "
    "-vf scale=480:270 -c:v libx264 -preset ultrafast -tune zerolatency "
    "-b:v 120k -maxrate 120k -bufsize 240k "
    "-r 8 -g 16 -an -f rtsp rtsp://127.0.0.1:$RTSP_PORT/{sub}"
)


def main_path(stream_id: int) -> str:
    return f"stream_{stream_id}"


def sub_path(stream_id: int) -> str:
    return f"stream_{stream_id}_sub"


def sub_ffmpeg_cmd(stream_id: int) -> str:
    """Perintah ffmpeg transcode main -> sub untuk satu kamera.

    Dijalankan MediaMTX sebagai ``runOnReady`` path main (bukan sebagai
    ``runOnDemand`` path sub). Input = main lokal, output = sub lokal.
    """
    return SUB_FFMPEG.format(main=main_path(stream_id), sub=sub_path(stream_id))


def main_conf(source: str, record: bool, retention_days: int | None = None,
              record_path: str | None = None, stream_id: int | None = None) -> dict:
    conf = {
        "source": source,
        "rtspTransport": "tcp",
        "sourceOnDemand": False,
        "record": bool(record),
    }
    # Sub selalu menyala 24/7 (aturan user 2026-11-13): begitu main siap,
    # jalankan ffmpeg transcode main -> sub; bila ffmpeg berhenti/crash,
    # jalankan lagi selama main masih siap. stream_id None = tanpa
    # runOnReady (dipakai tes lama yang tidak peduli sub).
    if stream_id is not None:
        conf["runOnReady"] = sub_ffmpeg_cmd(stream_id)
        conf["runOnReadyRestart"] = True
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
    """Konfigurasi path sub sebuah kamera (always-on).

    Hanya ``source: publisher``: ffmpeg yang dijalankan ``runOnReady`` path
    main yang publish ke sini terus-menerus. ``runOnDemand`` dikosongkan
    ("") supaya konfigurasi lama (runOnDemand + closeAfter 15 detik) yang
    masih menempel di MediaMTX ikut terhapus saat sync; tanpa perintah
    runOnDemand, nilai closeAfter/restart lama menjadi tidak berpengaruh.
    """
    return {
        "source": "publisher",
        "runOnDemand": "",
        "record": False,
    }


async def register_stream(mediamtx, stream_id: int, source: str,
                          record: bool, retention_days: int | None = None,
                          record_path: str | None = None) -> None:
    """Daftarkan/selaraskan main + sub sebuah kamera (idempoten)."""
    await mediamtx.ensure_path(
        main_path(stream_id),
        main_conf(source, record, retention_days, record_path,
                  stream_id=stream_id),
    )
    await mediamtx.ensure_path(sub_path(stream_id), sub_conf(stream_id))


def _selftest() -> None:
    c = sub_conf(7)
    # Sub tidak lagi punya runOnDemand (always-on via runOnReady main).
    assert c["runOnDemand"] == ""
    assert "runOnDemandCloseAfter" not in c
    assert c["source"] == "publisher"
    # Perintah ffmpeg: main -> sub eksplisit, parameter transcode tetap.
    # TIDAK ada flag -reconnect (ffmpeg 8.1.3 tidak mengenalnya; lihat atas).
    cmd = sub_ffmpeg_cmd(7)
    assert "rtsp://127.0.0.1:$RTSP_PORT/stream_7 " in cmd
    assert cmd.endswith("rtsp://127.0.0.1:$RTSP_PORT/stream_7_sub")
    assert "-g 16" in cmd and "-r 8" in cmd
    assert "-reconnect" not in cmd
    assert "-vf scale=480:270" in cmd and "-b:v 120k" in cmd
    # Main: runOnReady + restart, sourceOnDemand tetap False.
    m = main_conf("rtsp://x", True, stream_id=7)
    assert m["sourceOnDemand"] is False
    assert m["runOnReady"] == cmd
    assert m["runOnReadyRestart"] is True
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
