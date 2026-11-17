"""Model: users (+ refresh_token_hash untuk rotation)."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    """Pengguna. role: super_admin | admin | user | guest (lihat juga
    CHECK ck_users_role; v2.0 hanya mengenal admin | user | guest)."""

    __tablename__ = "users"
    # 2.15: role hanya boleh salah satu dari empat nilai ini (sama
    # dengan VALID_ROLES di routers/admin_users.py).
    __table_args__ = (
        CheckConstraint(
            "role IN ('super_admin', 'admin', 'user', 'guest')",
            name="ck_users_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Apakah banner iklan tampil untuk akun ini (paritas v2.0).
    show_ads: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    # Admin yang membuat akun ini (paritas v2.0: parent_admin_id).
    # Dasar cakupan kelola: admin biasa hanya mengelola akun buatannya.
    parent_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, default=None
    )

    # Kelompok wilayah akun (paritas v2.0). Akun dengan nama grup yang
    # sama saling mengelola; lintas grup tertutup. Kosong = belum
    # berkelompok, hanya Super Admin yang menjangkaunya. Tidak ada
    # hubungannya dengan group_name kamera.
    admin_group: Mapped[str | None] = mapped_column(
        String(60), nullable=True, index=True, default=None
    )

    # SHA-256 dari refresh token aktif. Dibersihkan saat logout, dirotasi
    # setiap refresh dipakai.
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 4.2: jti refresh token aktif (pasangan hash di atas). Dipakai
    # deteksi pemakaian ulang: token yang jti-nya sudah dirotasi keluar
    # dan dipakai lagi di luar grace window menandakan pencurian, dan
    # seluruh keluarga token user itu dicabut.
    refresh_token_jti: Mapped[str | None] = mapped_column(String(32), nullable=True)
