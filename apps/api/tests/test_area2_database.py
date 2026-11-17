"""Test Area 2 (audit backend+database 2026-11-17).

Mencakup perbaikan yang bisa diuji di SQLite tes:
- 2.1 unique drive_uploads + _mark_uploaded idempotent (ON CONFLICT).
- 2.2 retensi jejak upload (prune_drive_upload_traces).
- 2.3 cek jejak dibatasi nama lokal (IN (...)) di _uploaded_names,
  retensi, dan agregasi _cheap_segment_dates.
- 2.5/2.15 CHECK + unique stream_permissions.
- 2.7 kolom is_denied ApiAccessLog + default created_at.
- 2.12 retensi audit_logs (prune_audit_logs).
- 2.13 default sentinel NULL (record_disk, custom_camera_name).
- 2.14/2.20 created_at AdConfig.
- 2.16 relationship() dasar.

Migrasi 0027 (PG) diuji terpisah di tests/test_area2_migration_pg.py
(butuh NETRAVISION_AREA2_PG_URL, di-skip tanpa itu).
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.audit import prune_audit_logs
from app.models.access import StreamPermission, UserStreamAccess
from app.models.drive import DriveAccount, DriveUpload
from app.models.keys import ApiAccessLog, ApiKey
from app.models.misc import AdConfig, AuditLog
from app.models.streams import Stream
from app.models.users import User
from app.services.drive_uploader import (
    _mark_uploaded,
    _uploaded_names,
    prune_drive_upload_traces,
)
from app.services.recording import apply_retention


def _mk_stream(db, **kw):
    base = dict(name="Cam", rtsp_url="rtsp://x", is_active=True)
    base.update(kw)
    s = Stream(**base)
    db.add(s)
    return s


def _mk_file(root, stream_id, name, size=100):
    d = os.path.join(str(root), f"stream_{stream_id}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    return p


@pytest.fixture
def _uploader_db(monkeypatch, db_session):
    """Arahkan get_session_factory() milik drive_uploader ke DB tes."""
    from app.services import drive_uploader as du

    factory = async_sessionmaker(
        db_session.bind, class_=type(db_session), expire_on_commit=False
    )
    monkeypatch.setattr(du, "get_session_factory", lambda: factory)
    return db_session


async def test_mark_uploaded_idempotent(_uploader_db):
    """2.1: _mark_uploaded dua kali untuk segmen sama -> 1 baris."""
    db = _uploader_db
    s = _mk_stream(db)
    await db.commit()
    await _mark_uploaded(s.id, "2026-11-02_10-00-00-000000.mp4", "netravision")
    await _mark_uploaded(s.id, "2026-11-02_10-00-00-000000.mp4", "netravision")
    rows = (await db.execute(select(DriveUpload))).scalars().all()
    assert len(rows) == 1
    assert rows[0].folder_name == "netravision"


async def test_drive_upload_unique_menolak_duplikat(db_session):
    """2.1: duplikat (stream_id, folder_name, segment_name) ditolak DB."""
    s = _mk_stream(db_session)
    await db_session.commit()
    sid = s.id  # snapshot: rollback setelah commit gagal meng-expire objek
    db_session.add(
        DriveUpload(stream_id=sid, segment_name="a.mp4", folder_name="f")
    )
    await db_session.commit()
    db_session.add(
        DriveUpload(stream_id=sid, segment_name="a.mp4", folder_name="f")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    # Folder berbeda bukan duplikat.
    db_session.add(
        DriveUpload(stream_id=sid, segment_name="a.mp4", folder_name="g")
    )
    await db_session.commit()


async def test_uploaded_names_dibatasi_nama_lokal(_uploader_db):
    """2.3: _uploaded_names(names=[...]) hanya mengembalikan yang diminta."""
    db = _uploader_db
    s = _mk_stream(db)
    await db.commit()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        await _mark_uploaded(s.id, name, "netravision")
    assert await _uploaded_names(s.id, "netravision", ["a.mp4"]) == {"a.mp4"}
    assert await _uploaded_names(s.id, "netravision", []) == set()
    assert await _uploaded_names(s.id, "lain", ["a.mp4"]) == set()


async def test_prune_drive_upload_traces(db_session):
    """2.2: hanya jejak lebih tua dari N hari yang dihapus."""
    s = _mk_stream(db_session)
    await db_session.commit()
    old = DriveUpload(stream_id=s.id, segment_name="old.mp4", folder_name="f")
    new = DriveUpload(stream_id=s.id, segment_name="new.mp4", folder_name="f")
    db_session.add_all([old, new])
    await db_session.commit()
    old.uploaded_at = datetime.now(timezone.utc) - timedelta(days=100)
    await db_session.commit()
    n = await prune_drive_upload_traces(db_session, days=90)
    assert n == 1
    rows = (await db_session.execute(select(DriveUpload))).scalars().all()
    assert [r.segment_name for r in rows] == ["new.mp4"]


async def test_prune_audit_logs(db_session):
    """2.12: hanya audit lebih tua dari N hari yang dihapus."""
    old = AuditLog(
        actor_id=None, action="GET /x", resource="/x",
        created_at=datetime.now(timezone.utc) - timedelta(days=100),
    )
    new = AuditLog(actor_id=None, action="GET /y", resource="/y")
    db_session.add_all([old, new])
    await db_session.commit()
    n = await prune_audit_logs(db_session, days=90)
    assert n == 1
    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert [r.action for r in rows] == ["GET /y"]


async def test_check_role_dan_storage_mode(db_session):
    """2.15: role / storage_mode di luar daftar ditolak DB."""
    db_session.add(
        User(username="bad", password_hash="x", role="superuser", is_active=True)
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    db_session.add(
        Stream(name="C", rtsp_url="rtsp://x", storage_mode="cloud")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    db_session.add(DriveAccount(name="a", status="weird"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    db_session.add(StreamPermission(stream_id=1, role="owner"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_stream_permission_unique(db_session):
    """2.5: dua baris (stream_id, role, user_id) sama ditolak DB.

    Diuji dengan user_id terisi: SQLite menganggap NULL berbeda-beda
    di unique index, jadi kasus user_id NULL (dua baris peran sama)
    hanya bisa diuji di PostgreSQL dengan NULLS NOT DISTINCT, lihat
    tests/test_area2_migration_pg.py.
    """
    s = _mk_stream(db_session)
    u = User(username="u3", password_hash="x", role="user", is_active=True)
    db_session.add(u)
    await db_session.commit()
    sid, uid = s.id, u.id  # snapshot: rollback meng-expire objek
    db_session.add(StreamPermission(stream_id=sid, role="guest", user_id=uid))
    await db_session.commit()
    db_session.add(StreamPermission(stream_id=sid, role="guest", user_id=uid))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    # Peran berbeda bukan duplikat.
    db_session.add(StreamPermission(stream_id=sid, role="user", user_id=uid))
    await db_session.commit()


async def test_sentinel_default_null(db_session):
    """2.13: record_disk / custom_camera_name kosong = NULL, bukan ''."""
    s = _mk_stream(db_session)
    k = ApiKey(name="k", key_hash="h" * 64)
    db_session.add_all([s, k])
    await db_session.commit()
    assert s.record_disk is None
    assert k.custom_camera_name is None


async def test_api_access_log_defaults(db_session):
    """2.7 + 2.14: is_denied default False, created_at diisi server."""
    log = ApiAccessLog(api_key_id=None, stream_id=None, action="stream.hit")
    db_session.add(log)
    await db_session.commit()
    assert log.is_denied is False
    assert log.created_at is not None
    denied = ApiAccessLog(
        api_key_id=None, stream_id=None, action="stream.denied:bad_key",
        is_denied=True,
    )
    db_session.add(denied)
    await db_session.commit()
    rows = (
        await db_session.execute(
            select(ApiAccessLog).where(ApiAccessLog.is_denied.is_(True))
        )
    ).scalars().all()
    assert [r.action for r in rows] == ["stream.denied:bad_key"]


async def test_ad_config_created_at(db_session):
    """2.20: AdConfig kini punya created_at."""
    cfg = AdConfig(key="k", value={"a": 1})
    db_session.add(cfg)
    await db_session.commit()
    assert cfg.created_at is not None


async def test_relationship_user_stream_access(db_session):
    """2.16: relationship() UserStreamAccess.user/.stream bisa dipakai."""
    u = User(username="u2", password_hash="x", role="user", is_active=True)
    s = _mk_stream(db_session)
    db_session.add(u)
    await db_session.commit()
    db_session.add(UserStreamAccess(user_id=u.id, stream_id=s.id, can_view=True))
    await db_session.commit()
    row = (
        await db_session.execute(select(UserStreamAccess))
    ).scalars().first()
    assert row.user.username == "u2"
    assert row.stream.name == "Cam"


async def test_apply_retention_drive_hanya_yang_terupload(db_session, tmp_path):
    """2.3: retensi drive menghapus segmen kedaluwarsa yang ter-upload
    saja; yang belum ter-upload dipertahankan walau kedaluwarsa."""
    s = _mk_stream(
        db_session, recording_enabled=True, storage_mode="drive",
        retention_days=1,
    )
    await db_session.commit()
    r = str(tmp_path)
    up = "2026-10-20_10-00-00-000000.mp4"
    keep = "2026-10-20_11-00-00-000000.mp4"
    _mk_file(tmp_path, s.id, up)
    _mk_file(tmp_path, s.id, keep)
    db_session.add(
        DriveUpload(stream_id=s.id, segment_name=up, folder_name="netravision")
    )
    await db_session.commit()
    n = await apply_retention(db_session, r)
    assert n == 1
    assert not os.path.exists(os.path.join(r, f"stream_{s.id}", up))
    assert os.path.exists(os.path.join(r, f"stream_{s.id}", keep))


async def test_cheap_segment_dates_agregasi(db_session, tmp_path, monkeypatch):
    """2.3: _cheap_segment_dates menghitung per tanggal tanpa memuat
    semua nama; nama yang ada lokal + di jejak dihitung sekali."""
    from app.routers import recordings as rec

    s = _mk_stream(
        db_session, recording_enabled=True, storage_mode="drive",
    )
    await db_session.commit()
    monkeypatch.setattr(
        rec.get_settings(), "recordings_dir", str(tmp_path)
    )
    # Lokal: 1 segmen 2026-11-02.
    _mk_file(tmp_path, s.id, "2026-11-02_10-00-00-000000.mp4")
    # Jejak: 1 segmen yang sama (dedup) + 2 segmen 2026-11-03.
    for name in (
        "2026-11-02_10-00-00-000000.mp4",
        "2026-11-03_10-00-00-000000.mp4",
        "2026-11-03_11-00-00-000000.mp4",
    ):
        db_session.add(
            DriveUpload(stream_id=s.id, segment_name=name, folder_name="f")
        )
    await db_session.commit()
    counts, needs_full = await rec._cheap_segment_dates(s, db_session)
    assert needs_full is False
    assert counts == {"2026-11-02": 1, "2026-11-03": 2}


async def test_cheap_segment_dates_tanpa_jejak_butuh_fallback(db_session, tmp_path, monkeypatch):
    """_cheap_segment_dates: kamera drive tanpa jejak -> needs_full True."""
    from app.routers import recordings as rec

    s = _mk_stream(
        db_session, recording_enabled=True, storage_mode="drive",
    )
    await db_session.commit()
    monkeypatch.setattr(
        rec.get_settings(), "recordings_dir", str(tmp_path)
    )
    counts, needs_full = await rec._cheap_segment_dates(s, db_session)
    assert counts == {}
    assert needs_full is True
