"""Rate limiter in-memory, sliding-window per IP.

Dipakai sebagai dependency FastAPI: ``dependencies=[Depends(rate_limited(5, 60))]``.

Aproksimasi per-proses: setiap pemanggilan ``rate_limited()`` membuat bucket
store sendiri (per route), dan state hilang saat proses restart. Ini cukup
untuk deployment single-replica (pola NetraVision saat ini). Bila nanti scale
ke multi-replica, ganti store dengan backend Redis tanpa mengubah signature.
"""

import ipaddress
import math
import os
import time

from fastapi import HTTPException, Request, status

# Registry semua bucket store agar test bisa me-reset antar test.
_stores: list[dict[str, list[float]]] = []


def _trusted_proxy_cidrs() -> list:
    """Daftar CIDR proxy tepercaya dari env TRUSTED_PROXY_CIDRS
    (dipisah koma). Kosong = tidak ada proxy tepercaya yang dikonfigurasi."""
    raw = os.environ.get("TRUSTED_PROXY_CIDRS", "")
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                continue
    return nets


def _is_trusted_proxy(peer: str | None) -> bool:
    """Peer dianggap proxy tepercaya bila ada di TRUSTED_PROXY_CIDRS,
    atau bila ia loopback/private (Apache di host yang sama, pola
    deploy NetraVision saat ini). Peer publik tidak pernah dipercaya."""
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_private:
        return True
    return any(addr in net for net in _trusted_proxy_cidrs())


def client_ip(request: Request) -> str:
    """IP klien untuk rate limit/log.

    A-R5: X-Forwarded-For / X-Real-IP hanya dipercaya bila peer
    langsung adalah proxy tepercaya (lihat _is_trusted_proxy);
    bila tidak, pakai IP peer langsung supaya header tidak bisa
    dipalsukan untuk melewati batas.
    """
    peer = request.client.host if request.client else ""
    if _is_trusted_proxy(peer):
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            first = fwd.split(",")[0].strip()
            if first:
                return first
        real = request.headers.get("x-real-ip", "").strip()
        if real:
            return real
    return peer or "?"


def reset_rate_limits() -> None:
    """Kosongkan semua bucket (dipakai test agar antar-test terisolasi)."""
    for store in _stores:
        store.clear()


def rate_limited(times: int, per_seconds: int):
    """Dependency factory: batasi ``times`` request per ``per_seconds`` per IP.

    Key = IP klien (client_ip: X-Forwarded-For hanya dipercaya dari
    proxy tepercaya, lihat A-R5). Melewati batas -> 429 + header
    Retry-After (detik).
    """

    buckets: dict[str, list[float]] = {}
    _stores.append(buckets)

    async def checker(request: Request) -> None:
        ip = client_ip(request)

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
