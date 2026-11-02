# NetraVision v3.0 — Hardening Fase 4

Ringkasan pekerjaan hardening: rate limit, security headers, audit log,
metrik, PWA, dan uji beban. Kode backend hardening ada di
`apps/api/app/core/` (`rate_limit.py`, `security_headers.py`, `audit.py`,
`metrics.py`); PWA di `apps/web/public/` + `components/SWRegister.tsx`;
skrip uji di `scripts/load_test.py`.

## 1. Rate limit — `POST /api/auth/login` 5x/menit/IP

- Implementasi: dependency `rate_limited(5, 60)` (`app/core/rate_limit.py`),
  sliding-window in-memory per IP (hormati `X-Forwarded-For` karena di
  belakang Apache). Melewati batas → **429** + header `Retry-After`.
  Refresh token juga dibatasi (20x/menit).
- Verifikasi: `python3 scripts/load_test.py --base-url http://127.0.0.1:8100`
  skenario 2 — harapkan `statuses: [401 ×5, 429 ×3]` dan `rate limit OK`.
  Manual: `for i in $(seq 1 7); do curl -s -o /dev/null -w "%{http_code}\n"
  -X POST $BASE/api/auth/login -d '{"username":"x","password":"y"}'
  -H 'Content-Type: application/json'; done`
- Checklist: **S4** (endpoint publik diberi rate limit).
- Batasan jujur: state in-memory per proses — bila nanti jalan multi-worker,
  ganti store dengan Redis (signature `rate_limited()` tidak perlu berubah).

## 2. Security headers

- Implementasi: `SecurityHeadersMiddleware` (`app/core/security_headers.py`)
  + header yang sama di `deploy/apache/netra.mamura.net.id.conf`
  (defense-in-depth): `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`,
  `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
- `X-Frame-Options` **sengaja tidak dipasang** — halaman `/embed` harus bisa
  di-iframe oleh mitra (keputusan sadar, sama di vhost).
- Verifikasi: `curl -sI $BASE/api/health | grep -i "x-content-type-options"`
  → `nosniff`; pastikan `x-frame-options` tidak muncul.
- Checklist: **R8**.

## 3. Audit log — `audit_logs`

- Implementasi: `AuditMiddleware` (`app/core/audit.py`, pure-ASGI) mencatat
  setiap request non-GET ke `/api/admin/*`: actor (dari JWT),
  `METHOD /path`, IP, timestamp. Kegagalan pencatatan tidak pernah
  menggagalkan request (defensif, hanya warning di log).
- Verifikasi: lakukan aksi admin (mis. tambah user via `/admin/users`),
  lalu `SELECT action, actor_id, ip, created_at FROM audit_logs
  ORDER BY id DESC LIMIT 5;` — baris harus ada.
- Di test: override via `app.state.audit_session_factory`.
- Checklist: item **`audit_logs`** (§3.9 blueprint — "semua aksi admin
  tercatat, tidak bisa dimatikan diam-diam").

## 4. Metrik — `GET /api/metrics` (admin saja)

- Implementasi: `MetricsMiddleware` + router Prometheus
  (`app/core/metrics.py`, butuh `prometheus_client`): counter request,
  histogram latensi, info proses Python. Format Prometheus exposition,
  siap di-scrape.
- Verifikasi: login sebagai admin →
  `curl -H "Authorization: Bearer $TOKEN" $BASE/api/metrics` →
  `Content-Type: text/plain` berisi `# HELP`/`# TYPE`. Non-admin → 403.

## 5. PWA (installable di mobile & desktop)

- `apps/web/public/manifest.webmanifest` — name/short_name NetraVision,
  `display: standalone`, `start_url: /live/` (sesuai `trailingSlash`),
  theme/background `#0a0e13`, ikon SVG `icons/icon.svg`.
- `apps/web/public/sw.js` — service worker: **cache-first** untuk navigasi
  & aset statis same-origin (cache `nv-shell-v1`, precache /live/, /login/,
  manifest, ikon); **network-only** untuk `/api/*` dan `/ws` (tidak pernah
  di-cache); `skipWaiting` + `clients.claim`; fallback `/live/` saat offline.
- `components/SWRegister.tsx` didaftarkan di `app/layout.tsx`
  (bersama `manifest` di metadata). Next.js static export menyalin
  `public/` → `out/` otomatis — tanpa runtime Node.
- Verifikasi: `npm run build` → pastikan `out/sw.js`,
  `out/manifest.webmanifest`, `out/icons/icon.svg` ada; buka di Chrome →
  DevTools > Application > Manifest & Service Workers terdaftar;
  instal via menu browser.

## 6. Uji beban — `scripts/load_test.py`

- `python3 scripts/load_test.py --base-url http://127.0.0.1:8100
  --rps 20 --duration 30`
- Skenario 1: `GET /api/health` pada RPS target → output total request,
  p50/p95 latensi (ms), error %.
- Skenario 2: 8x `POST /api/auth/login` kredensial salah → hitung 429 →
  `rate limit OK` bila terlihat. Exit code 0 bila error < 5% dan rate
  limit terdeteksi, 1 bila tidak.
- Hanya butuh `httpx` di luar stdlib. Ini **smoke test**, bukan soak test
  — untuk uji kapasitas serius, naikkan `--rps`/`--duration` bertahap dan
  pantau `/api/metrics` selama jalan.

## Checklist keamanan yang terpenuhi Fase 4

| ID | Item | Status |
|----|------|--------|
| S4 | Endpoint publik diberi rate limit | ✅ login 5x/mnt + refresh 20x/mnt → 429 |
| R8 | Security header dasar terpasang | ✅ middleware app + vhost Apache |
| §3.9 | `audit_logs`: semua aksi admin tercatat | ✅ middleware audit non-GET /api/admin/* |

`docs/SECURITY-CHECKLIST.md` tidak diubah — tabel di atas merujuk ID-nya.
