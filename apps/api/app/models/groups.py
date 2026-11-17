"""Model grup kamera (grup wilayah): StreamGroup + relasi GroupStream.

Menggantikan kolom bebas `streams.group_name` v2.0 dengan entitas grup yang
proper (many-to-many kamera <-> grup). Migrasi: alembic 0002.
"""

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.users import TimestampMixin


class StreamGroup(Base, TimestampMixin):
    """Grup kamera, mis. 'Gedung A', 'Parkir'."""

    __tablename__ = "stream_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)


class GroupStream(Base, TimestampMixin):
    """Relasi grup <-> kamera."""

    __tablename__ = "group_streams"
    __table_args__ = (
        UniqueConstraint("group_id", "stream_id"),
        # 2.6: unique (group_id, stream_id) tidak melayani lookup per
        # stream_id saja (_refresh_stream_group_names).
        Index("ix_group_streams_stream_id", "stream_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("stream_groups.id", ondelete="CASCADE")
    )
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE")
    )

    # 2.16: relasi many-to-one.
    group = relationship("StreamGroup", lazy="selectin")
    stream = relationship("Stream", lazy="selectin")
