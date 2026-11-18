"""Test staging sweep (auto-upload segmen nyangkut di staging mirror).

Sejak 2026-11-18, _upload_once menyapu staging mirror
(settings.gdrive_record_path) dan meng-upload segmen yang nyangkut
ke Drive begitu koneksi pulih. Test ini membuktikan:
- file staging yang belum di drive_uploads ter-upload dan tercatat,
  lalu file staging dihapus;
- file yang sudah ada di drive_uploads dilewati (tidak dobel);
- file yang sedang diklaim (mirror/OAuth) dilewati;
- file staging TIDAK dihapus bila upload gagal;
- _upload_once tidak menyentuh staging bila Drive putus, dan
  menjalankan sweep bila Drive konek.
"""

import os
import time

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.drive import GoogleDriveFolder
from app.models.streams import Stream

SEG = "2026-11-18_10-00-00-000000.mp4"
SEG2 = "2026-11-18_10-10-00-000000.mp4"


def _mk_stream(db, **kw):
    base = dict(name="Cam", rtsp_url="rtsp://x", is_active=True)
    base.update(kw)
    s = Stream(**base)
    db.add(s)
    return s


def _mk_folder(db, local_path, name="netravision"):
    f = GoogleDriveFolder(folder_name=name, local_path=local_path)
    db.add(f)
    return f


def _mk_staging_file(staging_base, stream_id, name, size=100, age_sec=3600):
    d = os.path.join(str(staging_base), f"stream_{stream_id}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    old = time.time() - age_sec
    os.utime(p, (old, old))
    return p


def _make_stable(path):
    """Beri tahu _is_stable bahwa file ini sudah terlihat dengan
    (mtime, size) yang sama, supaya langsung dianggap stabil."""
    from app.services.drive_uploader import _SEEN_STABLE

    st = os.stat(path)
    _SEEN_STABLE[path] = (st.st_mtime, st.st_size, time.time())


@pytest.fixture
def _uploader_db(monkeypatch, db_session):
    """Arahkan get_session_factory() milik drive_uploader ke DB tes."""
    from app.services import drive_uploader as du

    factory = async_sessionmaker(
        db_session.bind, class_=type(db_session), expire_on_commit=False
    )
    monkeypatch.setattr(du, "get_session_factory", lambda: factory)
    # Bersihkan pelacak kestabilan dan klaim antar test.
    du._SEEN_STABLE.clear()
    from app.services.upload_claims import _reset_for_tests

    _reset_for_tests()
    return db_session


async def _seed_camera(db, staging_base):
    """Satu folder + satu kamera drive/both; kembalikan (folder, stream)."""
    folder = _mk_folder(db, str(staging_base))
    await db.flush()
    stream = _mk_stream(
        db,
        recording_enabled=True,
        storage_mode="drive",
        drive_folder_id=folder.id,
    )
    await db.commit()
    return folder, stream


async def test_staging_sweep_uploads_pending(_uploader_db, tmp_path, monkeypatch):
    """File staging yang belum di drive_uploads ter-upload, tercatat,
    lalu file staging dihapus."""
    from app.services import drive_uploader as du

    db = _uploader_db
    staging = tmp_path / "staging"
    _, stream = await _seed_camera(db, staging)
    p = _mk_staging_file(staging, stream.id, SEG)
    _make_stable(p)
    calls = []

    async def fake_upload(local_path, folder_name, remote):
        calls.append((local_path, folder_name, remote))

    monkeypatch.setattr(du.gr, "upload_segment", fake_upload)
    failures = await du._sweep_staging()
    assert failures == 0
    assert len(calls) == 1
    assert calls[0][0] == p
    assert calls[0][1] == "netravision"
    assert calls[0][2] == f"Cam/{SEG}"
    assert not os.path.exists(p)
    assert await du._uploaded_names(stream.id, "netravision", [SEG]) == {SEG}


async def test_staging_sweep_skips_uploaded(_uploader_db, tmp_path, monkeypatch):
    """File staging yang sudah ada di drive_uploads dilewati dan
    TIDAK dihapus (bukan kita yang meng-uploadnya putaran ini)."""
    from app.services import drive_uploader as du

    db = _uploader_db
    staging = tmp_path / "staging"
    _, stream = await _seed_camera(db, staging)
    p = _mk_staging_file(staging, stream.id, SEG)
    _make_stable(p)
    await du._mark_uploaded(stream.id, SEG, "netravision")
    calls = []

    async def fake_upload(local_path, folder_name, remote):
        calls.append((local_path, folder_name, remote))

    monkeypatch.setattr(du.gr, "upload_segment", fake_upload)
    failures = await du._sweep_staging()
    assert failures == 0
    assert calls == []
    assert os.path.exists(p)


async def test_staging_sweep_skips_claimed(_uploader_db, tmp_path, monkeypatch):
    """File staging yang sedang diklaim jalur lain (mirror/OAuth)
    dilewati dan tidak dihapus."""
    from app.services import drive_uploader as du
    from app.services.upload_claims import try_claim

    db = _uploader_db
    staging = tmp_path / "staging"
    _, stream = await _seed_camera(db, staging)
    p = _mk_staging_file(staging, stream.id, SEG)
    _make_stable(p)
    assert try_claim(stream.id, SEG, "mirror") is True
    calls = []

    async def fake_upload(local_path, folder_name, remote):
        calls.append((local_path, folder_name, remote))

    monkeypatch.setattr(du.gr, "upload_segment", fake_upload)
    failures = await du._sweep_staging()
    assert failures == 0
    assert calls == []
    assert os.path.exists(p)


async def test_staging_sweep_keeps_file_on_failure(
    _uploader_db, tmp_path, monkeypatch
):
    """Upload gagal: file staging TIDAK dihapus, kegagalan dihitung,
    dan tidak ada jejak di drive_uploads."""
    from app.services import drive_uploader as du

    db = _uploader_db
    staging = tmp_path / "staging"
    _, stream = await _seed_camera(db, staging)
    p = _mk_staging_file(staging, stream.id, SEG)
    _make_stable(p)

    async def fake_upload_fail(*args, **kwargs):
        raise RuntimeError("rclone putus")

    monkeypatch.setattr(du.gr, "upload_segment", fake_upload_fail)
    failures = await du._sweep_staging()
    assert failures == 1
    assert os.path.exists(p)
    assert await du._uploaded_names(stream.id, "netravision", [SEG]) == set()


async def test_upload_once_skips_staging_when_disconnected(
    _uploader_db, tmp_path, monkeypatch
):
    """Drive putus: _upload_once return 1 dan tidak menyentuh staging."""
    from app.services import drive_uploader as du

    db = _uploader_db
    staging = tmp_path / "staging"
    _, stream = await _seed_camera(db, staging)
    p = _mk_staging_file(staging, stream.id, SEG)
    _make_stable(p)

    async def fake_status():
        return {"connected": False}

    monkeypatch.setattr(du.gr, "connection_status", fake_status)
    calls = []

    async def fake_upload(local_path, folder_name, remote):
        calls.append((local_path, folder_name, remote))

    monkeypatch.setattr(du.gr, "upload_segment", fake_upload)
    n = await du._upload_once()
    assert n == 1
    assert calls == []
    assert os.path.exists(p)


async def test_upload_once_runs_staging_when_connected(
    _uploader_db, tmp_path, monkeypatch
):
    """Drive konek: _upload_once menjalankan staging sweep dan
    meng-upload file staging yang tertunda."""
    from app.services import drive_uploader as du

    db = _uploader_db
    staging = tmp_path / "staging"
    _, stream = await _seed_camera(db, staging)
    p = _mk_staging_file(staging, stream.id, SEG)
    _make_stable(p)

    async def fake_status():
        return {"connected": True}

    monkeypatch.setattr(du.gr, "connection_status", fake_status)
    calls = []

    async def fake_upload(local_path, folder_name, remote):
        calls.append((local_path, folder_name, remote))

    monkeypatch.setattr(du.gr, "upload_segment", fake_upload)
    n = await du._upload_once()
    assert n == 0
    assert len(calls) == 1
    assert calls[0][2] == f"Cam/{SEG}"
    assert not os.path.exists(p)
    assert await du._uploaded_names(stream.id, "netravision", [SEG]) == {SEG}


async def test_staging_sweep_ignores_camera_without_staging(
    _uploader_db, tmp_path, monkeypatch
):
    """Kamera tanpa basis staging (folder tanpa local_path dan
    gdrive_record_path kosong) dilewati tanpa error."""
    from app.services import drive_uploader as du

    db = _uploader_db
    folder = GoogleDriveFolder(folder_name="netravision", local_path="")
    db.add(folder)
    await db.flush()
    _mk_stream(
        db,
        recording_enabled=True,
        storage_mode="drive",
        drive_folder_id=folder.id,
    )
    await db.commit()
    calls = []

    async def fake_upload(local_path, folder_name, remote):
        calls.append((local_path, folder_name, remote))

    monkeypatch.setattr(du.gr, "upload_segment", fake_upload)
    failures = await du._sweep_staging()
    assert failures == 0
    assert calls == []
