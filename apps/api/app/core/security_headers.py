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

# 4.16: HSTS hanya bila request datang lewat HTTPS (langsung atau
# via proxy yang menyetel X-Forwarded-Proto). Mengirim HSTS pada
# respons HTTP polos tidak ada gunanya dan bisa mengunci localhost
# bila browser menerapkannya; di produksi Apache juga menyetel HSTS
# di vhost 443 (lapis kedua, lihat deploy/apache/*.conf).
_HSTS = "max-age=31536000; includeSubDomains"

# 4.16: CSP ketat untuk file statis /api/uploads (gambar iklan yang
# diunggah super_admin): tidak ada eksekusi skrip/HTML dari direktori
# itu bila suatu hari ada berkas non-gambar yang lolos validasi.
# Header ini HANYA untuk /api/uploads; API JSON tidak menyajikan HTML
# sehingga CSP global tidak diperlukan.
_CSP_UPLOADS = "default-src 'none'; sandbox"


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
                # 4.16: HSTS hanya untuk respons yang datang lewat HTTPS.
                scheme = scope.get("scheme", "http")
                fwd_proto = ""
                for k, v in scope.get("headers", []):
                    if k.decode("latin-1").lower() == "x-forwarded-proto":
                        fwd_proto = v.decode("latin-1").strip().lower()
                        break
                if scheme == "https" or fwd_proto == "https":
                    headers[b"strict-transport-security"] = _HSTS.encode("latin-1")
                # 4.16: CSP ketat untuk file statis /api/uploads.
                if (scope.get("path", "") or "").startswith("/api/uploads"):
                    headers[b"content-security-policy"] = _CSP_UPLOADS.encode("latin-1")
                message = {**message, "headers": list(headers.items())}
            await send(message)

        await self.app(scope, receive, send_with_headers)
