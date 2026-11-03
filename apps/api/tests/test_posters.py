"""Poster: ffmpeg wajib dipaksa format JPEG (berkas sementara *.tmp) dan
gagal ffmpeg (returncode != 0) tidak boleh dianggap sukses."""

import subprocess

from app.services import posters


def test_capture_poster_forces_jpeg_and_checks_returncode(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        open(cmd[-1], "wb").write(b"\xff\xd8jpeg")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(posters.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(posters.subprocess, "run", fake_run)
    out = tmp_path / "stream_1.jpg"
    assert posters.capture_poster(1, "rtsp://mediamtx:8554/stream_1_sub", str(out))
    assert out.read_bytes().startswith(b"\xff\xd8")
    cmd = calls[0]
    assert cmd[cmd.index("-f") + 1] == "image2"

    def fail_run(cmd, **kw):
        open(cmd[-1], "wb").write(b"partial")
        return subprocess.CompletedProcess(cmd, 1, b"", b"boom")

    monkeypatch.setattr(posters.subprocess, "run", fail_run)
    out2 = tmp_path / "stream_2.jpg"
    assert not posters.capture_poster(2, "rtsp://x/y", str(out2))
    assert not out2.exists()
    assert not (tmp_path / "stream_2.jpg.tmp").exists()
