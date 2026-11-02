"""Manajemen akun Google Drive: cache client, resolusi akun per kamera.

Resolusi untuk satu kamera (resolve_drive_account):
  streams.drive_account_id -> akun itu (bila connected)
  NULL -> akun is_default (bila connected)
  tidak ada -> None (Drive nonaktif; atau fallback legacy token.json
  bila instalasi satu-akun lama belum migrasi — lihat uploader_for_stream).
"""

import logging
import os
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.drive import DriveUploader

log = logging.getLogger("netravision.drive")

_clients: dict[str, "DriveUploader"] = {}


def clear_drive_client_cache(account_id) -> None:
    """Buang client cache akun (dipakai setelah reauth/hapus)."""
    _clients.pop(str(account_id), None)


async def get_drive_client(account_id, db):
    """Client Drive ter-cache untuk satu akun (token DB terenkripsi)."""
    from app.services.drive import AccountCreds, DriveUploader

    key = str(account_id)
    if key in _clients:
        return _clients[key]
    from sqlalchemy import select

    from app.models.drive import DriveAccount

    acc = (
        await db.execute(select(DriveAccount).where(DriveAccount.id == uuid.UUID(key)))
    ).scalars().first()
    if acc is None or not acc.token_encrypted:
        raise RuntimeError(f"akun Drive {key} tidak ada / belum terhubung")
    from app.core.drive_tokens import decrypt_token, encrypt_token

    creds = AccountCreds(
        id=key,
        token=decrypt_token(acc.token_encrypted),
        root_folder_id=acc.root_folder_id,
        is_default=acc.is_default,
    )

    async def _save(token_json: str):
        """Simpan token hasil refresh Google kembali ke DB (terenkripsi)."""
        import json as _json

        from app.db.session import get_session_factory

        async with get_session_factory()() as s:
            row = await s.get(DriveAccount, uuid.UUID(key))
            if row is not None:
                row.token_encrypted = encrypt_token(_json.loads(token_json))
                await s.commit()

    up = DriveUploader(account=creds, save_token=_save)
    _clients[key] = up
    return up


async def resolve_drive_account(db, stream):
    """Akun Drive untuk kamera, atau None bila Drive nonaktif."""
    from sqlalchemy import select

    from app.models.drive import DriveAccount

    if stream.drive_account_id:
        acc = await db.get(DriveAccount, stream.drive_account_id)
        if acc is not None and acc.connected:
            return acc
        log.warning(
            "drive: akun %s kamera %s tidak connected — Drive nonaktif",
            stream.drive_account_id, stream.id,
        )
        return None
    acc = (
        await db.execute(
            select(DriveAccount).where(DriveAccount.is_default.is_(True))
        )
    ).scalars().first()
    return acc if acc is not None and acc.connected else None


def _legacy_uploader(settings=None):
    from app.services.drive import DriveUploader

    if "legacy" not in _clients:
        _clients["legacy"] = DriveUploader(settings)
    return _clients["legacy"]


async def uploader_for_stream(db, stream):
    """DriveUploader untuk satu kamera, atau None bila Drive nonaktif."""
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.drive_enabled or stream.storage_mode not in ("drive", "both"):
        return None
    acc = await resolve_drive_account(db, stream)
    if acc is not None:
        try:
            return await get_drive_client(acc.id, db)
        except Exception as e:  # noqa: BLE001
            log.warning("drive: client akun %s gagal: %s", acc.id, e)
            return None
    # Backward compat: instalasi satu-akun lama (token.json di disk).
    if os.path.exists(settings.drive_token_file):
        return _legacy_uploader(settings)
    return None


async def active_uploaders(db) -> dict:
    """Semua uploader aktif: tiap akun connected + legacy bila tak ada akun."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models.drive import DriveAccount

    settings = get_settings()
    accs = (
        await db.execute(
            select(DriveAccount).where(DriveAccount.status == "connected")
        )
    ).scalars().all()
    out: dict = {}
    for acc in accs:
        if not acc.token_encrypted:
            continue
        try:
            out[str(acc.id)] = await get_drive_client(acc.id, db)
        except Exception as e:  # noqa: BLE001
            log.warning("drive: akun %s (%s) dilewati: %s", acc.id, acc.name, e)
    if not out and os.path.exists(settings.drive_token_file):
        out["legacy"] = _legacy_uploader(settings)
    return out
