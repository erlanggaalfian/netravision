"""Riwayat kegagalan tambah kamera + hasil probe RTSP terakhir.

Dipakai halaman Diagnostik admin (GET /admin/diagnostics/camera-add):
riwayat kegagalan terakhir per kamera dan hasil probe RTSP terakhir
per kamera. Tidak menyimpan kredensial apa pun: hanya kode, judul,
penyebab, dan langkah perbaikan (sudah di-redact di classifier).
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CameraAddFailure(Base):
    """Satu kegagalan tambah kamera (atau registrasi MediaMTX-nya).

    stream_id NULL bila kamera belum sempat tersimpan (mis. probe
    RTSP gagal sebelum insert). Retensi tidak diatur di sini; tabel
    ini kecil dan hanya dibaca 20 baris terakhir.
    """

    __tablename__ = "camera_add_failures"
    __table_args__ = (
        Index("ix_camera_add_failures_stream_created", "stream_id", "created_at"),
        Index("ix_camera_add_failures_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    judul: Mapped[str] = mapped_column(String(256), nullable=False)
    penyebab: Mapped[str] = mapped_column(Text, nullable=False)
    langkah: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CameraProbeResult(Base):
    """Hasil probe RTSP terakhir satu kamera (upsert per stream_id)."""

    __tablename__ = "camera_probe_results"

    stream_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_name: Mapped[str] = mapped_column(String(128), nullable=False)
    main_status: Mapped[str] = mapped_column(String(32), nullable=False)
    sub_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
