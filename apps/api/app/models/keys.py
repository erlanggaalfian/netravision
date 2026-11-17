"""Model API key embed pihak ketiga + log akses."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.users import TimestampMixin


class ApiKey(Base, TimestampMixin):
    """Kunci API per integrasi. Yang disimpan hanya hash (SHA-256) kuncinya."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    domain_lock: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # TTL token sesi embed (menit). Dibaca endpoint /api/external/*.
    session_ttl_mnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Opsi embed ala v2.0.
    # 2.13: sentinel ganda '' vs NULL dihapus; kosong = NULL saja.
    custom_camera_name: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    include_playback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Opsi iklan per kunci: False -> embed kunci ini tanpa iklan.
    show_ads: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ApiKeyStream(Base):
    """Cakupan kamera per API key (pengganti api_key_cameras v2.0)."""

    __tablename__ = "api_key_streams"
    __table_args__ = (
        UniqueConstraint("api_key_id", "stream_id"),
        # 2.6: unique (api_key_id, stream_id) tidak melayani filter
        # stream_id saja.
        Index("ix_api_key_streams_stream_id", "stream_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"))
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 2.16: relasi many-to-one.
    api_key = relationship("ApiKey", lazy="selectin")
    stream = relationship("Stream", lazy="selectin")


class ApiAccessLog(Base):
    """Catatan setiap akses embed (dipertahankan dari v2.0)."""

    __tablename__ = "api_access_logs"
    # 6.8: list_logs memfilter api_key_id + mengurutkan created_at dan
    # menghitung total per halaman; tanpa indeks ini tiap halaman
    # memindai seluruh tabel log yang tumbuh tanpa batas.
    __table_args__ = (
        Index("ix_api_access_logs_key_created", "api_key_id", "created_at"),
        # 2.7: filter/ringkasan per stream_id (logs_summary GROUP BY
        # api_key_id ikut terbantu indeks key_created di atas).
        Index("ix_api_access_logs_stream_id", "stream_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    api_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    stream_id: Mapped[int | None] = mapped_column(
        ForeignKey("streams.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 2.7: penanda ditolak sebagai kolom boolean, supaya filter status
    # tidak lagi memakai LIKE '%.denied%' (leading %, tak terindeks).
    # Diisi dari action saat _log (external.py); migrasi 0027 mengisi
    # ulang baris lama dari action yang sudah ada.
    is_denied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 2.14: samakan dengan created_at lain: server_default func.now(),
    # bukan datetime.utcnow (naive, deprecated) di sisi Python.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
