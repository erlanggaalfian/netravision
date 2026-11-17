"""Model lain: ad_config, system_settings, audit_logs.

2.10: DetectionEvent dan Alert (tabel detection_events dan alerts,
0 baris, tanpa writer/reader; modul detektor Fase 6 belum pernah
dibangun) dihapus migrasi 0029.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.users import TimestampMixin


class AdConfig(Base):
    """Konfigurasi iklan/banner (dipertahankan dari v2.0). Satu baris per key."""

    __tablename__ = "ad_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 2.20: samakan dengan TimestampMixin; sebelumnya AdConfig tidak
    # punya created_at.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SystemSetting(Base, TimestampMixin):
    """Pengaturan sistem key-value (mis. kredensial internal).

    Satu baris per key. Dipakai untuk MEDIAMTX_API_PASSWORD: dibuat
    sekali saat deploy / install pertama, disimpan di database (bukan
    .env), dibaca backend saat startup dan dipakai deploy untuk
    menghasilkan deploy/mediamtx.yml. Nilai adalah rahasia, jangan
    pernah dikembalikan lewat API.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(String(512), nullable=False)


class AuditLog(Base):
    """Jejak audit aksi admin (wajib — temuan audit keamanan v2.0).

    2.12: dibaca lewat GET /admin/audit-logs (routers/admin_audit.py)
    dan di-retensi 90 hari oleh prune_audit_logs (core/audit.py).
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        # 2.12: filter yang dipakai retensi/pembacaan audit.
        Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
        Index("ix_audit_logs_resource_created", "resource", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
