"""Model hak akses: user_stream_access, stream_permissions, stream_admin_grants."""

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.users import TimestampMixin


class UserStreamAccess(Base, TimestampMixin):
    """Hak akses kamera per pengguna (pengganti user_cctv_access v2.0)."""

    __tablename__ = "user_stream_access"
    __table_args__ = (UniqueConstraint("user_id", "stream_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # PTZ


class StreamPermission(Base, TimestampMixin):
    """Hak akses kamera berbasis peran (role) atau pengguna tertentu."""

    __tablename__ = "stream_permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)  # admin|user|guest
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_download: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class StreamAdminGrant(Base, TimestampMixin):
    """Grant admin per kamera (admin dapat mengelola kamera tertentu saja)."""

    __tablename__ = "stream_admin_grants"
    __table_args__ = (UniqueConstraint("stream_id", "admin_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    can_manage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
