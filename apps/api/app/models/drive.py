"""Model: drive_accounts (Google Drive multi-akun, v3.0).

Satu baris = satu akun Google yang terhubung via OAuth2. Token OAuth
disimpan terenkripsi (Fernet, app/core/drive_tokens.py) - tidak pernah
plaintext di DB. Kamera memilih akun via streams.drive_account_id;
NULL = pakai akun default (is_default).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RcloneRemote(Base):
    """Satu remote rclone di .rclone.conf (multi-akun Google Drive).

    remote_name adalah nama section di conf (mis. gdrive, gdrive-2) dan
    dipakai sebagai `rclone:{remote}` pada record_disk: rekaman ditulis
    lokal dulu (staging), lalu di-upload ke remote itu. JANGAN pakai
    `rclone mount` (FUSE) sebagai jalur utama.
    """

    __tablename__ = "rclone_remotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    remote_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Token OAuth rclone (JSON) terenkripsi Fernet (DRIVE_TOKEN_KEY).
    # Sumber kebenaran token: bila .rclone.conf hilang, API membangun
    # ulang conf dari kolom ini saat start. NULL = remote lama, perlu
    # dihubungkan ulang sekali.
    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DriveAccount(Base):
    __tablename__ = "drive_accounts"
    # 2.15: status hanya boleh salah satu dari tiga nilai ini.
    # A-1.19: tepat SATU akun default — indeks unik parsial supaya dua
    # POST bersamaan tidak bisa sama-sama jadi default, dan PUT tidak
    # bisa mematikan default terakhir tanpa pengganti (penjaga di
    # router tetap diperlukan untuk pesan error yang jelas).
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'connected', 'error')",
            name="ck_drive_accounts_status",
        ),
        Index(
            "uq_drive_accounts_is_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_folder_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # status: pending | connected | error
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def connected(self) -> bool:
        return self.status == "connected" and bool(self.token_encrypted)


class DriveUpload(Base):
    """Jejak segmen yang sudah ter-upload ke Google Drive (via rclone copyto).

    Mencegah upload ganda antar putaran upload loop.

    2.1: stream_id adalah FK ke streams.id (ON DELETE CASCADE, jadi hapus
    kamera tidak meninggalkan jejak yatim) dan (stream_id, folder_name,
    segment_name) unik, sehingga dua loop yang balapan tidak bisa
    memasukkan jejak ganda; _mark_uploaded memakai INSERT ... ON CONFLICT
    DO NOTHING.
    2.4: indeks komposit (stream_id, uploaded_at) untuk MAX(uploaded_at) /
    status antrean; unique di atas melayani filter (stream_id, folder_name).
    2.9: kolom ini dulu bernama folder_id padahal isinya NAMA folder
    (kunci jalur rclone, bukan ID Drive); diganti nama menjadi
    folder_name supaya tidak berbohong. Nilai tetap nama folder.
    """

    __tablename__ = "drive_uploads"
    __table_args__ = (
        UniqueConstraint(
            "stream_id",
            "folder_name",
            "segment_name",
            name="uq_drive_uploads_stream_folder_segment",
        ),
        Index(
            "ix_drive_uploads_stream_uploaded",
            "stream_id",
            "uploaded_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_name: Mapped[str] = mapped_column(String(64), nullable=False)
    folder_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 2.16: relasi many-to-one ke kamera.
    stream = relationship("Stream", lazy="selectin")


class GoogleDriveFolder(Base):
    """Satu tautan folder Google Drive (mode folder-link + rclone).

    Bisa ada BANYAK baris - tiap baris = satu folder tujuan dengan
    mount rclone-nya sendiri (local_path). Kamera memilih folder via
    streams.drive_folder_id; NULL = folder pertama (default).
    """

    __tablename__ = "google_drive_folders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folder_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    folder_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    folder_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # Mount point rclone untuk folder ini (mis. /mnt/gdrive-cctv).
    # Kosong = pakai env GDRIVE_RECORD_PATH (kompatibel lama).
    local_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Retensi per folder (hari): file .mp4 di folder Drive ini yang lebih
    # tua dari nilai ini dihapus otomatis oleh cleanup_folder_retention.
    # None = tidak ada hapus otomatis per folder.
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Nama remote rclone pemilik folder ini (mis. gdrive). Terisi untuk
    # folder "netravision" yang dibuat otomatis saat akun terhubung;
    # kosong untuk tautan folder manual.
    remote_name: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 2.14/2.20: onupdate supaya updated_at tidak basi bila ada jalur
    # update yang lupa menulisnya manual.
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )
    # 2.13: sentinel ganda '' vs NULL dihapus; kosong = NULL saja.
    updated_by: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
