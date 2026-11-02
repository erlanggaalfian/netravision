"""Metrik Prometheus + endpoint /api/metrics (khusus admin).

- Counter ``nv_http_requests_total{method,path_template,status}``
- Histogram ``nv_http_latency_seconds{method,path_template}``
- path digeneralisasi via route.path_template bila tersedia (contoh:
  /api/streams/{stream_id}); fallback regex untuk 404.
"""

import re
import time

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.core.rbac import require_roles

REQUESTS = Counter(
    "nv_http_requests_total",
    "Jumlah request HTTP",
    ["method", "path_template", "status"],
)
LATENCY = Histogram(
    "nv_http_latency_seconds",
    "Latensi request HTTP dalam detik",
    ["method", "path_template"],
)

_SEGMENT_RE = re.compile(r"/(\d+|[0-9a-fA-F]{8}-[0-9a-fA-F-]{28}|[0-9a-fA-F]{32})")


def path_template_for_scope(scope) -> str:
    """Template path generik, mis. ``/api/admin/users/{user_id}``.

    Dibangun dari path aktual + path_params (andal terhadap lazy
    _IncludedRouter yang route.path-nya tanpa prefix mount). Fallback:
    generalisasi segmen numerik/UUID pada path mentah (untuk 404).
    """
    path = scope.get("path", "") or "/"
    params = scope.get("path_params", {}) or {}
    for name, value in params.items():
        path = path.replace(f"/{value}", "/{" + name + "}", 1)
    return _SEGMENT_RE.sub(r"/{id}", path)


def _path_template(scope) -> str:
    return path_template_for_scope(scope)


class MetricsMiddleware:
    """Middleware ASGI murni: ukur setiap request HTTP."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_holder: dict = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            template = _path_template(scope)
            method = scope.get("method", "?")
            status_code = str(status_holder.get("status", 0))
            REQUESTS.labels(
                method=method, path_template=template, status=status_code
            ).inc()
            LATENCY.labels(method=method, path_template=template).observe(
                time.perf_counter() - start
            )


router = APIRouter(tags=["system"])


@router.get("/metrics", dependencies=[Depends(require_roles("admin"))])
async def metrics() -> Response:
    """Endpoint scrape Prometheus — khusus admin (akses internal)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
