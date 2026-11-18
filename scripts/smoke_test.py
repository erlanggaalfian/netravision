#!/usr/bin/env python3
"""Smoke test NetraVision v3.0 pasca-install/cutover.

Berjalan berurutan, BERHENTI di cek pertama yang gagal:
  1. GET /api/health -> 200 dan status ok/degraded
  2. POST /api/auth/login -> 200 + access_token
  3. GET /api/streams (dengan token) -> 200
  4. GET /api/metrics dengan token admin -> 200; tanpa token -> 401/403
  5. WebSocket /ws -> terima snapshot (SKIP bila lib `websockets` tak ada)

Contoh:
  python scripts/smoke_test.py --base-url http://127.0.0.1:8100 \\
      --username admin --password 'R4h4s1a!'
  python scripts/smoke_test.py --health-only          # tanpa kredensial, tanpa httpx
  python scripts/smoke_test.py --check-mediamtx       # TCP ke 8888/9997 MediaMTX

Exit 0 bila semua PASS (SKIP dihitung lolos), 1 bila ada FAIL.

Mode --health-only memakai stdlib (urllib) saja, supaya deploy/update.sh
bisa memanggilnya dari host tanpa dependensi Python. Mode --check-mediamtx
hanya memastikan port HLS (8888) dan RTSP (9997) MediaMTX bisa dihubungi
dari host (liveness penuh tetap lewat /api/health).
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.request
import urllib.error

# httpx diimpor LAZY (di main, hanya untuk mode penuh): mode --health-only
# dan --check-mediamtx harus jalan tanpa dependensi eksternal.

CHECKS: list[tuple[str, str]] = []  # (nama, PASS|FAIL|SKIP)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke test NetraVision v3.0")
    p.add_argument("--base-url", default="http://127.0.0.1:8100",
                   help="basis URL API (default: http://127.0.0.1:8100)")
    p.add_argument("--username", default=None, help="username admin (wajib kecuali --health-only / --check-mediamtx)")
    p.add_argument("--password", default=None, help="password admin (wajib kecuali --health-only / --check-mediamtx)")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--health-only", action="store_true",
                   help="hanya GET /api/health (stdlib saja, tanpa kredensial)")
    p.add_argument("--check-mediamtx", action="store_true",
                   help="cek TCP MediaMTX: HLS 8888 + RTSP 9997 (stdlib saja)")
    return p.parse_args(argv)


def check(nama: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    CHECKS.append((nama, status))
    print(f"[{status}] {nama}" + (f", {detail}" if detail else ""))
    return ok


def skip(nama: str, detail: str = "") -> None:
    CHECKS.append((nama, "SKIP"))
    print(f"[SKIP] {nama}" + (f", {detail}" if detail else ""))


def _summary() -> int:
    print()
    n_fail = sum(1 for _, s in CHECKS if s == "FAIL")
    n_skip = sum(1 for _, s in CHECKS if s == "SKIP")
    print(f"Ringkasan: {len(CHECKS)} cek, {n_fail} gagal, {n_skip} dilewati")
    return 1 if n_fail else 0


def _health_only(base: str, timeout: float) -> int:
    """Hanya GET /api/health via stdlib urllib (tanpa httpx/kredensial)."""
    print(f"Smoke test (health-only) -> {base}\n")
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
            status = r.status
    except urllib.error.HTTPError as e:
        check("GET /api/health -> 200", False, f"status={e.code}")
        return _summary()
    except Exception as e:  # noqa: BLE001
        check("GET /api/health", False, f"tidak terjangkau: {e}")
        return _summary()
    if not check("GET /api/health -> 200", status == 200, f"status={status}"):
        return _summary()
    if not check("health.status ok/degraded",
                 body.get("status") in ("ok", "degraded"),
                 f"status={body.get('status')}"):
        return _summary()
    return _summary()


def _check_mediamtx(timeout: float = 3.0) -> int:
    """TCP connect ke port MediaMTX yang diekspos di host.

    8888 = HTTP/HLS, 9997 = RTSP. Ini BUKAN liveness penuh (tidak
    membuktikan ada stream), tapi cukup untuk membuktikan service
    mediamtx naik dan mendengarkan. Liveness penuh: /api/health
    (api memeriksa koneksi ke MediaMTX) + cek stream.
    """
    print("Cek MediaMTX (TCP connect, timeout 3 dtk)\n")
    for port, nama in ((8888, "MediaMTX HLS :8888"), (9997, "MediaMTX RTSP :9997")):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                check(f"TCP 127.0.0.1:{port} ({nama})", True)
        except OSError as e:
            check(f"TCP 127.0.0.1:{port} ({nama})", False, str(e))
    return _summary()


def main() -> int:
    args = parse_args()
    base = args.base_url.rstrip("/")
    t = args.timeout

    if args.check_mediamtx:
        return _check_mediamtx()
    if args.health_only:
        return _health_only(base, t)
    if not args.username or not args.password:
        print("error: --username dan --password wajib untuk mode penuh "
              "(atau pakai --health-only / --check-mediamtx).", file=sys.stderr)
        return 2

    # Mode penuh butuh httpx (diimpor di sini, bukan di atas).
    try:
        import httpx
    except ImportError:
        print("error: httpx tidak terinstal - pip install httpx, atau pakai --health-only.",
              file=sys.stderr)
        return 2
    print(f"Smoke test -> {base}\n")

    # 1. health
    try:
        r = httpx.get(f"{base}/api/health", timeout=t)
        body = r.json()
    except Exception as e:  # noqa: BLE001
        check("GET /api/health", False, f"tidak terjangkau: {e}")
        return _summary()
    if not check("GET /api/health -> 200", r.status_code == 200, f"status={r.status_code}"):
        return _summary()
    if not check("health.status ok/degraded",
                 body.get("status") in ("ok", "degraded"),
                 f"status={body.get('status')}"):
        return _summary()

    # 2. login
    try:
        r = httpx.post(f"{base}/api/auth/login", timeout=t,
                       json={"username": args.username, "password": args.password})
    except Exception as e:  # noqa: BLE001
        check("POST /api/auth/login", False, f"tidak terjangkau: {e}")
        return _summary()
    if not check("login -> 200", r.status_code == 200, f"status={r.status_code}"):
        return _summary()
    try:
        token = r.json()["access_token"]
    except (KeyError, ValueError, json.JSONDecodeError):
        check("login mengembalikan access_token", False, r.text[:120])
        return _summary()
    check("login mengembalikan access_token", True)
    headers = {"Authorization": f"Bearer {token}"}

    # 3. daftar stream
    try:
        r = httpx.get(f"{base}/api/streams", headers=headers, timeout=t)
    except Exception as e:  # noqa: BLE001
        check("GET /api/streams", False, f"tidak terjangkau: {e}")
        return _summary()
    if not check("GET /api/streams -> 200", r.status_code == 200,
                 f"status={r.status_code}"):
        return _summary()

    # 4. metrik: admin boleh, anonim ditolak
    try:
        r_admin = httpx.get(f"{base}/api/metrics", headers=headers, timeout=t)
        r_anon = httpx.get(f"{base}/api/metrics", timeout=t)
    except Exception as e:  # noqa: BLE001
        check("GET /api/metrics", False, f"tidak terjangkau: {e}")
        return _summary()
    if not check("GET /api/metrics (admin) -> 200",
                 r_admin.status_code == 200,
                 f"status={r_admin.status_code}"):
        return _summary()
    if not check("GET /api/metrics (anonim) -> 401/403",
                 r_anon.status_code in (401, 403),
                 f"status={r_anon.status_code}"):
        return _summary()

    # 5. websocket /ws (opsional)
    try:
        import websockets  # noqa: F401
        from websockets.sync.client import connect
    except ImportError:
        skip("WS /ws snapshot", "lib `websockets` tidak terinstal")
        return _summary()
    try:
        ws_url = base.replace("http://", "ws://").replace("https://", "wss://")
        with connect(f"{ws_url}/ws?token={token}", open_timeout=t) as ws:
            msg = json.loads(ws.recv(timeout=t))
        ok = msg.get("type") == "snapshot"
        if not check("WS /ws -> snapshot", ok, f"type={msg.get('type')}"):
            return _summary()
    except Exception as e:  # noqa: BLE001
        check("WS /ws -> snapshot", False, str(e)[:120])
        return _summary()

    return _summary()


def _summary() -> int:
    print()
    fails = sum(1 for _, s in CHECKS if s == "FAIL")
    print(f"Ringkasan: {len(CHECKS)} cek, {fails} FAIL. " +
          ("SEMUA LOLOS." if fails == 0 else "ADA YANG GAGAL, jangan lanjut cutover."))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
