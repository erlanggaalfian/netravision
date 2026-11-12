"""Test service recording: segmen, linimasa, next-playable, retensi."""

import os
from datetime import date, datetime, timedelta

from app.models.streams import Stream
from app.services.recording import (
    apply_retention,
    build_timeline,
    find_next_playable,
    list_dates,
    list_segments,
    parse_segment_name,
)


def _mk(root, stream_id, name, size=100, mtime=None):
    d = os.path.join(str(root), f"stream_{stream_id}")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_parse_segment_name():
    assert parse_segment_name("2026-11-02_10-00-00-000000.mp4") == datetime(
        2026, 11, 2, 10, 0, 0
    )
    assert parse_segment_name("acak.mp4") is None
    assert parse_segment_name("2026-13-99_99-99-99-000000.mp4") is None
    # Toleransi .mp4.mp4 (recordPath lama + fmp4): segmen lama tetap terbaca.
    assert parse_segment_name("2026-11-02_10-00-00-000000.mp4.mp4") == datetime(
        2026, 11, 2, 10, 0, 0
    )


def test_list_segments_filter_dan_urut(tmp_path):
    r = str(tmp_path)
    _mk(tmp_path, 1, "2026-11-02_09-10-00-000000.mp4")
    _mk(tmp_path, 1, "2026-11-02_09-00-00-000000.mp4")
    _mk(tmp_path, 1, "2026-11-01_09-00-00-000000.mp4")
    _mk(tmp_path, 1, "bukan-segmen.mp4")

    segs = list_segments(1, date(2026, 11, 2), r)
    assert [(s.start.hour, s.start.minute) for s in segs] == [(9, 0), (9, 10)]
    assert all(s.size == 100 for s in segs)
    assert segs[0].end == segs[1].start  # end = awal segmen berikut

    assert list_segments(1, date(2026, 11, 3), r) == []
    assert list_segments(99, None, r) == []  # stream tak ada


def test_build_timeline(tmp_path):
    r = str(tmp_path)
    _mk(tmp_path, 2, "2026-11-02_10-00-00-000000.mp4")
    tl = build_timeline(2, date(2026, 11, 2), r)
    assert tl["date"] == "2026-11-02"
    assert len(tl["entries"]) == 1
    assert tl["entries"][0]["has_event"] is False
    assert tl["events"] == []


def test_find_next_playable(tmp_path):
    r = str(tmp_path)
    _mk(tmp_path, 3, "2026-11-02_10-00-00-000000.mp4")
    _mk(tmp_path, 3, "2026-11-02_10-20-00-000000.mp4")

    # di dalam segmen -> segmen itu, waktu = after
    seg, t = find_next_playable(3, datetime(2026, 11, 2, 10, 5), r)
    assert seg.start.hour == 10 and seg.start.minute == 0
    assert t == datetime(2026, 11, 2, 10, 5)

    # di antara segmen -> segmen berikut
    seg, t = find_next_playable(3, datetime(2026, 11, 2, 10, 15), r)
    assert seg.start.hour == 10 and seg.start.minute == 20 and t == seg.start

    # setelah semua -> None
    assert find_next_playable(3, datetime(2026, 11, 5), r) is None


def test_list_dates(tmp_path):
    r = str(tmp_path)
    _mk(tmp_path, 4, "2026-11-02_10-00-00-000000.mp4")
    _mk(tmp_path, 4, "2026-11-01_10-00-00-000000.mp4")
    assert list_dates(4, r) == ["2026-11-01", "2026-11-02"]


async def test_apply_retention_hapus_yang_lama(db_session, tmp_path):
    r = str(tmp_path)
    s = Stream(
        name="Cam",
        rtsp_url="rtsp://x",
        is_active=True,
        recording_enabled=True,
        retention_days=1,
    )
    db_session.add(s)
    await db_session.commit()

    old = _mk(tmp_path, s.id, "2026-10-30_10-00-00-000000.mp4")
    now_dt = datetime.now()
    new_name = now_dt.strftime("%Y-%m-%d_%H-%M-%S-000000.mp4")
    new = _mk(tmp_path, s.id, new_name)
    # buat file "baru" segar agar tak terhapus karena mtime
    now = now_dt.timestamp()
    os.utime(new, (now, now))

    # ubah nama file lama jadi 5 hari lalu agar pasti kedaluwarsa
    five_ago = now_dt - timedelta(days=5)
    old_name = five_ago.strftime("%Y-%m-%d_%H-%M-%S-000000.mp4")
    os.rename(old, os.path.join(str(tmp_path), f"stream_{s.id}", old_name))

    n = await apply_retention(db_session, r)
    assert n == 1
    remaining = list_segments(s.id, None, r)
    assert len(remaining) == 1
    assert remaining[0].name == new_name
