"""Tes system_settings: password MediaMTX di database (migrasi 0028).

Sejak migrasi 0030 nilai disimpan TERENKRIPSI (Fernet,
DRIVE_TOKEN_KEY), bukan plaintext. Tes di sini memakai kunci
Fernet sementara (pola drive_env di test_drive_accounts.py).
"""

import re

import pytest
from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.models.misc import SystemSetting
from app.services.mediamtx import get_mediamtx
from app.services.system_settings import (
    MEDIAMTX_PASSWORD_KEY,
    decrypt_system_setting_value,
    encrypt_system_setting_value,
    ensure_mediamtx_password,
    generate_mediamtx_password,
    get_mediamtx_password,
    render_mediamtx_yml,
    set_mediamtx_password_cache,
)
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _clear_cache():
    set_mediamtx_password_cache(None)
    yield
    set_mediamtx_password_cache(None)


@pytest.fixture(autouse=True)
def _drive_key(monkeypatch):
    """DRIVE_TOKEN_KEY sementara untuk enkripsi nilai (0030)."""
    monkeypatch.setenv("DRIVE_TOKEN_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_generate_mediamtx_password_hex_48():
    pw = generate_mediamtx_password()
    assert re.fullmatch(r"[0-9a-f]{48}", pw), pw
    assert generate_mediamtx_password() != pw


def test_encrypt_decrypt_roundtrip():
    blob = encrypt_system_setting_value("a" * 48)
    assert blob != "a" * 48
    assert decrypt_system_setting_value(blob) == "a" * 48


def test_decrypt_melewatkan_plaintext_lama():
    # Nilai warisan sebelum migrasi 0030: dikembalikan apa adanya.
    assert decrypt_system_setting_value("a" * 48) == "a" * 48


async def test_ensure_buat_lalu_pakai_lagi(db_session):
    pw1 = await ensure_mediamtx_password(db_session)
    assert re.fullmatch(r"[0-9a-f]{48}", pw1)
    assert get_mediamtx_password() == pw1
    # Panggilan kedua memakai yang sudah tersimpan (bukan buat baru).
    pw2 = await ensure_mediamtx_password(db_session)
    assert pw2 == pw1
    res = await db_session.execute(select(SystemSetting))
    rows = res.scalars().all()
    assert len(rows) == 1
    assert rows[0].key == MEDIAMTX_PASSWORD_KEY
    # 0030: yang tersimpan di DB terenkripsi, bukan plaintext.
    assert rows[0].value != pw1
    assert decrypt_system_setting_value(rows[0].value) == pw1


async def test_ensure_tidak_timpa_yang_sudah_ada(db_session):
    db_session.add(
        SystemSetting(key=MEDIAMTX_PASSWORD_KEY, value="a" * 48)
    )
    await db_session.commit()
    assert await ensure_mediamtx_password(db_session) == "a" * 48


async def test_ensure_meningkatkan_plaintext_lama_ke_terenkripsi(db_session):
    """Baris warisan plaintext dibaca, lalu di-upgrade di tempat."""
    db_session.add(
        SystemSetting(key=MEDIAMTX_PASSWORD_KEY, value="a" * 48)
    )
    await db_session.commit()
    assert await ensure_mediamtx_password(db_session) == "a" * 48
    res = await db_session.execute(
        select(SystemSetting.value).where(
            SystemSetting.key == MEDIAMTX_PASSWORD_KEY
        )
    )
    stored = res.scalar_one()
    assert stored != "a" * 48
    assert decrypt_system_setting_value(stored) == "a" * 48


async def test_ensure_gagal_tanpa_drive_token_key(db_session, monkeypatch):
    """Tanpa DRIVE_TOKEN_KEY: gagal keras, bukan simpan plaintext."""
    monkeypatch.setenv("DRIVE_TOKEN_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DRIVE_TOKEN_KEY"):
            await ensure_mediamtx_password(db_session)
    finally:
        get_settings.cache_clear()
    res = await db_session.execute(select(SystemSetting))
    assert res.scalars().all() == []


def test_render_mediamtx_yml():
    template = "user: netravision\npass: __MEDIAMTX_API_PASSWORD__\n"
    out = render_mediamtx_yml(template, "b" * 48)
    assert "b" * 48 in out
    assert "__MEDIAMTX_API_PASSWORD__" not in out
    with pytest.raises(ValueError):
        render_mediamtx_yml("tanpa placeholder", "b" * 48)


def test_get_mediamtx_pakai_password_db_cache():
    import base64

    set_mediamtx_password_cache("c" * 48)
    client = get_mediamtx()
    # httpx BasicAuth hanya menyimpan header "Basic base64(user:pass)".
    assert client._client.auth is not None
    header = client._client.auth._auth_header
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header[len("Basic ") :]).decode()
    assert decoded == "netravision:" + "c" * 48
