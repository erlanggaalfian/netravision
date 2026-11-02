# NetraVision v3.0 — Peta Migrasi (v2.0 → v3.0)

Disusun 2026-11-02 dari inventarisasi `backend/main.py` (5.374 baris).
Aturan: **path `/api/*` dipertahankan kompatibel** — tidak ada yang dihilangkan,
hanya dirapikan ke modul. Total: **52 endpoint** (27 GET, 16 POST, 5 PUT, 4 DELETE).

## Modul router v3.0 (`apps/api/routers/`)

| Modul | Tanggung jawab |
|---|---|
| `system.py` | health, root |
| `auth.py` | login, guest |
| `streams.py` | daftar stream, reconnect, poster |
| `recordings.py` | timeline, segmen, unduh, tanggal |
| `admin_users.py` | user, hak akses kamera, ikhtisar akses |
| `admin_streams.py` | stream, grup, scan kamera, disk |
| `admin_keys.py` | API key + log akses |
| `admin_ads.py` | konfigurasi iklan/banner |
| `external.py` | embed pihak ketiga — **KONTRAK TIDAK BERUBAH** |
| `ws.py` | **BARU**: WebSocket status kamera & alert |

## 1. System & Auth

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `GET /` | — (dihilangkan) | v3.0: `/` dilayani Apache DocumentRoot (frontend statis) |
| `GET /api/health` | `system.py` | + cek koneksi DB & MediaMTX |
| `POST /api/auth/login` | `auth.py` | JWT access pendek + refresh rotation (baru) |
| `POST /api/auth/guest` | `auth.py` | dipertahankan |

## 2. Streams (pengguna)

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `GET /api/streams` | `streams.py` | + status online/offline real-time |
| `POST /api/streams/{stream_id}/reconnect` | `streams.py` | + auto-reconnect terlihat di UI |
| `GET /api/posters/stream_{stream_id}.jpg` | `streams.py` | job poster via worker, bukan inline |

## 3. Recordings

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `GET /api/recordings/cameras` | `recordings.py` | — |
| `GET /api/recordings/{stream_id}/timeline` | `recordings.py` | + penanda event AI (aktif bila modul AI on) |
| `GET /api/recordings/{stream_id}/segments` | `recordings.py` | — |
| `GET /api/recordings/{stream_id}/dates` | `recordings.py` | — |
| `GET /api/recordings/{stream_id}/stream` | `recordings.py` | — |
| `GET /api/recordings/{stream_id}/file` | `recordings.py` | unduh potongan |
| `GET /api/recordings/{stream_id}/playback-url` | `recordings.py` | — |
| `GET /api/recordings/{stream_id}/next-playable` | `recordings.py` | — |

## 4. Admin — Users & Akses

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `GET /api/admin/users` | `admin_users.py` | — |
| `POST /api/admin/users` | `admin_users.py` | — |
| `PUT /api/admin/users/{user_id}` | `admin_users.py` | — |
| `DELETE /api/admin/users/{user_id}` | `admin_users.py` | — |
| `GET /api/admin/users/{user_id}/camera-access` | `admin_users.py` | — |
| `POST /api/admin/users/{user_id}/camera-access` | `admin_users.py` | — |
| `POST /api/admin/users/{user_id}/access` | `admin_users.py` | — |
| `GET /api/admin/admins/{admin_id}/camera-grants` | `admin_users.py` | — |
| `POST /api/admin/admins/{admin_id}/camera-grants` | `admin_users.py` | — |
| `GET /api/admin/access-overview` | `admin_users.py` | — |

## 5. Admin — Streams, Grup, Scan, Disk

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `GET /api/admin/streams` | `admin_streams.py` | — |
| `POST /api/admin/streams` | `admin_streams.py` | + brand resolver (ONVIF → template → generik) |
| `PUT /api/admin/streams/{stream_id}` | `admin_streams.py` | simpan `brand`, `main_url`, `sub_url` eksplisit |
| `DELETE /api/admin/streams/{stream_id}` | `admin_streams.py` | — |
| `GET /api/admin/streams/{stream_id}/sharing` | `admin_streams.py` | — |
| `POST /api/admin/streams/{stream_id}/sharing` | `admin_streams.py` | — |
| `POST /api/admin/streams/{stream_id}/owner` | `admin_streams.py` | — |
| `PUT /api/admin/groups/{nama_grup}` | `admin_streams.py` | — |
| `GET /api/admin/groups/{nama_grup}/camera-grants` | `admin_streams.py` | — |
| `POST /api/admin/groups/{nama_grup}/camera-grants` | `admin_streams.py` | — |
| `POST /api/admin/scan` | `admin_streams.py` | + pilih brand / otomatis + preview kandidat |
| `POST /api/admin/scan/preview` | `admin_streams.py` | preview tiap kandidat sebelum simpan |
| `GET /api/admin/disks` | `admin_streams.py` | — |

## 6. Admin — API Keys & Log

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `GET /api/admin/api-keys` | `admin_keys.py` | — |
| `POST /api/admin/api-keys` | `admin_keys.py` | — |
| `PUT /api/admin/api-keys/{key_id}` | `admin_keys.py` | — |
| `DELETE /api/admin/api-keys/{key_id}` | `admin_keys.py` | — |
| `GET /api/admin/api-access-logs` | `admin_keys.py` | — |
| `GET /api/admin/api-access-logs/summary` | `admin_keys.py` | — |
| `DELETE /api/admin/api-access-logs` | `admin_keys.py` | — |

## 7. Admin — Iklan

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `GET /api/ad-config` | `admin_ads.py` | — |
| `POST /api/admin/ad-config` | `admin_ads.py` | — |
| `POST /api/admin/ad-config/upload-image` | `admin_ads.py` | — |
| `PUT /api/admin/groups/{group_name}/ads` | `admin_ads.py` | — |

## 8. External (embed pihak ketiga) — KONTRAK TETAP

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `GET /api/external/cameras` | `external.py` | tidak berubah |
| `GET /api/external/stream` | `external.py` | tidak berubah |
| `GET /api/external/playback` | `external.py` | tidak berubah |

## 9. BARU di v3.0 (tidak ada di v2.0)

| Endpoint | Modul | Fungsi |
|---|---|---|
| `WS /ws` | `ws.py` | status kamera, alert, progres — ganti polling |
| `POST /api/auth/refresh` | `auth.py` | refresh-token rotation |
| `POST /api/auth/logout` | `auth.py` | revoke refresh token |

## Peta database (9 tabel v2.0 → Alembic)

| v2.0 (MariaDB) | v3.0 (PostgreSQL) | Perubahan |
|---|---|---|
| `users` | `users` | + `refresh_token_hash`, kolom waktu standar |
| `cctv_streams` | `streams` | + `brand`, `main_url`, `sub_url`, `onvif_profile`, `is_online`, `last_seen_at` |
| `user_cctv_access` | `user_stream_access` | nama dirapikan, relasi sama |
| `stream_permissions` | `stream_permissions` | — |
| `stream_admin_grants` | `stream_admin_grants` | — |
| `api_keys` | `api_keys` | + `last_used_at` |
| `api_key_cameras` | `api_key_streams` | nama dirapikan |
| `api_access_logs` | `api_access_logs` | → hypertable TimescaleDB (opsional) |
| `ad_config` | `ad_config` | — |
| — (baru) | `detection_events` | event AI (hypertable; dipakai bila modul AI on) |
| — (baru) | `alerts` | alert ke user (dipakai bila modul AI on) |
| — (baru) | `audit_logs` | jejak aksi admin (wajib — temuan audit v2.0) |

Skrip impor sekali-jalan: `deploy/migrate-v2.py` (MariaDB v2.0 → PostgreSQL v3.0).

## Peta halaman frontend (PHP → Next.js)

| v2.0 | v3.0 | Catatan |
|---|---|---|
| `index.php` (live-monitor) | `/live` | grid + sub/main stream otomatis |
| `playback.php` | `/playback` | timeline + penanda event |
| `views/maps.php` | `/maps` | Leaflet, dipertahankan |
| `views/custom-monitor.php` | `/monitors` | tata letak kisi tersimpan |
| `views/admin-console.php` | `/admin` | semua panel admin |
| `login.php` | `/login` | — |
| `embed.php` | `/embed` | kontrak `/api/external/*` tetap |

---

# Backlog Fase 0 — Fondasi

Gate: selesai bila semua checklist di bawah ✅ dan demo "fondasi jalan" disetujui.

**Repo & struktur**
- [ ] Inisialisasi monorepo `erlanggaalfian/netravision` (lokal dulu, push saat "mulai" disetujui)
- [ ] Struktur `apps/api`, `apps/web`, `apps/detector` (stub), `packages/contracts`, `deploy/`
- [ ] Kontrak OpenAPI digenerate dari 52 endpoint (§1–8 di atas) → tipe TS otomatis

**Backend fondasi**
- [ ] FastAPI app factory + config (env) + logging JSON
- [ ] Alembic init + migrasi awal (12 tabel di atas)
- [ ] `routers/system.py` + `routers/auth.py` (login + refresh + logout, JWT rotation)
- [ ] RBAC dependency (admin/user/guest + grant per kamera)

**Infra**
- [ ] `deploy/docker-compose.yml` (postgres, redis, api, mediamtx — publish 127.0.0.1 saja)
- [ ] `deploy/mediamtx.yml` (path template `stream_{id}` & `stream_{id}_sub`, UDP range)
- [ ] `deploy/apache/netra.mamura.net.id.conf` (DocumentRoot, proxy /api/* & /ws)
- [ ] `deploy/install.sh` + `deploy/update.sh` (idempoten, dengan health check)

**CI & kualitas**
- [ ] GitHub Actions: lint (ruff), typecheck (mypy), test (pytest), build web
- [ ] 48 checklist audit v2.0 sebagai file `docs/SECURITY-CHECKLIST.md`

**Demo Fase 0**: `install.sh` di server dev → buka `/api/health` → login via API →
response sesuai kontrak. Tanpa UI (UI mulai Fase 2).
