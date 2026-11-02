# Catatan Patch RBAC (untuk parent agent)

File ini milik area kerja RBAC (subagent). Berisi perubahan yang TIDAK BOLEH
dikerjakan subagent karena filenya dikunci untuk area lain, tapi DIBUTUHKAN
agar paritas RBAC v2.0 utuh.

## 1. `streams.created_by` (kolom DB + model)

Paritas v2.0: `dipasang_sendiri()` — admin hanya melihat kredensial RTSP
kamera yang ia pasang sendiri. Kolom `streams.created_by` (FK users.id,
nullable) SUDAH ditambahkan di migrasi Alembic `0007_rbac_parity.py`,
tapi `app/models/streams.py` belum punya field-nya (file dikunci).

Patch yang perlu diterapkan di `app/models/streams.py`:

```python
from sqlalchemy import ForeignKey  # tambah import bila belum ada
...
    # Siapa yang memasang kamera (paritas v2.0: dasar masking RTSP).
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )
```

Kode RBAC (`app/core/rbac.py::mask_rtsp_url`) sudah toleran bila kolom
belum ada: memakai `getattr(stream, "created_by", None)` lalu jatuh ke
`owner_id` (persis fallback v2.0).

Juga: saat kamera dibuat/dipasang (POST /api/admin/streams di
`app/routers/admin_streams.py`), isi `created_by` dengan id admin pembuat.

## 2. Satu baris di `GET /api/admin/streams` (`app/routers/admin_streams.py`)

Terapkan masking RTSP pada respons daftar kamera admin:

```python
from app.core.rbac import mask_rtsp_url
...
# di dalam handler GET /api/admin/streams, sebelum return:
for s in streams_out:  # sesuaikan nama variabel lokal
    s.rtsp_url = await mask_rtsp_url(s, admin, db)
```

Aturan (paritas v2.0 `saring_rtsp`): super_admin melihat semua;
admin melihat kredensial hanya untuk kamera pasangannya sendiri atau
via grant `can_manage`; selain itu `rtsp_url` dikosongkan. Non-admin
tidak mencapai endpoint ini.

## 3. Endpoint rekaman: pakai `require_camera_playback_access()`

`app/routers/recordings.py` (file dikunci) masih memakai
`require_camera_access` (cek tonton saja). Agar izin playback terpisah
dari izin live (paritas v2.0 `boleh_playback`), ganti dependency di
endpoint rekaman (segments/timeline/file/stream/playback-url) menjadi:

```python
from app.core.rbac import require_camera_playback_access
...
user: User = Depends(require_camera_playback_access())
```

Kolom `stream_permissions.can_playback` sudah ada (migrasi 0007,
default True untuk data lama — tidak ada perubahan perilaku sebelum
endpoint beralih).
