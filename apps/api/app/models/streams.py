"""Model: streams (pengganti cctv_streams v2.0 + kolom baru v3.0)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.users import TimestampMixin


class Stream(Base, TimestampMixin):
    """Kamera/stream. main_url/sub_url disimpan eksplisit (hasil brand resolver),
    bukan di-derive ulang setiap request."""

    __tablename__ = "streams"

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
