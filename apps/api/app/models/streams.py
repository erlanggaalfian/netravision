"""Model: streams (pengganti cctv_streams v2.0 + kolom baru v3.0)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.users import TimestampMixin


class Stream(Base, TimestampMixin):
    """Kamera/stream. main_url/sub_url disimpan eksplisit (hasil brand resolver),
    bukan di-derive ulang setiap request."""

    __tablename__ = "streams"
    __table_args__ = (
        # 2.18: is_active dipakai hampir semua daftar; (storage_mode,
        # recording_enabled) dipakai uploader/retensi/cleanup.
        Index("ix_streams_is_active", "is_active"),
        Index("ix_streams_storage_recording", "storage_mode", "recording_enabled"),
        # 0030: indeks FK yang dipakai query panas (daftar kamera per
        # admin, hapus akun/folder Drive), sebelumnya seq scan.
        # ix_streams_group_name sengaja TIDAK dideklarasikan: kolom
        # group_name tidak pernah difilter (hanya dibaca untuk
        # tampilan/path); indeksnya di-drop migrasi 0030.
        Index("ix_streams_owner_id", "owner_id"),
        Index("ix_streams_created_by", "created_by"),
        Index("ix_streams_drive_account_id", "drive_account_id"),
        Index("ix_streams_drive_folder_id", "drive_folder_id"),
        # 2.15: storage_mode hanya boleh salah satu dari tiga nilai ini.
        CheckConstraint(
            "storage_mode IN ('local', 'drive', 'both')",
            # Nama pendek, lihat komentar yang sama di models/users.py
            # (naming convention Base merender ck_streams_storage_mode).
            name="storage_mode",
        ),
        # 0030: retensi negatif membuat cutoff di masa depan dan bisa
        # menghapus segmen yang baru dibuat.
        CheckConstraint(
            "retention_days >= 0",
            name="retention_days_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rtsp_url: Mapped[str] = mapped_column(String(512), nullable=False)

    # Brand-aware resolver (v3.0): ONVIF -> template brand -> generik.
    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    main_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sub_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    onvif_profile: Mapped[str | None] = mapped_column(String(128), nullable=True)

    group_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # grup wilayah
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rekaman: lokal | drive | both (Google Drive opsional, per §3.8 blueprint).
    recording_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    storage_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="local")

    # Disk tujuan rekaman per kamera (mount point, mis. "/mnt/disk2").
    # Kosong/NULL = pakai recordings_dir default (perilaku lama).
    # 2.13: sentinel ganda '' vs NULL dihapus; kosong = NULL saja.
    record_disk: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)

    # Pemilik kamera (dikelola via POST /api/admin/streams/{id}/owner).
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Siapa yang memasang kamera (paritas v2.0: dasar masking RTSP).
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )

    # Akun Google Drive untuk kamera ini (NULL = akun default).
    # Backward compat: instalasi satu-akun lama (token.json) tetap jalan
    # tanpa baris drive_accounts, lihat app/services/drive.py.
    drive_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("drive_accounts.id", ondelete="SET NULL"), nullable=True
    )

    # Folder Google Drive tujuan (mode folder-link, multi-tautan).
    # NULL = folder pertama (default). Diatur per kamera di modal kamera
    # bila storage_mode = "drive"/"both" dan ada >1 folder.
    drive_folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("google_drive_folders.id", ondelete="SET NULL"),
        nullable=True, default=None,
    )
