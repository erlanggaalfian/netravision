"""Sub stream selalu menyala 24/7 (aturan user 2026-11-13).

- Main: runOnReady = ffmpeg transcode main -> sub, runOnReadyRestart True.
  Sub hidup sejak main siap, bukan menunggu penonton.
- Sub: hanya source publisher; TIDAK ada runOnDemand (tidak pernah mati
  15 detik setelah penonton pergi). runOnDemand lama dikosongkan ("")
  supaya konfigurasi lama ikut terhapus saat sync.
- Parameter transcode tidak berubah (480x270, 8 fps, 120 kbps, GOP 16).
"""

import pytest

from app.services.stream_paths import (
    main_conf,
    register_stream,
    sub_conf,
    sub_ffmpeg_cmd,
)
from tests.conftest import FakeMediaMTX


def test_sub_ffmpeg_cmd_main_ke_sub():
    cmd = sub_ffmpeg_cmd(7)
    assert "rtsp://127.0.0.1:$RTSP_PORT/stream_7 " in cmd
    assert cmd.endswith("rtsp://127.0.0.1:$RTSP_PORT/stream_7_sub")
    # TIDAK ada flag -reconnect: ffmpeg 8.1.3 di image mediamtx tidak
    # mengenal opsi itu ("Option reconnect not found" -> exit 8, semua
    # sub mati total 2026-11-13 04:54 WIB). Retry ditangani MediaMTX
    # via runOnAvailableRestart.
    assert "-reconnect" not in cmd
    # Parameter transcode TIDAK berubah.
    assert "-vf scale=480:270" in cmd
    assert "-b:v 120k" in cmd
    assert "-r 8" in cmd and "-g 16" in cmd
    assert "-an" in cmd  # tanpa audio


def test_main_conf_run_on_ready():
    m = main_conf("rtsp://kamera/x", True, stream_id=7)
    assert m["sourceOnDemand"] is False  # main selalu tersambung
    assert m["runOnReady"] == sub_ffmpeg_cmd(7)
    assert m["runOnReadyRestart"] is True


def test_main_conf_tanpa_stream_id_tanpa_run_on_ready():
    m = main_conf("rtsp://kamera/x", True)
    assert "runOnReady" not in m
    assert "runOnReadyRestart" not in m


def test_sub_conf_tanpa_run_on_demand():
    c = sub_conf(7)
    assert c["source"] == "publisher"
    assert c["runOnDemand"] == ""  # kosongkan konfigurasi lama
    assert "runOnDemandCloseAfter" not in c
    assert "runOnDemandStartTimeout" not in c
    assert "runOnDemandRestart" not in c
    assert c["record"] is False


@pytest.mark.asyncio
async def test_register_stream_always_on():
    mtx = FakeMediaMTX()
    await register_stream(mtx, 7, "rtsp://kamera/x", True)
    main = mtx.confs["stream_7"]
    sub = mtx.confs["stream_7_sub"]
    assert main["runOnReady"] == sub_ffmpeg_cmd(7)
    assert main["runOnReadyRestart"] is True
    assert main["source"] == "rtsp://kamera/x"
    assert sub["source"] == "publisher"
    assert sub["runOnDemand"] == ""
