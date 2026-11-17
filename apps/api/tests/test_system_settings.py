"""Tes system_settings: password MediaMTX di database (migrasi 0028)."""

import re

import pytest

from app.models.misc import SystemSetting
from app.services.mediamtx import get_mediamtx
from app.services.system_settings import (
    MEDIAMTX_PASSWORD_KEY,
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


def test_generate_mediamtx_password_hex_48():
    pw = generate_mediamtx_password()
    assert re.fullmatch(r"[0-9a-f]{48}", pw), pw
    assert generate_mediamtx_password() != pw


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
    assert rows[0].value == pw1


async def test_ensure_tidak_timpa_yang_sudah_ada(db_session):
    db_session.add(
        SystemSetting(key=MEDIAMTX_PASSWORD_KEY, value="a" * 48)
    )
    await db_session.commit()
    assert await ensure_mediamtx_password(db_session) == "a" * 48


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
