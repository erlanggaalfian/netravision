"""Test fungsi murni skrip deploy/migrate-v2.py (tanpa DB sungguhan)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "migrate_v2",
    Path(__file__).parent.parent.parent.parent / "deploy" / "migrate-v2.py",
)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_sha256_hex():
    assert mig.sha256_hex("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_map_role():
    assert mig.map_role("super_admin") == "admin"
    assert mig.map_role("admin") == "admin"
    assert mig.map_role("user") == "user"
    assert mig.map_role("guest") == "guest"
    assert mig.map_role("aneh") == "user"
    assert mig.map_role(None) == "user"


def test_parse_coords():
    assert mig.parse_coords("-6.2,106.8") == (-6.2, 106.8)
    assert mig.parse_coords("") == (None, None)
    assert mig.parse_coords(None) == (None, None)
    assert mig.parse_coords("bukan-koordinat") == (None, None)
    assert mig.parse_coords("91,181") == (None, None)  # di luar rentang


def test_ttl_mnt():
    assert mig.ttl_mnt(300) == 5
    assert mig.ttl_mnt(3600) == 60
    assert mig.ttl_mnt(None) == 5  # default v2.0 = 300 detik
    assert mig.ttl_mnt(0) == 1


def test_map_user_bcrypt_disalin():
    h = "$2b$12$" + "x" * 53
    m = mig.map_user(
        {"id": 1, "username": "admin", "password_hash": h, "role": "super_admin"}
    )
    assert m["password_hash"] == h  # JANGAN di-re-hash
    assert m["role"] == "admin"


def test_map_stream():
    m = mig.map_stream(
        {
            "id": 7, "name": "Cam", "rtsp_url": "rtsp://x/1",
            "group_name": "Gedung", "coordinates": "-6.2,106.8",
            "is_active": 1, "record_enabled": 1, "record_retention_days": 14,
        }
    )
    assert m["main_url"] == "rtsp://x/1"
    assert m["rtsp_url"] == "rtsp://x/1"
    assert m["latitude"] == -6.2 and m["longitude"] == 106.8
    assert m["recording_enabled"] is True
    assert m["retention_days"] == 14


def test_map_api_key():
    m = mig.map_api_key(
        {
            "id": 3, "key_value": "RAHASIA", "client_name": "Mitra",
            "allowed_domain": "mitra.id", "secret_pass": "",
            "is_active": 1, "embed_timeout_seconds": 300,
        }
    )
    assert m["key_hash"] == mig.sha256_hex("RAHASIA")
    assert m["name"] == "Mitra"
    assert m["domain_lock"] == "mitra.id"
    assert m["password_hash"] is None
    assert m["session_ttl_mnt"] == 5
    assert m["_secret_note"] == "tanpa-password"


def test_map_api_key_bcrypt_secret_disalin():
    h = "$2b$12$" + "y" * 53
    m = mig.map_api_key(
        {
            "id": 4, "key_value": "K2", "client_name": "X",
            "allowed_domain": None, "secret_pass": h,
            "is_active": 1, "embed_timeout_seconds": 600,
        }
    )
    assert m["password_hash"] == h
    assert m["_secret_note"] == "bcrypt-ok"


def test_map_api_key_legacy_secret_ditandai():
    m = mig.map_api_key(
        {
            "id": 5, "key_value": "K3", "client_name": "Y",
            "allowed_domain": None, "secret_pass": "plaintext-lama",
            "is_active": 1, "embed_timeout_seconds": 300,
        }
    )
    assert m["password_hash"] is None  # tidak bisa dipakai langsung; wajib rotasi
    assert m["_secret_note"] == "legacy-plaintext-butuh-rotasi"


def test_map_access_log():
    m = mig.map_access_log(
        {
            "id": 9, "api_key_id": 3, "camera_id": 7, "status": "denied",
            "deny_reason": "Domain tidak diizinkan", "ip_address": "1.2.3.4",
            "user_agent": "ua", "accessed_at": None,
        }
    )
    assert m["stream_id"] == 7
    assert m["action"].startswith("v2:denied")


def test_map_ad_config():
    rows = mig.map_ad_config({"id": 1, "marquee_text": "Halo", "scroll_speed": 5})
    keys = {r["key"] for r in rows}
    assert "v2_marquee_text" in keys
    assert "v2_scroll_speed" in keys
    assert "id" not in keys and "v2_id" not in keys
