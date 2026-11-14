"""Sub stream native dari kamera (transcoder MATI TOTAL, 2026-11-14).

- Main: TIDAK ada lagi runOnReady/runOnAvailable ffmpeg. Main hanya
  menarik RTSP kamera.
- Sub: HANYA dari sub_url asli kamera (RTSP source, bukan publisher,
  bukan ffmpeg). Bila kamera tidak punya sub_url, path sub TIDAK
  dibuat sama sekali (dan yang lama dihapus saat register/sync).
- Frontend memakai main sebagai fallback bila kamera tanpa sub
  (lihat CameraTile), jadi tile tidak hitam.
"""

import pytest

from app.services.stream_paths import (
    main_conf,
    register_stream,
    sub_conf,
    sub_path,
)
from tests.conftest import FakeMediaMTX


def test_main_conf_tanpa_run_on_ready():
    """Main tidak lagi menjalankan ffmpeg transcode (transcoder mati)."""
    m = main_conf("rtsp://kamera/x", True)
    assert m["sourceOnDemand"] is False
    assert m["source"] == "rtsp://kamera/x"
    assert "runOnReady" not in m
    assert "runOnReadyRestart" not in m
    assert "runOnAvailable" not in m
    # Retensi + recordPath tetap seperti dulu.
    assert main_conf("rtsp://kamera/x", True, 30)["recordDeleteAfter"] == "720h"
    assert "recordDeleteAfter" not in main_conf("rtsp://kamera/x", True)
    assert "recordDeleteAfter" not in main_conf("rtsp://kamera/x", False, 30)
    rp = "/mnt/disk2/recordings/Gedung_A/Kamera_1/%path/%Y-%m-%d_%H-%M-%S-%f.mp4"
    assert main_conf("rtsp://kamera/x", True, 30, rp)["recordPath"] == rp
    assert "recordPath" not in main_conf("rtsp://kamera/x", True)
    assert "recordPath" not in main_conf("rtsp://kamera/x", True, 30)
    assert "recordPath" not in main_conf("rtsp://kamera/x", False, 30, rp)


def test_sub_conf_native_dari_kamera():
    """Sub native: source RTSP sub_url kamera, selalu tersambung."""
    c = sub_conf("rtsp://kamera/sub")
    assert c["source"] == "rtsp://kamera/sub"
    assert c["rtspTransport"] == "tcp"
    assert c["sourceOnDemand"] is False
    assert c["runOnDemand"] == ""  # kosongkan konfigurasi lama
    assert c["record"] is False


def test_sub_conf_merekam_dengan_retensi():
    """Sub adalah sumber rekaman bila kamera punya sub (2026-11-14):
    record=True membawa recordDeleteAfter + recordPath seperti main."""
    rp = "/mnt/disk2/recordings/Gedung_A/Kamera_1/%path/%Y-%m-%d_%H-%M-%S-%f.mp4"
    c = sub_conf("rtsp://kamera/sub", True, 30, rp)
    assert c["record"] is True
    assert c["recordDeleteAfter"] == "720h"
    assert c["recordPath"] == rp
    assert "recordDeleteAfter" not in sub_conf("rtsp://kamera/sub", True)
    assert "recordPath" not in sub_conf("rtsp://kamera/sub", True)
    assert "recordDeleteAfter" not in sub_conf("rtsp://kamera/sub", False, 30, rp)
    assert "recordPath" not in sub_conf("rtsp://kamera/sub", False, 30, rp)


@pytest.mark.asyncio
async def test_register_stream_dengan_sub_native():
    """Kamera punya sub_url: main tanpa ffmpeg + sub native RTSP.
    Rekaman dari SUB (perintah user 2026-11-14): main record=False,
    sub record=True, supaya yang disimpan substream bukan mainstream."""
    mtx = FakeMediaMTX()
    await register_stream(
        mtx, 7, "rtsp://kamera/main", True,
        sub_source="rtsp://kamera/sub",
    )
    main = mtx.confs["stream_7"]
    sub = mtx.confs["stream_7_sub"]
    assert main["source"] == "rtsp://kamera/main"
    assert "runOnReady" not in main
    assert main["record"] is False
    assert sub["source"] == "rtsp://kamera/sub"
    assert sub["rtspTransport"] == "tcp"
    assert sub["sourceOnDemand"] is False
    assert sub["record"] is True


@pytest.mark.asyncio
async def test_register_stream_tanpa_sub_main_merekam():
    """Kamera tanpa sub_url: main yang merekam (fallback), supaya tetap
    ada rekaman walau kamera tidak punya substream."""
    mtx = FakeMediaMTX()
    await register_stream(mtx, 7, "rtsp://kamera/main", True)
    assert mtx.confs["stream_7"]["source"] == "rtsp://kamera/main"
    assert mtx.confs["stream_7"]["record"] is True
    assert "stream_7_sub" not in mtx.confs
    # register_stream menghapus path sub lama bila ada (transcode dulu).
    assert sub_path(7) in mtx.deleted


@pytest.mark.asyncio
async def test_register_stream_sub_dihapus_bila_sub_hilang():
    """Kamera yang tadinya punya sub lalu sub-nya dihapus: path sub
    ikut terhapus, main tetap jalan tanpa ffmpeg DAN main kembali
    merekam (fallback) supaya rekaman tidak berhenti."""
    mtx = FakeMediaMTX()
    await register_stream(
        mtx, 7, "rtsp://kamera/main", True,
        sub_source="rtsp://kamera/sub",
    )
    assert "stream_7_sub" in mtx.confs
    assert mtx.confs["stream_7"]["record"] is False
    await register_stream(mtx, 7, "rtsp://kamera/main", True)
    assert "stream_7_sub" not in mtx.confs
    assert "stream_7" in mtx.confs
    assert "runOnReady" not in mtx.confs["stream_7"]
    assert mtx.confs["stream_7"]["record"] is True
