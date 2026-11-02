"""Test ringan untuk skrip cutover Fase 5 (scripts/ + deploy/seed_admin.py)."""
# ruff: noqa: E501 — data fixture /proc/net/tcp memang berbaris panjang

import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
DEPLOY_DIR = Path(__file__).resolve().parents[3] / "deploy"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(DEPLOY_DIR))

import preflight  # noqa: E402
import seed_admin  # noqa: E402
import smoke_test  # noqa: E402

# --- preflight: fungsi murni ---

SAMPLE_PROC_NET_TCP = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1 0000000000000000 100 0 0 10 0  # noqa: E501
   1: 0100007F:01BB 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12346 1 0000000000000000 100 0 0 10 0  # noqa: E501
   2: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12347 1 0000000000000000 100 0 0 10 0  # noqa: E501
   3: 00000000:0050 00000000:0000 06 00000000:00000000 00:00000000 00000000     0        0 99999 1 0000000000000000 100 0 0 10 0
"""


def test_hex_port():
    assert preflight.hex_port(80) == "0050"
    assert preflight.hex_port(443) == "01BB"
    assert preflight.hex_port(8189) == "1FFD"


def test_find_listening_inodes():
    found = preflight.find_listening_inodes(SAMPLE_PROC_NET_TCP, {80, 443, 22})
    assert found[80] == ["12345"]      # hanya state 0A (LISTEN); baris 06 diabaikan
    assert found[443] == ["12346"]
    assert found[22] == []


def test_preflight_main_returns_int():
    # main() menjalankan cek sistem nyata; pastikan hanya mengembalikan int.
    # Tidak di-assert isinya karena tergantung environment.
    rc = preflight.main()
    assert isinstance(rc, int)


# --- smoke_test: parsing argumen ---

def test_smoke_parse_args():
    args = smoke_test.parse_args(
        ["--base-url", "http://x:8100", "--username", "admin", "--password", "p"]
    )
    assert args.base_url == "http://x:8100"
    assert args.username == "admin"
    assert args.password == "p"


def test_smoke_parse_args_missing_password():
    with pytest.raises(SystemExit):
        smoke_test.parse_args(["--username", "admin"])


# --- seed_admin: idempoten ---

async def test_seed_admin_idempotent(tmp_path):
    db_file = tmp_path / "seed.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    from app.db.base import Base

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    assert await seed_admin.ensure_admin("admin", "R4h4s1a!", db_url) == "created:super_admin"
    assert await seed_admin.ensure_admin("admin", "R4h4s1a!", db_url) == "exists"


def test_seed_admin_missing_env(monkeypatch, capsys):
    monkeypatch.delenv("NV_ADMIN_USER", raising=False)
    monkeypatch.delenv("NV_ADMIN_PASS", raising=False)
    assert seed_admin.main() == 2
    assert "NV_ADMIN_USER" in capsys.readouterr().err
