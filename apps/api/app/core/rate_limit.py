"""Rate limiter in-memory, sliding-window per IP.

Dipakai sebagai dependency FastAPI: ``dependencies=[Depends(rate_limited(5, 60))]``.

Aproksimasi per-proses: setiap pemanggilan ``rate_limited()`` membuat bucket
store sendiri (per route), dan state hilang saat proses restart. Ini cukup
untuk deployment single-replica (pola NetraVision saat ini). Bila nanti scale
ke multi-replica, ganti store dengan backend Redis tanpa mengubah signature.
"""

import math
import time

from fastapi import HTTPException, Request, status

# Registry semua bucket store agar test bisa me-reset antar test.
_stores: list[dict[str, list[float]]] = []


def reset_rate_limits() -> None:
    """Kosongkan semua bucket (dipakai test agar antar-test terisolasi)."""
    for store in _stores:
        store.clear()


def rate_limited(times: int, per_seconds: int):
    """Dependency factory: batasi ``times`` request per ``per_seconds`` per IP.

    Key = IP klien (hormati X-Forwarded-For karena deploy di belakang reverse
    proxy Apache). Melewati batas -> 429 + header Retry-After (detik).
    """

    buckets: dict[str, list[float]] = {}
    _stores.append(buckets)

    async def checker(request: Request) -> None:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            ip = fwd.split(",")[0].strip()
        elif request.client is not None:
            ip = request.client.host
        else:
            ip = "?"

        now = time.monotonic()
        window_start = now - per_seconds
        hits = [t for t in buckets.get(ip, []) if t > window_start]

        if len(hits) >= times:
            retry_after = max(math.ceil(hits[0] + per_seconds - now), 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="terlalu banyak permintaan, coba lagi nanti",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        buckets[ip] = hits

        # Bersih-bersih oportunistik agar memori tidak tumbuh tanpa batas.
        if len(buckets) > 5000:
            for key in [k for k, v in buckets.items() if not v or v[-1] <= window_start]:
                del buckets[key]

    return checker
