"""Middleware security headers.

Menambah header keamanan pada setiap respons HTTP. Sengaja TIDAK men-set
``X-Frame-Options`` secara global: halaman ``/embed`` milik mitra harus bisa
di-iframe (sudah ditangani di konfigurasi vhost Apache).
"""

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Halaman embed tidak butuh device API apa pun.
    "Permissions-Policy": "camera=(), microphone=()",
}


class SecurityHeadersMiddleware:
    """Middleware ASGI murni (tanpa BaseHTTPMiddleware)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                for name, value in _HEADERS.items():
                    headers[name.lower().encode("latin-1")] = value.encode("latin-1")
                message = {**message, "headers": list(headers.items())}
            await send(message)

        await self.app(scope, receive, send_with_headers)
