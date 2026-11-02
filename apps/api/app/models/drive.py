"""Model: drive_accounts (Google Drive multi-akun, v3.0).

Satu baris = satu akun Google yang terhubung via OAuth2. Token OAuth
disimpan terenkripsi (Fernet, app/core/drive_tokens.py) — tidak pernah
plaintext di DB. Kamera memilih akun via streams.drive_account_id;
NULL = pakai akun default (is_default).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriveAccount(Base):
    __tablename__ = "drive_accounts"

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
