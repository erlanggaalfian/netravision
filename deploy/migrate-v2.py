#!/usr/bin/env python3
"""Migrasi sekali-jalan: database v2.0 (MariaDB) -> v3.0 (PostgreSQL).

Sumber : MariaDB v2.0 — koneksi via env V2_DB_HOST/PORT/USER/PASSWORD/NAME
Tujuan : PostgreSQL v3.0 — via env DATABASE_URL (bagian driver +asyncpg diabaikan)

Keamanan/idempotensi:
  - Default --dry-run: hanya menghitung + melaporkan, tanpa menulis apa pun.
  - --apply menolak bila tabel tujuan sudah berisi data, kecuali --force.
  - ID asli dipertahankan (penting untuk relasi); memakai
    ON CONFLICT DO NOTHING + reset sequence setelahnya.
  - Hash password user v2.0 (bcrypt) disalin APA ADANYA — tidak di-re-hash.

Contoh:
  python deploy/migrate-v2.py                      # dry-run
  python deploy/migrate-v2.py --apply              # eksekusi
  python deploy/migrate-v2.py --apply --force      # eksekusi walau tujuan berisi data
"""

import argparse
import hashlib
import json
import os
import sys

# ── fungsi murni (bisa di-unit-test tanpa DB) ─────────────────────────

ROLE_MAP = {"super_admin": "admin", "admin": "admin", "user": "user", "guest": "guest"}


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def map_role(v2_role: str | None) -> str:
    return ROLE_MAP.get((v2_role or "").strip().lower(), "user")


def parse_coords(s: str | None) -> tuple[float | None, float | None]:
    """'lat,lng' -> (lat, lng); gagal -> (None, None)."""
    if not s:
        return None, None
    try:
        lat_s, lng_s = str(s).split(",", 1)
        lat, lng = float(lat_s.strip()), float(lng_s.strip())
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return lat, lng
    except (ValueError, AttributeError):
        pass
    return None, None


def ttl_mnt(embed_timeout_seconds: int | None) -> int:
    """Detik (v2.0) -> menit (v3.0), minimal 1.

    None -> default v2.0 (300 detik) -> 5 menit.
    """
    try:
        return max(1, round(int(embed_timeout_seconds if embed_timeout_seconds is not None else 300) / 60))
    except (TypeError, ValueError):
        return 5


def is_bcrypt_hash(s: str | None) -> bool:
    return bool(s) and s.startswith("$2")


def map_user(r: dict) -> dict:
    return {
        "id": r["id"],
        "username": r["username"],
        "password_hash": r["password_hash"],  # bcrypt v2.0 — salin apa adanya
        "role": map_role(r.get("role")),
        "is_active": True,
        "created_at": r.get("created_at"),
    }


def map_stream(r: dict) -> dict:
    lat, lng = parse_coords(r.get("coordinates"))
    return {
        "id": r["id"],
        "name": r["name"],
        "rtsp_url": r["rtsp_url"],
        "main_url": r["rtsp_url"],
        "group_name": r.get("group_name") or "Default",
        "latitude": lat,
        "longitude": lng,
        "is_active": bool(r.get("is_active", 1)),
        "recording_enabled": bool(r.get("record_enabled", 0)),
        "retention_days": r.get("record_retention_days") or 7,
        "created_at": r.get("created_at"),
    }


def map_user_access(r: dict) -> dict:
    return {"user_id": r["user_id"], "stream_id": r["stream_id"], "can_view": True}


def map_permission(r: dict) -> dict:
    return {
        "stream_id": r["stream_id"],
        "user_id": r["user_id"],
        "can_view": bool(r.get("can_view", 1)),
        "can_download": bool(r.get("can_playback", 0)),
    }


def map_admin_grant(r: dict) -> dict:
    return {
        "stream_id": r["stream_id"],
        "admin_id": r["admin_id"],
        "can_manage": bool(r.get("can_manage", 0)),
    }


def map_api_key(r: dict) -> dict:
    """key_value plaintext v2.0 -> key_hash SHA-256 v3.0.

    secret_pass: bila sudah bcrypt -> salin; bila plaintext legacy -> beri
    tanda agar admin merotasi (disimpan apa adanya, verifikasi v3.0 hanya
    bcrypt — lihat laporan migrasi).
    """
    secret = r.get("secret_pass") or ""
    if is_bcrypt_hash(secret):
        password_hash = secret
        secret_note = "bcrypt-ok"
    elif secret.strip():
        password_hash = None  # plaintext legacy: wajib dirotasi via panel admin
        secret_note = "legacy-plaintext-butuh-rotasi"
    else:
        password_hash = None
        secret_note = "tanpa-password"
    return {
        "id": r["id"],
        "name": r.get("client_name") or f"kunci-{r['id']}",
        "key_hash": sha256_hex(r["key_value"]),
        "domain_lock": r.get("allowed_domain") or None,
        "password_hash": password_hash,
        "expires_at": None,
        "is_active": bool(r.get("is_active", 1)),
        "session_ttl_mnt": ttl_mnt(r.get("embed_timeout_seconds")),
        "_secret_note": secret_note,  # hanya untuk laporan, tidak ditulis ke DB
    }


def map_api_key_stream(r: dict) -> dict:
    return {"api_key_id": r["api_key_id"], "stream_id": r["camera_id"]}


def map_access_log(r: dict) -> dict:
    action = f"v2:{r.get('status') or 'hit'}"
    if r.get("deny_reason"):
        action = f"{action}:{r['deny_reason']}"[:64]
    return {
        "id": r["id"],
        "api_key_id": r.get("api_key_id"),
        "stream_id": r.get("camera_id"),
        "action": action,
        "ip": r.get("ip_address"),
        "user_agent": r.get("user_agent"),
        "created_at": r.get("accessed_at"),
    }


AD_CONFIG_SKIP = {"id"}


def map_ad_config(r: dict) -> list[dict]:
    """Satu baris lebar v2.0 -> banyak baris key/value JSONB v3.0."""
    rows = []
    for k, v in r.items():
        if k in AD_CONFIG_SKIP or v is None:
            continue
        rows.append({"key": f"v2_{k}", "value": v})
    return rows


# ── definisi tabel ────────────────────────────────────────────────────
# (v2_tabel, v3_tabel, mapper, kolom_insert, conflict)

TABLES = [
    ("users", "users", map_user,
     ["id", "username", "password_hash", "role", "is_active", "created_at"], "id"),
    ("cctv_streams", "streams", map_stream,
     ["id", "name", "rtsp_url", "main_url", "group_name", "latitude", "longitude",
      "is_active", "recording_enabled", "retention_days", "created_at"], "id"),
    ("user_cctv_access", "user_stream_access", map_user_access,
     ["user_id", "stream_id", "can_view"], None),
    ("stream_permissions", "stream_permissions", map_permission,
     ["stream_id", "user_id", "can_view", "can_download"], None),
    ("stream_admin_grants", "stream_admin_grants", map_admin_grant,
     ["stream_id", "admin_id", "can_manage"], None),
    ("api_keys", "api_keys", map_api_key,
     ["id", "name", "key_hash", "domain_lock", "password_hash", "expires_at",
      "is_active", "session_ttl_mnt"], "id"),
    ("api_key_cameras", "api_key_streams", map_api_key_stream,
     ["api_key_id", "stream_id"], None),
    ("api_access_logs", "api_access_logs", map_access_log,
     ["id", "api_key_id", "stream_id", "action", "ip", "user_agent", "created_at"], "id"),
]

SEQ_TABLES = ["users", "streams", "api_keys", "api_access_logs"]


# ── koneksi (import lazy agar fungsi murni bisa di-test tanpa driver) ─

def _src_conn():
    import pymysql

    return pymysql.connect(
        host=os.getenv("V2_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("V2_DB_PORT", "3306")),
        user=os.getenv("V2_DB_USER", "root"),
        password=os.getenv("V2_DB_PASSWORD", ""),
        database=os.getenv("V2_DB_NAME", "cctv_monitoring"),
        charset="utf8mb4",
        cursorclass=__import__("pymysql.cursors", fromlist=["DictCursor"]).DictCursor,
    )


def _dst_conn():
    import psycopg

    url = os.getenv("DATABASE_URL", "")
    url = url.replace("+asyncpg", "").replace("+psycopg", "")
    if not url:
        raise SystemExit("env DATABASE_URL belum diset")
    return psycopg.connect(url)


def _table_count(cur, table: str) -> int:
    cur.execute(f'SELECT COUNT(*) AS c FROM "{table}"')
    return cur.fetchone()["c"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrasi DB v2.0 (MariaDB) -> v3.0 (PostgreSQL)")
    ap.add_argument("--apply", action="store_true", help="eksekusi penulisan (default: dry-run)")
    ap.add_argument("--force", action="store_true", help="lanjut walau tujuan sudah berisi data")
    args = ap.parse_args()

    src = _src_conn()
    dst = _dst_conn()
    try:
        s_cur = src.cursor()
        d_cur = dst.cursor()

        # ── baca ──
        data: dict[str, list[dict]] = {}
        for v2_table, _, _, _, _ in TABLES:
            try:
                s_cur.execute(f"SELECT * FROM `{v2_table}`")
                data[v2_table] = list(s_cur.fetchall())
            except Exception as e:  # tabel opsional (mis. hasil migrasi parsial)
                print(f"! baca {v2_table}: {e} -> dilewati")
                data[v2_table] = []
        # ad_config ditangani khusus (1 baris -> N baris)
        try:
            s_cur.execute("SELECT * FROM `ad_config` LIMIT 1")
            ad_row = s_cur.fetchone()
        except Exception as e:
            print(f"! baca ad_config: {e} -> dilewati")
            ad_row = None

        # ── rencanakan ──
        plan: list[tuple[str, list[dict], list[str], str | None]] = []
        legacy_secrets = 0
        for v2_table, v3_table, mapper, cols, conflict in TABLES:
            mapped = []
            for r in data[v2_table]:
                m = mapper(r)
                if m.pop("_secret_note", "") == "legacy-plaintext-butuh-rotasi":
                    legacy_secrets += 1
                mapped.append({k: m.get(k) for k in cols})
            plan.append((v3_table, mapped, cols, conflict))
        ad_mapped = map_ad_config(ad_row) if ad_row else []

        total = sum(len(rows) for _, rows, _, _ in plan) + len(ad_mapped)
        print(f"Rencana migrasi: {total} baris")
        for v3_table, rows, _, _ in plan:
            print(f"  {v3_table}: {len(rows)} baris")
        print(f"  ad_config: {len(ad_mapped)} baris key/value")
        if legacy_secrets:
            print(f"  ! {legacy_secrets} api_keys punya secret_pass plaintext legacy -> wajib dirotasi via panel admin")

        if not args.apply:
            print("\nDRY-RUN selesai — tidak ada yang ditulis. Tambahkan --apply untuk eksekusi.")
            return 0

        # ── pengaman ──
        targets = [v3 for v3, _, _, _ in plan] + (["ad_config"] if ad_mapped else [])
        non_empty = [t for t in targets if _table_count(d_cur, t) > 0]
        if non_empty and not args.force:
            print(f"BATAL: tabel tujuan sudah berisi data: {', '.join(non_empty)}")
            print("Gunakan --force untuk tetap lanjut (baris duplikat dilewati via ON CONFLICT).")
            return 2

        # ── tulis ──
        for v3_table, rows, cols, conflict in plan:
            if not rows:
                continue
            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(["%s"] * len(cols))
            on_conflict = (
                f' ON CONFLICT ("{conflict}") DO NOTHING' if conflict
                else " ON CONFLICT DO NOTHING"
            )
            sql = f'INSERT INTO "{v3_table}" ({col_list}) VALUES ({placeholders}){on_conflict}'
            for r in rows:
                vals = []
                for c in cols:
                    v = r[c]
                    if isinstance(v, (dict, list)):
                        v = json.dumps(v)
                    vals.append(v)
                d_cur.execute(sql, vals)
            print(f"  tulis {v3_table}: {len(rows)} baris (duplikat dilewati)")
        for r in ad_mapped:
            d_cur.execute(
                'INSERT INTO "ad_config" ("key", "value") VALUES (%s, %s::jsonb)'
                " ON CONFLICT (\"key\") DO NOTHING",
                (r["key"], json.dumps(r["value"])),
            )
        if ad_mapped:
            print(f"  tulis ad_config: {len(ad_mapped)} baris key/value")

        for t in SEQ_TABLES:
            d_cur.execute(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                f'(SELECT COALESCE(MAX("id"), 1) FROM "{t}"))',
                (t,),
            )
        dst.commit()
        print("\nMigrasi selesai. Password user disalin apa adanya (bcrypt kompatibel).")
        if legacy_secrets:
            print(f"INGAT: {legacy_secrets} api_keys butuh rotasi secret_pass via panel admin.")
        return 0
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    sys.exit(main())
