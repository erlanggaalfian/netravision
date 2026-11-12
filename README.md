# NetraVision v3.0

Sistem monitoring CCTV modern. Tulis ulang penuh dari v2.0 ("Mamura Stream") dengan arsitektur modular, frontend baru, dan kontrak API yang dijaga kompatibel. Deploy di `netra.mamura.net.id`, berdampingan dengan virtualhost Apache lain. Port 80/443 tetap milik Apache.

## Fitur

### Menonton

- **Live**: grid kamera 1x1 sampai 4x4 di desktop, daftar di HP. Sub stream untuk grid, main stream untuk fokus. LQ/HQ, snapshot, fullscreen, putar ulang langsung dari tile.
- **Putar Ulang (Playback)**: rekaman per kamera dengan timeline, navigasi tanggal, dan grid yang sama seperti Live.
- **Peta (Maps)**: semua kamera di peta Leaflet/OpenStreetMap. Kamera berdekatan digabung jadi satu klaster berisi jumlah kamera saat zoom out, dan menyebar (spiderfy) saat zoom maksimal. Warna klaster mengikuti status: hijau bila semua kamera nyala, kuning bila ada yang mati, merah bila semua mati. Klik marker untuk popup, tombol **Edit Lokasi** (super admin) untuk memindahkan posisi, lalu **Save Lokasi**.
- **Monitor**: layout kamera tersimpan (grid custom) plus grup kamera yang bisa dibuka langsung dari daftar. Layar penuh memakai grid sama tinggi, nama kamera disembunyikan, iklan masuk ke dalam frame.
- **Embed**: sematkan satu kamera ke situs lain lewat API Key, dengan sesi token dan batas domain.

### Admin

- **Kamera**: tambah, ubah, hapus, bagikan ke pengguna, scan subnet (async, ada progres), bulk set koordinat dan grup, folder Google Drive per kamera.
- **Pengguna**: kelola akun dan grup wilayah, akses kamera per pengguna (Live/Playback/Bagikan), bulk set grup. Admin hanya mengelola grupnya sendiri; super admin mengelola semua.
- **Grup Kamera**: kelompokkan kamera, atur akses per grup.
- **Iklan**: teks berjalan (marquee) dan gambar sponsor di bawah video. Jenis tampilan Selalu Tampil atau Berkala (interval, hover, klik). Iklan bisa dimatikan per pengguna, per grup, dan per API Key.
- **API Key**: kunci akses eksternal dengan batas domain, password, masa berlaku, TTL sesi, nama kamera custom, opsi playback, dan opsi iklan.
- **Scanner**: pindai subnet untuk menemukan kamera RTSP/ONVIF (12 brand, termasuk Ezviz).
- **Penyimpanan**: tautan folder Google Drive (rclone) dan akun OAuth untuk rekaman.
- **Akses tamu (guest)**: login tanpa password untuk pengunjung, bisa diaktifkan/dimatikan, dengan akses kamera dan iklan yang bisa diatur. Dibuat otomatis dalam posisi nonaktif bila database di-reset.

### Peran dan hak akses

| Peran | Hak |
|---|---|
| `super_admin` | Kuasa penuh: semua kamera, pengguna, grup, iklan, API Key, scanner, penyimpanan. |
| `admin` | Mengelola pengguna di grupnya sendiri, membagikan kamera yang diizinkan super admin ke user/guest di grupnya. Tidak bisa tambah/ubah/hapus kamera. |
| `user` | Menonton kamera yang dibagikan, sesuai akses Live/Playback. |
| `guest` | Pengunjung tanpa password, akses kamera diatur super admin. |

Akses kamera per pengguna diatur dua arah: per kamera (menu Bagikan) dan per pengguna (menu Pengguna, Akses Kamera). Keduanya saling melengkapi dan tidak saling menghapus di luar cakupan admin yang menyimpan.

## Teknologi

| Lapisan | Stack |
|---|---|
| Backend | FastAPI (Python), SQLAlchemy 2 + Alembic, PostgreSQL 16 + TimescaleDB, JWT 15 menit + refresh 7 hari, WebSocket status live |
| Frontend | Next.js 15 + React 19 + TypeScript + Tailwind v4 (static export), PWA, mode terang/gelap |
| Streaming | MediaMTX (RTSP ke WebRTC via WHIP/WHEP), sub + main stream |
| Rekaman | Lokal per kamera dan/atau Google Drive (rclone + OAuth), retensi per kamera |
| Deploy | Bash `install.sh`/`update.sh`, Docker Compose (container hanya 127.0.0.1), Apache reverse proxy `/api/*` dan `/ws` |
| Deteksi AI | Modul opsional (worker YOLO), bisa diaktifkan/dimatikan |

## Struktur monorepo

```text
apps/
  api/        # Backend FastAPI modular: routers, models, schemas, services, Alembic
  web/        # Frontend Next.js (static export ke apps/web/out)
  detector/   # Worker AI detection (YOLO), modul opsional
packages/
  contracts/  # Kontrak OpenAPI, sumber kebenaran API; tipe TS digenerate
deploy/
  apache/         # vhost netra.mamura.net.id
  docker-compose.yml
  mediamtx.yml
  install.sh      # instalasi idempoten dari bash
  update.sh       # pembaruan: pull, build, migrasi, restart
  rollback.sh     # kembali ke rilis sebelumnya
  migrate-v2.py   # migrasi data dari v2.0
  seed_admin.py   # buat akun admin awal
docs/
  BLUEPRINT.md            # arsitektur
  MIGRATION-MAP.md        # peta 52 endpoint v2 ke router v3
  SECURITY-CHECKLIST.md   # daftar periksa keamanan
  CUTOVER.md              # runbook cutover ke produksi
  GOOGLE-DRIVE.md         # panduan Drive dan rclone
  HARDENING.md            # pengerasan server
  analisa-menyeluruh-2026-11-11.md  # audit 133 temuan dan perbaikannya
scripts/
  preflight.py            # cek prasyarat sebelum install
```

### Backend (apps/api)

```text
app/
  main.py          # titik masuk FastAPI
  core/            # config, keamanan, RBAC, rate limit
  db/              # session, base model
  models/          # users, streams, groups, access, keys, ads, drive, recordings
  routers/         # auth, streams, admin_streams, admin_users, admin_ads,
                   # admin_keys, admin_scan, admin_drive, recordings, external, ws, system
  schemas/         # validasi Pydantic
  services/        # MediaMTX, RTSP discovery, poster, recording, Drive
alembic/           # migrasi database (head saat ini: 0018)
tests/             # pytest, 207 tes
```

### Frontend (apps/web)

```text
app/
  live/            # Live grid
  playback/        # Putar Ulang
  maps/            # Peta Leaflet + klaster
  monitors/        # Monitor tersimpan + grup kamera
  embed/           # halaman embed publik
  login/           # login + guest
  admin/           # streams, users, groups, ads, keys, scanner, drive
components/        # CameraTile, FocusModal, AdBanner, ShareModal, ui
hooks/             # useCameraStatus (WebSocket live)
lib/               # api client, auth, types
```

## Mulai cepat

### Prasyarat

- Ubuntu/Debian server, root atau sudo
- Docker + Docker Compose plugin
- Apache2 (port 80/443 milik Apache)
- Node.js 20+ dan Python 3.12+ (untuk build lokal)
- PostgreSQL 16 (disediakan container oleh compose, atau instal di OS)

### Instalasi baru (server)

```bash
git clone https://github.com/erlanggaalfian/netravision.git
cd netravision
sudo ./deploy/install.sh
```

`install.sh` idempoten dan aman dijalankan ulang. Langkahnya: cek prasyarat, siapkan `deploy/.env`, hentikan MediaMTX v2.0, jalankan Docker Compose, migrasi Alembic, seed admin (bila `NV_ADMIN_USER`/`NV_ADMIN_PASS` diset), siapkan vhost Apache, lalu health check `GET /api/health`.

### Pembaruan (server yang sudah jalan)

```bash
sudo ./deploy/update.sh
```

Urutan update: pull, rebuild frontend dan API, migrasi Alembic, restart API/MediaMTX/Apache. Bila gagal, kembalikan dengan `sudo ./deploy/rollback.sh`. Detail cutover produksi ada di `docs/CUTOVER.md`.

### Menjalankan lokal (pengembangan)

Backend:

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock
cp .env.example .env   # isi DATABASE_URL dan JWT_SECRET
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Frontend:

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
npm run build      # static export ke apps/web/out
```

MediaMTX dan PostgreSQL tetap dibutuhkan untuk streaming dan data; tanpa MediaMTX, health API berstatus `degraded` (normal) dan tile menampilkan poster.

## Konfigurasi

Salin `apps/api/.env.example` ke `apps/api/.env` (atau `deploy/.env` untuk Docker). Jangan commit `.env` berisi rahasia asli.

| Variabel | Keterangan |
|---|---|
| `DATABASE_URL` | URL PostgreSQL, contoh `postgresql+psycopg://netravision:pass@127.0.0.1:5432/netravision` |
| `JWT_SECRET` | Rahasia JWT, wajib diganti di produksi (acak, minimal 32 karakter) |
| `JWT_ACCESS_MINUTES` | Umur access token (default 15) |
| `JWT_REFRESH_DAYS` | Umur refresh token (default 7) |
| `GUEST_ENABLED` | Login tamu aktif atau tidak (default false; guest dibuat nonaktif) |
| `MEDIAMTX_API_URL` | API MediaMTX (default `http://127.0.0.1:9997`) |
| `MEDIAMTX_WHEP_BASE` | Base WHEP MediaMTX (default `http://127.0.0.1:8889`) |
| `POSTERS_ENABLED` | Buat poster kamera berkala (butuh ffmpeg) |
| `POSTER_INTERVAL_SEC` | Interval poster (default 60 detik) |
| `RETENTION_ENABLED` | Hapus rekaman lokal melewati retensi |

## API

Kontrak lengkap ada di `packages/contracts/` (OpenAPI). Ringkasnya:

- **Auth**: `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/guest`, `GET /api/auth/me`, `GET /api/auth/guest-enabled`.
- **Kamera**: `GET /api/streams`, `GET /api/streams/{id}/whep`, `POST /api/streams/{id}/reconnect`, `GET /api/posters/stream_{id}.jpg`.
- **Admin kamera**: `POST/PUT/DELETE /api/admin/streams`, `POST /api/admin/streams/{id}/sharing`, `POST /api/admin/streams/{id}/grants`, `POST /api/admin/scan-subnet` (async, 202 + `job_id`, polling `GET /api/admin/scan-subnet/{job_id}`).
- **Admin pengguna**: `GET/POST /api/admin/users`, `PUT/DELETE /api/admin/users/{id}`, `POST /api/admin/users/{id}/camera-access`, `GET/POST /api/admin/admins/{id}/camera-grants`, `GET/POST /api/admin/groups`.
- **Iklan**: `GET /api/ad-config` (publik), `POST /api/admin/ad-config`, `POST /api/admin/ad-config/upload-image`.
- **API Key**: `GET/POST/PUT/DELETE /api/admin/api-keys`, `GET /api/admin/api-access-logs`.
- **Rekaman**: `GET /api/recordings/{id}/timeline`, `GET /api/recordings/{id}/file` (Range).
- **Drive**: `GET/POST /api/admin/drive/folders`, `POST /api/admin/drive/connect`.
- **Sistem**: `GET /api/health`, `GET /api/system/info`.
- **WebSocket**: `/ws?token=...` mengirim `snapshot` saat tersambung lalu `status` tiap ada perubahan online/offline.

### API eksternal (kontrak beku)

`GET /external/cameras`, `/external/stream`, `/external/playback`, `/external/playback/file`. Kunci lewat query `?key=` (plus `?pass=` dan `?camera=` atau `?stream_id=` bila perlu). Kegagalan validasi mengembalikan **403**. Embed memakai sesi JWT dengan klaim `stream_id` dan TTL per kunci.

## Status live

Status online/offline kamera dipantau lewat WebSocket `/ws`. Frontend menerima `snapshot` saat tersambung, lalu pembaruan `status` tiap ada perubahan, dan reconnect otomatis dengan backoff (maks 15 detik) plus refresh token bila kedaluwarsa. Bila WebSocket putus, UI memakai data terakhir dari API sampai tersambung lagi. Di balik Apache, pastikan `/ws` ikut di-proxy (lihat `deploy/apache/netra.mamura.net.id.conf`).

## Pengujian

```bash
cd apps/api
.venv/bin/pytest -q        # 207 tes
cd ../web
npx tsc --noEmit           # cek tipe
npm run build              # build + static export
```

## Dokumen terkait

- `docs/BLUEPRINT.md`: arsitektur dan keputusan desain
- `docs/MIGRATION-MAP.md`: peta 52 endpoint v2 ke router v3
- `docs/SECURITY-CHECKLIST.md`: daftar periksa keamanan
- `docs/CUTOVER.md`: runbook cutover ke `netra.mamura.net.id`
- `docs/GOOGLE-DRIVE.md`: rekaman ke Google Drive
- `docs/HARDENING.md`: pengerasan server
- `docs/analisa-menyeluruh-2026-11-11.md`: audit menyeluruh (133 temuan) dan perbaikannya
