#!/usr/bin/env python3
"""Uji beban ringan NetraVision API (Fase 4).

Skenario:
  1. GET /api/health pada RPS target selama durasi -> p50/p95 latensi & error %.
  2. POST /api/auth/login kredensial salah 8x cepat -> verifikasi rate limit
     (429 setelah 5x/menit); laporkan "rate limit OK" bila 429 terlihat.

Contoh:
  python3 scripts/load_test.py --base-url http://127.0.0.1:8100 --rps 20 --duration 30

Hanya butuh httpx di luar stdlib.
"""

import argparse
import asyncio
import statistics
import sys
import time

try:
    import httpx
except ImportError:
    print("butuh httpx: pip install httpx", file=sys.stderr)
    sys.exit(2)


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = min(len(s) - 1, max(0, int(p / 100 * len(s))))
    return s[k]


async def hammer_health(
    client: httpx.AsyncClient, base: str, rps: int, duration: int
) -> dict:
    total = rps * duration
    lat: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(min(4 * rps, 200))

    async def one():
        nonlocal errors
        async with sem:
            t0 = time.perf_counter()
            try:
                r = await client.get(f"{base}/api/health", timeout=10.0)
                lat.append((time.perf_counter() - t0) * 1000.0)
                if r.status_code >= 500:
                    errors += 1
            except Exception:
                errors += 1

    interval = 1.0 / rps if rps > 0 else 0
    tasks = []
    for _ in range(total):
        tasks.append(asyncio.create_task(one()))
        await asyncio.sleep(interval)
    await asyncio.gather(*tasks)
    return {
        "total": total,
        "p50_ms": round(percentile(lat, 50), 1),
        "p95_ms": round(percentile(lat, 95), 1),
        "error_pct": round(errors / total * 100, 2) if total else 0.0,
    }


async def check_rate_limit(client: httpx.AsyncClient, base: str) -> dict:
    """8x login salah beruntun -> harapkan 429 setelah 5x/menit."""
    statuses: list[int] = []
    for _ in range(8):
        try:
            r = await client.post(
                f"{base}/api/auth/login",
                json={"username": "beban-test", "password": "salah"},
                timeout=10.0,
            )
            statuses.append(r.status_code)
        except Exception:
            statuses.append(0)
    n429 = statuses.count(429)
    return {"statuses": statuses, "n429": n429, "ok": n429 >= 1}


async def main() -> int:
    ap = argparse.ArgumentParser(description="Uji beban ringan NetraVision API")
    ap.add_argument("--base-url", default="http://127.0.0.1:8100")
    ap.add_argument("--rps", type=int, default=10, help="request/detik utk /health")
    ap.add_argument("--duration", type=int, default=30, help="detik")
    args = ap.parse_args()

    async with httpx.AsyncClient() as client:
        print(f"== GET /api/health  rps={args.rps} durasi={args.duration}s ==")
        h = await hammer_health(client, args.base_url, args.rps, args.duration)
        print(f"total request : {h['total']}")
        print(f"p50 latency   : {h['p50_ms']} ms")
        print(f"p95 latency   : {h['p95_ms']} ms")
        print(f"error         : {h['error_pct']} %")

        print("\n== POST /api/auth/login (rate limit 5x/mnt) ==")
        rl = await check_rate_limit(client, args.base_url)
        print(f"status codes  : {rl['statuses']}")
        print(f"429 count     : {rl['n429']}")
        print("rate limit OK" if rl["ok"] else "rate limit TIDAK TERDETEKSI")

    ok = h["error_pct"] < 5.0 and rl["ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
