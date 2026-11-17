"""Model hak akses: user_stream_access, stream_permissions, stream_admin_grants."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.users import TimestampMixin


class UserStreamAccess(Base, TimestampMixin):
    """Hak akses kamera per pengguna (pengganti user_cctv_access v2.0)."""

    __tablename__ = "user_stream_access"
    __table_args__ = (
        UniqueConstraint("user_id", "stream_id"),
        # 2.6: unique (user_id, stream_id) tidak melayani filter stream_id
        # saja (get_sharing, DELETE per kamera).
        Index("ix_user_stream_access_stream_id", "stream_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 2.10: can_control (PTZ) tidak pernah dibaca di luar model ini
    # (kolom mati), dihapus migrasi 0029 bersama kolom mati lain.
    # Paritas v2.0 (boleh_playback): share stream saja (False) atau
    # stream + playback (True). Default True agar share lama tidak berubah.
    can_playback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    # 2.16: relasi many-to-one.
    user = relationship("User", lazy="selectin")
    stream = relationship("Stream", lazy="selectin")


class StreamPermission(Base, TimestampMixin):
    """Hak akses kamera berbasis peran (role) atau pengguna tertentu.

    2.8: baris warisan dengan user_id terisi dan role NULL (17 baris
    di produksi per 2026-11-17) TIDAK dibaca jalur kode mana pun;
    _check_camera_access dan get_role_access mensyaratkan
    user_id IS NULL. Baris itu dihapus migrasi 0029, dan CHECK
    ck_stream_permissions_user_row_needs_role di bawah mencegah
    baris mati seperti itu dibuat lagi.
    """

    __tablename__ = "stream_permissions"
    __table_args__ = (
        # 2.5: cek akses panas memfilter (stream_id, role, user_id IS NULL).
        Index(
            "ix_stream_permissions_stream_role",
            "stream_id",
            "role",
            postgresql_where="user_id IS NULL",
        ),
        # 2.5: cegah baris peran ganda. NULLS NOT DISTINCT supaya dua
        # baris (stream_id, role, NULL) tetap dianggap duplikat.
        UniqueConstraint(
            "stream_id",
            "role",
            "user_id",
            name="uq_stream_permissions_stream_role_user",
            postgresql_nulls_not_distinct=True,
        ),
        # 2.15: role hanya boleh salah satu nilai ini (NULL = baris
        # warisan per-user, lolos CHECK karena CHECK benar untuk NULL).
        CheckConstraint(
            "role IN ('admin', 'user', 'guest')",
            name="ck_stream_permissions_role",
        ),
        # 2.8: baris per-user tanpa role adalah baris mati (tidak ada
        # pembaca yang menerima user_id terisi dan role NULL). Cegah
        # dibuat lagi; baris lama bentuk ini dihapus migrasi 0029.
        # Baris per-user DENGAN role tetap lolos (dipakai tes unique
        # 2.5), hanya bentuk matinya yang ditolak.
        CheckConstraint(
            "user_id IS NULL OR role IS NOT NULL",
            name="ck_stream_permissions_user_row_needs_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)  # admin|user|guest
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 2.10: can_download tidak pernah dibaca di luar model ini (kolom
    # mati), dihapus migrasi 0029.
    # Paritas v2.0: izin membuka rekaman dipisah dari izin menonton live.
    # Seseorang dapat diberi siaran langsung tanpa riwayat rekamannya.
    can_playback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    # 2.16: relasi many-to-one.
    stream = relationship("Stream", lazy="selectin")
    user = relationship("User", lazy="selectin")


class StreamAdminGrant(Base, TimestampMixin):
    """Grant admin per kamera (admin dapat mengelola kamera tertentu saja).

    Paritas v2.0 (StreamAdminGrantModel): can_view dan can_playback
    dipisah persis seperti pemberian kepada User; can_reshare
    mengizinkan Admin meneruskan kamera itu kepada bawahannya.
    can_manage sudah tidak dipakai di v2.0 (kolom mati), dihapus
    migrasi 0029.
    """

    __tablename__ = "stream_admin_grants"
    __table_args__ = (
        UniqueConstraint("stream_id", "admin_id"),
        # 2.6: unique (stream_id, admin_id) tidak melayani query per
        # admin_id saja (daftar grant satu admin).
        Index("ix_stream_admin_grants_admin_id", "admin_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # 2.10: can_manage dinyatakan "sudah tidak dipakai di v2.0" dan
    # masih ditulis True serta dikembalikan mentah di API; kolom mati,
    # dihapus migrasi 0029 (referensi di admin_streams.py dan
    # admin_users.py dihapus koordinator, lihat laporan Area A).
    can_view: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    can_playback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    can_reshare: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # Admin yang memberikan grant ini (paritas v2.0: granted_by —
    # admin hanya boleh menyentuh pemberian yang ia buat sendiri).
    granted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )

    # 2.16: relasi many-to-one.
    stream = relationship("Stream", lazy="selectin")
    admin = relationship("User", foreign_keys=[admin_id], lazy="selectin")
