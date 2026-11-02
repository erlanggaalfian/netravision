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

Exit 0 bila semua PASS (SKIP dihitung lolos), 1 bila ada FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

CHECKS: list[tuple[str, str]] = []  # (nama, PASS|FAIL|SKIP)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke test NetraVision v3.0")
    p.add_argument("--base-url", default="http://127.0.0.1:8100",
                   help="basis URL API (default: http://127.0.0.1:8100)")
    p.add_argument("--username", required=True, help="username admin")
    p.add_argument("--password", required=True, help="password admin")
    p.add_argument("--timeout", type=float, default=10.0)
    return p.parse_args(argv)


def check(nama: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    CHECKS.append((nama, status))
    print(f"[{status}] {nama}" + (f" — {detail}" if detail else ""))
    return ok


def skip(nama: str, detail: str = "") -> None:
    CHECKS.append((nama, "SKIP"))
    print(f"[SKIP] {nama}" + (f" — {detail}" if detail else ""))


def main() -> int:
    args = parse_args()
    base = args.base_url.rstrip("/")
    t = args.timeout
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
          ("SEMUA LOLOS." if fails == 0 else "ADA YANG GAGAL — jangan lanjut cutover."))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
