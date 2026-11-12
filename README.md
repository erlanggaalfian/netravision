# NetraVision v3.0

Sistem monitoring CCTV modern. Tulis ulang penuh dari v2.0 ("Mamura Stream") dengan arsitektur modular, frontend baru, dan kontrak API yang dijaga kompatibel. Deploy di `netra.mamura.net.id`, berdampingan dengan virtualhost Apache lain. Port 80/443 tetap milik Apache.

## Daftar isi

- [Fitur](#fitur)
  - [Rekaman multi-disk](#rekaman-multi-disk)
- [Peran dan hak akses](#peran-dan-hak-akses)
- [Teknologi](#teknologi)
- [Struktur direktori](#struktur-direktori)
- [Struktur database](#struktur-database)
- [Instalasi](#instalasi)
- [Update dari v2.0](#update-dari-v20)
- [Update dari v3.0](#update-dari-v30)
- [Rollback ke v2.0](#rollback-ke-v20)
- [Uninstall](#uninstall)
- [Konfigurasi](#konfigurasi)
- [API](#api)
- [Status live](#status-live)
- [Pengujian](#pengujian)
- [Operasional dan troubleshooting](#operasional-dan-troubleshooting)
- [Dokumen terkait](#dokumen-terkait)

## Fitur

### Menonton

- **Live** (`/live`): grid kamera 1x1 sampai 4x4 di desktop, daftar di HP. Sub stream untuk grid, main stream untuk fokus. LQ/HQ, snapshot, fullscreen, putar ulang langsung dari tile. Status online/offline dipantau live lewat WebSocket.
- **Putar Ulang** (`/playback`): rekaman per kamera dengan timeline, navigasi tanggal, dan grid yang sama seperti Live.
- **Peta** (`/maps`): semua kamera di peta Leaflet/OpenStreetMap. Kamera berdekatan digabung jadi satu klaster berisi jumlah kamera saat zoom out, dan menyebar (spiderfy) saat zoom maksimal. Warna klaster mengikuti status: hijau bila semua kamera nyala, kuning bila ada yang mati, merah bila semua mati. Klik marker untuk popup, tombol **Edit Lokasi** (super admin) untuk memindahkan posisi, lalu **Save Lokasi** atau **Batal**.
- **Monitor** (`/monitors`): layout kamera tersimpan (grid custom) plus grup kamera yang bisa dibuka langsung dari daftar. Layar penuh memakai grid sama tinggi, nama kamera disembunyikan, iklan masuk ke dalam frame.
- **Embed** (`/embed`): sematkan satu kamera ke situs lain lewat API Key, dengan sesi token, batas domain, dan TTL sesi.

### Admin (`/admin`)

- **Kamera** (`/admin/streams`): tambah, ubah, hapus, bagikan ke pengguna, bulk set koordinat dan grup, folder Google Drive per kamera, tombol Lihat (popup live yang sama seperti Live).
- **Pengguna** (`/admin/users`): kelola akun dan grup wilayah, akses kamera per pengguna (Live/Playback/Bagikan), bulk set grup. Admin hanya mengelola grupnya sendiri; super admin mengelola semua.
- **Grup Kamera** (`/admin/groups`): kelompokkan kamera, atur akses per grup.
- **Iklan** (`/admin/ads`): teks berjalan (marquee) dan gambar sponsor di bawah video. Jenis tampilan Selalu Tampil atau Berkala (interval, hover, klik). Iklan bisa dimatikan per pengguna, per grup, dan per API Key. Ada pratinjau langsung (live preview) di halaman.
- **API Key** (`/admin/keys`): kunci akses eksternal dengan batas domain, password, masa berlaku, TTL sesi, nama kamera custom, opsi playback, dan opsi iklan. Log akses per kunci bisa dilihat dan dihapus.
- **Scanner** (`/admin/scanner`): pindai subnet untuk menemukan kamera RTSP/ONVIF (12 brand, termasuk Ezviz). Scan berjalan async (202 + `job_id`, polling tiap 2 detik) supaya tidak timeout di balik Cloudflare.
- **Penyimpanan** (`/admin/storage`): tautan folder Google Drive (rclone) dan akun OAuth untuk rekaman.
- **Akses tamu (guest)**: login tanpa password untuk pengunjung, bisa diaktifkan/dimatikan, dengan akses kamera dan iklan yang bisa diatur. Dibuat otomatis dalam posisi nonaktif bila database di-reset.

### Rekaman multi-disk

Setiap kamera bisa menyimpan rekaman ke disk yang berbeda lewat kolom `record_disk`. Pilih disk per kamera di menu **Kamera** (`/admin/streams`), seksi **Rekaman & lokasi**, kolom **SAVE TO DISK**. Bila kolom ini kosong, rekaman memakai `recordings_dir` default seperti sebelumnya.

Path rekaman dibuat otomatis mengikuti disk yang dipilih: `{disk}/recordings/{grup}/{nama_kamera}/stream_{id}/`. MediaMTX memakai `recordPath` per kamera yang di-set lewat API, jadi rekaman langsung ditulis ke disk tersebut.

Cleanup otomatis berjalan saat disk hampir penuh: ambang batas default 90 persen, target 85 persen, interval 300 detik. Cleanup hanya menghapus segmen yang sudah ter-upload, dan hanya untuk kamera mode `drive` atau `both`, supaya rekaman yang belum ter-upload ke Drive tidak hilang.

Syarat Docker: disk tambahan harus di-bind-mount ke container `mediamtx` DAN `api` dengan path yang sama, supaya keduanya bisa membaca dan menulis path itu. Lihat contoh yang dikomentari di `deploy/docker-compose.yml` pada bagian `volumes` kedua service tersebut.

## Peran dan hak akses

| Peran | Hak |
|---|---|
| `super_admin` | Kuasa penuh: semua kamera, pengguna, grup, iklan, API Key, scanner, penyimpanan. |
| `admin` | Mengelola pengguna di grupnya sendiri, membagikan kamera yang diizinkan super admin ke user/guest di grupnya. Tidak bisa tambah/ubah/hapus kamera, iklan, API Key, scanner, atau penyimpanan. |
| `user` | Menonton kamera yang dibagikan, sesuai akses Live/Playback. |
| `guest` | Pengunjung tanpa password, akses kamera diatur super admin. |

Akses kamera per pengguna diatur dua arah: per kamera (menu Bagikan) dan per pengguna (menu Pengguna, Akses Kamera). Keduanya saling melengkapi dan tidak saling menghapus di luar cakupan admin yang menyimpan. Admin membagikan kamera hanya bila super admin memberinya hak `can_reshare` untuk kamera itu.

## Teknologi

| Lapisan | Stack |
|---|---|
| Backend | FastAPI (Python 3.12), SQLAlchemy 2 + Alembic, PostgreSQL 16 + TimescaleDB, JWT 15 menit + refresh 7 hari, WebSocket status live |
| Frontend | Next.js 15 + React 19 + TypeScript + Tailwind v4 (static export), PWA, mode terang/gelap |
| Streaming | MediaMTX (RTSP ke WebRTC via WHIP/WHEP), sub + main stream |
| Rekaman | Lokal per kamera dan/atau Google Drive (rclone + OAuth), retensi per kamera |
| Deploy | Bash `install.sh`/`update.sh`/`rollback.sh`/`uninstall.sh`, Docker Compose (container hanya 127.0.0.1), Apache reverse proxy `/api/*`, `/ws`, `/whep/`, `/hls/` |
| Deteksi AI | Modul opsional (worker YOLO), bisa diaktifkan/dimatikan |

## Struktur direktori

```text
netravision/
  README.md               # dokumen ini
  apps/
    api/                  # Backend FastAPI
      app/
        main.py           # titik masuk FastAPI
        core/             # config, keamanan, RBAC, rate limit, deps
        db/               # session, base model
        models/           # users, streams, groups, access, keys, drive, misc
        routers/          # auth, streams, admin_streams, admin_users,
                          # admin_ads, admin_keys, admin_scan, admin_drive,
                          # recordings, external, ws, system
        schemas/          # validasi Pydantic
        services/         # MediaMTX, RTSP discovery, poster, recording, Drive
      alembic/            # migrasi database (head: 0018)
      alembic.ini
      tests/              # pytest, 207 tes
      Dockerfile          # WORKDIR /srv/api, uvicorn :8000
      requirements.lock
      .env.example
    web/                  # Frontend Next.js (static export)
      app/
        live/             # Live grid
        playback/         # Putar Ulang
        maps/             # Peta Leaflet + klaster
        monitors/         # Monitor tersimpan + grup kamera
        embed/            # halaman embed publik
        login/            # login + guest
        admin/            # streams, users, groups, ads, keys, scanner, storage
          _nb.tsx         # komponen bersama admin (NBButton, NBBadge, NBField, ...)
        layout.tsx        # shell aplikasi (sidebar, tab bar HP, tema)
        globals.css       # token tema --nv-*, .nv-cluster, .nv-stage, ...
      components/         # CameraTile, FocusModal, AdBanner, ShareModal, ui
      hooks/              # useCameraStatus (WebSocket live)
      lib/                # api client, auth, types
      next.config.ts      # static export (output: export)
      package.json
    detector/             # Worker AI detection (YOLO), modul opsional
  packages/
    contracts/            # Kontrak OpenAPI, sumber kebenaran API
  deploy/
    apache/
      netra.mamura.net.id.conf   # vhost Apache (80 redirect, 443 SSL + proxy)
    docker-compose.yml    # postgres, redis, migrate, api, mediamtx, netravision
    mediamtx.yml          # konfigurasi MediaMTX
    install.sh            # instalasi awal (idempoten)
    update.sh             # update v3.0 ke v3.0 (idempoten)
    rollback.sh           # kembali ke v2.0 bila cutover gagal
    uninstall.sh          # hapus instalasi v3.0
    migrate-v2.py         # migrasi data MariaDB v2.0 ke PostgreSQL v3.0
    seed_admin.py         # buat akun admin awal
    .env.example          # contoh variabel environment deploy
  docs/
    BLUEPRINT.md            # arsitektur dan keputusan desain
    MIGRATION-MAP.md        # peta 52 endpoint v2 ke router v3
    SECURITY-CHECKLIST.md   # daftar periksa keamanan
    CUTOVER.md              # runbook cutover ke produksi (Fase A-H)
    GOOGLE-DRIVE.md         # rekaman ke Google Drive
    HARDENING.md            # pengerasan server
    analisa-menyeluruh-2026-11-11.md  # audit 133 temuan dan perbaikannya
    analisa-v2/             # analisis kesenjangan v2 vs v3
  scripts/
    preflight.py          # cek prasyarat sebelum install
    smoke_test.py         # uji asap pasca install
    load_test.py          # uji beban
  data/
    uploads/              # file upload (iklan) di repo, disajikan via /api/uploads
```

### Service Docker Compose

| Service | Image | Keterangan |
|---|---|---|
| `postgres` | postgres:18-alpine | Database utama. Tidak ada port publik, hanya diakses dari dalam network. Volume `pgdata`. |
| `redis` | redis:7-alpine | Cache/queue. Tidak ada port publik. Volume `redisdata`. |
| `migrate` | (image api) | Menjalankan `alembic upgrade head` sekali saat compose up. |
| `api` | (build `apps/api`) | FastAPI di `127.0.0.1:8100` (host) ke `:8000` (container). |
| `mediamtx` | bluenviron/mediamtx:latest-ffmpeg | RTSP/WebRTC. UDP 8189 (WebRTC) dan port API/WHEP. Volume `recordings`. |
| `netravision` | (opsional) | Service tambahan bila didefinisikan di compose. |

Volume: `pgdata`, `redisdata`, `recordings`, `apidata` (plus `gdrive_staging` untuk staging rclone bila dipakai).

### Apache vhost

`deploy/apache/netra.mamura.net.id.conf` berisi dua blok: port 80 redirect permanen ke HTTPS, dan port 443 dengan sertifikat Let's Encrypt. DocumentRoot `/var/www/netravision/out` (hasil static export frontend). Proxy yang diteruskan:

| Path | Tujuan |
|---|---|
| `/api/` | `http://127.0.0.1:8100/api/` |
| `/ws` | `ws://127.0.0.1:8100/ws` (WebSocket status live) |
| `/whep/` | `http://127.0.0.1:8889/` (sinyal WebRTC MediaMTX) |
| `/hls/` | `http://127.0.0.1:8888/` (HLS MediaMTX) |

## Struktur database

PostgreSQL 16. Migrasi Alembic di `apps/api/alembic/versions/`, head saat ini **0018**, total **19 tabel** (termasuk satu tabel backup internal `_backup_0014_super_admin_group` dari migrasi 0014).

### Tabel pengguna dan peran

**`users`**: akun semua peran.

| Kolom | Keterangan |
|---|---|
| `id` | PK |
| `username` | unik, maks 64 karakter |
| `password_hash` | bcrypt; guest memakai `!` (tidak bisa login pakai password) |
| `role` | `super_admin`, `admin`, `user`, `guest` |
| `is_active` | akun aktif; untuk guest artinya login tamu diizinkan |
| `show_ads` | tampilkan iklan untuk pengguna ini |
| `parent_admin_id` | FK ke `users.id` (SET NULL bila admin induk dihapus); cakupan manajemen user |
| `admin_group` | grup wilayah, maks 60 karakter; NULL untuk super_admin dan pengguna lepas |
| `refresh_token_hash` | hash refresh token (rotasi 7 hari) |
| `created_at`, `updated_at` | timestamp |

Aturan: super_admin selalu `admin_group = NULL` (migrasi 0014). Admin baru tanpa grup mendapat default `grup-{username}`. Guest tidak bisa dibuat manual (ditolak 400) dan hanya `is_active` + `show_ads` yang bisa diubah.

### Tabel kamera

**`streams`**: kamera.

| Kolom | Keterangan |
|---|---|
| `id` | PK |
| `name` | nama kamera |
| `rtsp_url` | URL RTSP (utama) |
| `brand` | brand (12 template: Hikvision, Dahua, Ezviz, dan lain-lain) |
| `main_url`, `sub_url` | URL main/sub stream hasil resolver (ONVIF dulu, lalu template brand) |
| `onvif_profile` | profil ONVIF yang dipakai |
| `group_name` | nama grup lama (kompatibilitas; grup baru memakai `stream_groups`) |
| `latitude`, `longitude` | koordinat peta (NULL = belum dipetakan) |
| `is_active` | kamera aktif; nonaktif tidak menghapus, bisa diaktifkan lagi |
| `is_online` | status live terakhir (diperbarui WebSocket + health check) |
| `last_seen_at` | terakhir terlihat online |
| `recording_enabled` | rekaman aktif |
| `retention_days` | retensi rekaman lokal (hari) |
| `storage_mode` | `local`, `drive`, atau `both` |
| `owner_id` | pemilik kamera (FK users) |
| `created_by` | yang membuat (FK users) |
| `drive_account_id`, `drive_folder_id` | tujuan rekaman Drive |

### Tabel akses

**`user_stream_access`**: akses kamera per pengguna (ditulis oleh menu Bagikan per kamera dan menu Akses Kamera per pengguna).

| Kolom | Keterangan |
|---|---|
| `id`, `user_id`, `stream_id` | PK + FK |
| `can_view` | boleh lihat live |
| `can_control` | boleh kontrol (PTZ dan sejenisnya) |
| `can_playback` | boleh putar rekaman |

**`stream_permissions`**: izin per peran per kamera (warisan v2).

| Kolom | Keterangan |
|---|---|
| `id`, `stream_id`, `role` | PK + FK + peran |
| `user_id` | FK users (nullable, untuk izin per pengguna) |
| `can_view`, `can_download`, `can_playback` | izin |

**`stream_admin_grants`**: grant admin per kamera (super admin yang mengatur).

| Kolom | Keterangan |
|---|---|
| `id`, `stream_id`, `admin_id` | PK + FK |
| `can_manage` | (deprecated, tidak dipakai) |
| `can_view` | admin boleh lihat live |
| `can_playback` | admin boleh putar rekaman |
| `can_reshare` | admin boleh membagikan kamera ini ke user/guest di grupnya (otomatis mengaktifkan `can_view`) |
| `granted_by` | super admin yang memberi |

Grant tanpa `can_view` dan tanpa `can_playback` akan menghapus barisnya.

### Tabel grup

**`stream_groups`**: grup kamera.

| Kolom | Keterangan |
|---|---|
| `id`, `name`, `description` | PK, nama grup, deskripsi |

**`group_streams`**: anggota grup (many-to-many).

| Kolom | Keterangan |
|---|---|
| `id`, `group_id`, `stream_id` | PK + FK |

### Tabel API Key

**`api_keys`**: kunci akses eksternal.

| Kolom | Keterangan |
|---|---|
| `id`, `name` | PK, nama kunci |
| `key_hash` | SHA256 kunci (hanya hash yang disimpan; kunci asli ditampilkan sekali saat dibuat) |
| `domain_lock` | batas domain (Referer/Origin) |
| `password_hash` | password kunci (opsional) |
| `expires_at` | masa berlaku (NULL = tidak kedaluwarsa) |
| `is_active` | kunci aktif |
| `last_used_at` | terakhir dipakai |
| `session_ttl_mnt` | TTL sesi embed (menit, NULL = default) |
| `custom_camera_name` | nama kamera custom di embed |
| `include_playback` | izinkan playback lewat kunci ini (default true) |
| `show_ads` | tampilkan iklan lewat kunci ini (default true) |

**`api_key_streams`**: kamera yang boleh diakses satu kunci (`api_key_id`, `stream_id`, `position`).

**`api_access_logs`**: log tiap percobaan akses kunci (`api_key_id`, `stream_id`, `action`, `ip`, `user_agent`, `created_at`).

### Tabel Drive

**`drive_accounts`**: akun Google OAuth (token terenkripsi Fernet).

| Kolom | Keterangan |
|---|---|
| `id` (UUID), `name` | PK, nama akun |
| `token_encrypted` | token OAuth terenkripsi |
| `root_folder_id` | folder root Drive |
| `is_default` | akun default |
| `status`, `last_error` | status koneksi dan error terakhir |
| `created_at`, `updated_at` | timestamp |

**`google_drive_folders`**: tautan folder Drive (mode folder-link + rclone).

| Kolom | Keterangan |
|---|---|
| `id`, `folder_url`, `folder_id`, `folder_name` | PK, URL, ID, nama folder |
| `local_path` | mount rclone lokal |
| `created_at`, `updated_at`, `updated_by` | timestamp + yang menambah |

**`google_drive_settings`**: satu baris pengaturan Drive (`folder_url`, `folder_id`, `folder_name`, `updated_at`, `updated_by`).

**`drive_uploads`**: antrean/log upload rekaman ke Drive (`stream_id`, `segment_name`, `folder_id`, `uploaded_at`).

### Tabel lain

**`ad_config`**: konfigurasi iklan sebagai key/value JSON (`key`, `value`, `updated_at`). Kunci `default` menyimpan seluruh pengaturan (mode tampil, marquee, gambar, warna, ukuran). Menambah field tidak butuh migrasi.

**`detection_events`**: event deteksi AI (`stream_id`, `event_type`, `confidence`, `detected_at`, `snapshot_path`, `meta`).

**`alerts`**: peringatan (`user_id`, `stream_id`, `event_id`, `message`, `is_read`).

**`audit_logs`**: jejak audit (`actor_id`, `action`, `resource`, `resource_id`, `detail`, `ip`, `created_at`).

**`_backup_0014_super_admin_group`**: backup internal dari migrasi 0014 (grup super admin sebelum dihapus). Bukan tabel aplikasi.

## Instalasi

Instalasi baru di server kosong (belum ada v2.0 maupun v3.0).

### Prasyarat

- Ubuntu/Debian server, akses root atau sudo
- Docker + Docker Compose plugin
- Apache2 (port 80/443 milik Apache)
- `openssl`, `curl`
- Sertifikat Let's Encrypt untuk domain (buat dulu dengan certbot, karena install memeriksa keberadaannya)
- Node.js 20+ dan Python 3.12+ hanya bila build lokal (tidak wajib di server, build frontend memakai container Node 20)

### Langkah

```bash
git clone https://github.com/erlanggaalfian/netravision.git
cd netravision
sudo ./deploy/install.sh
```

`install.sh` idempoten dan aman dijalankan ulang. Urutannya:

0. Pastikan Apache berjalan (enable dan start bila perlu), lalu preflight check (`scripts/preflight.py`). Gagal berarti berhenti.
1. Cek prasyarat: root, docker, docker compose plugin, apache2, openssl, curl, dan `apps/api/Dockerfile`.
2. Siapkan `deploy/.env` dari `.env.example` (tidak ditimpa bila sudah ada). Generate acak `POSTGRES_PASSWORD`, `JWT_SECRET`, `REDIS_PASSWORD`, dan `DRIVE_TOKEN_KEY` (kunci Fernet 44 karakter) bila masih placeholder atau kosong.
3. Hentikan mediamtx v2.0 bila masih jalan (membebaskan UDP 8189), lalu `docker compose up -d`, tunggu PostgreSQL sehat (maks 90 detik).
4. Migrasi Alembic (`alembic upgrade head`) di dalam container api.
5. Seed admin awal, hanya bila `NV_ADMIN_USER` dan `NV_ADMIN_PASS` diset di environment.
6. Siapkan file vhost Apache untuk domain (default `netra.mamura.net.id`, bisa override `DOMAIN=...`). File disiapkan saja, BELUM diaktifkan. Cek sertifikat ada, aktifkan modul Apache yang dibutuhkan (`proxy`, `proxy_http`, `proxy_wstunnel`, `rewrite`, `ssl`, `headers`).
7. Health check `GET /api/health`.

Setelah install, v2.0 tetap melayani (vhost belum diganti). Lanjut ke cutover di `docs/CUTOVER.md` bila ini instalasi berdampingan dengan v2.0. Bila ini server baru tanpa v2.0, aktifkan vhost sendiri:

```bash
sudo a2ensite netra.mamura.net.id
sudo systemctl reload apache2
```

### Instalasi lokal (pengembangan, tanpa Docker)

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

MediaMTX dan PostgreSQL tetap dibutuhkan untuk streaming dan data. Tanpa MediaMTX, health API berstatus `degraded` (normal) dan tile menampilkan poster.

## Update dari v2.0

Update dari v2.0 ("Mamura Stream", PHP + MariaDB) ke v3.0 adalah **migrasi**, bukan update biasa. v2.0 dan v3.0 berjalan berdampingan sampai cutover. Runbook lengkap ada di `docs/CUTOVER.md` (Fase A sampai H). Ringkasnya:

### Fase A: Backup v2.0

```bash
# Dump database v2.0 (MariaDB) dan simpan di tempat aman
mysqldump -u <v2_user> -p <v2_db> > /backup/netravision-v2-<TANGGAL>.sql
# Backup juga vhost Apache v2.0
sudo cp /etc/apache2/sites-available/<vhost-v2>.conf /etc/apache2/sites-available/<vhost-v2>.conf.bak.v2
```

### Fase B: Preflight

```bash
python3 scripts/preflight.py
```

Memastikan Apache listen 80/443, Docker tersedia, port yang dibutuhkan bebas, dan domain bisa dijangkau.

### Fase C: Install v3.0

```bash
sudo ./deploy/install.sh
```

v3.0 terpasang berdampingan. v2.0 tetap melayani karena vhost belum diganti.

### Fase D: Migrasi data v2.0 ke v3.0

```bash
# Dry-run dulu: hanya menghitung dan melaporkan, tanpa menulis apa pun
python3 deploy/migrate-v2.py
# Bila laporan sudah benar, eksekusi
python3 deploy/migrate-v2.py --apply
```

`migrate-v2.py` memindahkan pengguna (hash password bcrypt disalin apa adanya, tidak di-re-hash), kamera, grup, akses, dan konfigurasi iklan dari MariaDB v2.0 ke PostgreSQL v3.0. ID asli dipertahankan. Peran v2.0 dipetakan: `admin` v2.0 menjadi `super_admin` bila memang admin utama, selebihnya mengikuti `ROLE_MAP` di script. Script menolak bila tabel tujuan sudah berisi data, kecuali `--force`.

File rekaman TIDAK ikut pindah oleh migrasi database saja. Pindahkan dengan:

```bash
python3 deploy/migrate-v2.py --apply --copy-recordings \
  --v2-recordings-dir /var/lib/cctv/recordings \
  --v3-recordings-dir /var/lib/docker/volumes/netravision_recordings/_data
```

Arsip v2.0 jangan dihapus sebelum verifikasi ukuran per file selesai (CUTOVER Fase H).

### Fase E: Seed admin dan smoke test

```bash
NV_ADMIN_USER=admin NV_ADMIN_PASS='<rahasia>' sudo -E ./deploy/install.sh
python3 scripts/smoke_test.py
```

### Fase F: Switch (maintenance window, umumkan dulu)

```bash
sudo a2ensite netra.mamura.net.id
sudo a2dissite <vhost-v2>
sudo apachectl configtest && sudo systemctl reload apache2
```

Mulai titik ini domain dilayani v3.0.

### Fase G: Rollback (hanya bila gagal)

Lihat [Rollback ke v2.0](#rollback-ke-v20).

### Fase H: Pensiun v2.0 (setelah v3.0 stabil minimal 30 hari)

Hentikan service v2.0 dan MediaMTX v2.0, hapus vhost v2.0, dan arsipkan (bukan hapus) database serta file rekaman v2.0.

## Update dari v3.0

Update v3.0 ke v3.0 yang lebih baru (mis. setelah `git pull` ada commit baru).

```bash
cd /path/ke/netravision
sudo ./deploy/update.sh
```

`update.sh` idempoten dan aman dijalankan ulang. Urutannya:

1. `git pull --ff-only` (fast-forward saja; gagal bila ada konflik atau perubahan lokal yang belum commit).
2. Build frontend di container Node 20 (`npm ci && npm run build`), lalu sinkronkan `apps/web/out` ke DocumentRoot `/var/www/netravision/out` (rsync `--delete`, atau hapus lalu salin bila rsync tidak ada).
3. `docker compose up -d --build` (rebuild image api dengan kode dan migrasi terbaru).
4. Migrasi database (`alembic upgrade head`) di dalam image baru. Migrasi sengaja dijalankan SETELAH rebuild, supaya file migrasi baru sudah ada di image (bila migrasi jalan sebelum rebuild, migrasi baru tidak pernah diterapkan karena image lama tidak punya filenya).
5. Health check `GET /api/health` dengan retry sampai 60 detik.

Bila update gagal di tengah jalan, perbaiki penyebabnya lalu jalankan ulang `update.sh`. Bila ingin kembali ke v2.0, lihat [Rollback ke v2.0](#rollback-ke-v20).

## Rollback ke v2.0

Mengembalikan server ke v2.0 bila cutover v3.0 gagal.

```bash
sudo ./deploy/rollback.sh
```

Yang dilakukan:

1. Restore vhost Apache v2.0 dari backup terbaru (`.bak-YYYYMMDDHHMMSS` dari install.sh, atau `.bak.v2` dari Fase A; yang terbaru yang dipakai). Nonaktifkan vhost v3, aktifkan vhost v2.0, `configtest`, lalu reload Apache.
2. Matikan stack Docker v3.0 (`docker compose down`). Volume data sengaja dipertahankan untuk investigasi.
3. Jalankan ulang mediamtx v2.0 dan service aplikasi v2.0 (bila berupa unit systemd; nama unit bisa dioverride `V2_APP_SERVICE=...`).
4. Restore database v2.0 dari dump Fase A, HANYA bila dikonfirmasi interaktif (destruktif; default dilewati, karena migrasi v3.0 hanya membaca database v2.0 dan tidak pernah mengubahnya).

Nama vhost v2.0 bisa dioverride: `V2_VHOST_NAME=... ./deploy/rollback.sh`. Script aman dijalankan non-interaktif: pertanyaan konfirmasi default ke "tidak" bila stdin tertutup.

## Uninstall

Menghapus instalasi v3.0 dari server.

```bash
sudo ./deploy/uninstall.sh
sudo ./deploy/uninstall.sh --yes --delete-data
sudo ./deploy/uninstall.sh --yes --delete-data --delete-repo
```

Opsi:

| Opsi | Keterangan |
|---|---|
| `--yes` | Lewati semua konfirmasi (untuk otomatisasi) |
| `--delete-data` | Hapus juga volume Docker (database, rekaman, upload). Destruktif. |
| `--delete-repo` | Hapus juga direktori repo ini setelah selesai (termasuk `.env` dan riwayat git lokal). Destruktif. |

Yang dilakukan:

1. Matikan stack Docker v3.0. Tanpa `--delete-data`, volume dipertahankan dan script memberi tahu perintah manual untuk menghapusnya.
2. Nonaktifkan dan hapus vhost Apache v3.0, lalu reload Apache. Vhost lain dan vhost v2.0 tidak disentuh. Backup vhost (`.bak-*`) tidak dihapus.
3. Hapus DocumentRoot frontend (`/var/www/netravision/out`).
4. Bila `--delete-repo`, hapus direktori repo setelah script keluar (dijadwalkan 3 detik kemudian, karena script ini tinggal di dalam repo).

Yang TIDAK dilakukan: menghapus Docker itu sendiri, menghapus Apache, menghapus database v2.0 (MariaDB), menghapus sertifikat Let's Encrypt, menghapus backup vhost. Script idempoten: langkah yang sudah tidak ada dilewati, bukan gagal.

## Konfigurasi

Salin `deploy/.env.example` ke `deploy/.env` (untuk Docker) atau `apps/api/.env.example` ke `apps/api/.env` (untuk jalan lokal). Jangan commit `.env` berisi rahasia asli. `install.sh` mengisi rahasia yang masih placeholder secara otomatis.

| Variabel | Keterangan |
|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database PostgreSQL di compose |
| `API_PORT` | Port API di host (default 8100); harus sama dengan vhost Apache |
| `DATABASE_URL` | URL PostgreSQL, contoh `postgresql+psycopg://netravision:pass@127.0.0.1:5432/netravision` |
| `JWT_SECRET` | Rahasia JWT, wajib diganti di produksi (acak, minimal 32 karakter) |
| `JWT_ACCESS_MINUTES` | Umur access token (default 15) |
| `JWT_REFRESH_DAYS` | Umur refresh token (default 7) |
| `REDIS_PASSWORD` | Password Redis internal |
| `PUBLIC_BASE_URL` | URL publik aplikasi (untuk link dan embed) |
| `POSTERS_ENABLED` | Buat poster kamera berkala (butuh ffmpeg) |
| `POSTER_INTERVAL_SEC` | Interval poster (default 60 detik) |
| `RETENTION_ENABLED` | Hapus rekaman lokal melewati retensi |
| `DRIVE_ENABLED` | Aktifkan integrasi Google Drive |
| `DRIVE_FOLDER_ROOT` | Folder root Drive untuk rekaman |
| `DRIVE_RETENTION_DAYS` | Retensi rekaman di Drive (hari) |
| `DRIVE_TOKEN_KEY` | Kunci Fernet 44 karakter untuk enkripsi token Drive |
| `GUEST_ENABLED` | Login tamu aktif atau tidak (default false; guest dibuat nonaktif) |
| `MEDIAMTX_API_URL` | API MediaMTX (default `http://127.0.0.1:9997`, di compose `http://mediamtx:9997`) |
| `MEDIAMTX_WHEP_BASE` | Base WHEP MediaMTX (default `http://127.0.0.1:8889`) |
| `WEBRTC_ADDITIONAL_HOSTS` | IP/domain publik server untuk WebRTC (wajib diisi di `deploy/.env`) |

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
python3 scripts/smoke_test.py   # uji asap pasca install
python3 scripts/load_test.py    # uji beban
```

## Operasional dan troubleshooting

| Gejala | Kemungkinan penyebab dan perbaikan |
|---|---|
| `GET /api/health` gagal | Cek `docker compose logs api`; pastikan PostgreSQL sehat (`docker compose exec postgres pg_isready`); pastikan migrasi sudah jalan. |
| Health `degraded` | Normal bila MediaMTX belum jalan; tile menampilkan poster. Cek `docker compose ps mediamtx`. |
| Status kamera tidak ter-update (sidebar terus "Menghubungkan…") | WebSocket `/ws` tidak tersambung. Pastikan Apache mem-proxy `/ws` ke `ws://127.0.0.1:8100/ws` dan API berjalan. |
| Scan subnet timeout / 524 | Scan lama sudah async (202 + polling). Bila masih timeout, pastikan akses via domain tidak memotong request; scan berjalan lokal di server. |
| Kamera nonaktif lalu diaktifkan error "stream tidak ditemukan" | Sudah diperbaiki (admin endpoint tidak lagi menolak kamera nonaktif). Update ke rilis terbaru. |
| Marker peta tidak muncul | Pastikan kamera punya koordinat (menu Kamera, bulk set koordinat, atau Edit Lokasi di peta). Periksa console browser. |
| Guest tidak bisa login | Guest dibuat nonaktif secara default. Aktifkan di Pengguna, Ubah Guest, nyalakan Login Guest. |
| Iklan tidak muncul | Cek `GET /api/ad-config` (publik): `is_active` harus true, pengguna/grup/API Key harus mengizinkan iklan, dan mode tampil harus sesuai. |
| `git pull` gagal di update.sh | Ada konflik atau perubahan lokal. Selesaikan manual (`git status`, `git stash` bila perlu), lalu jalankan ulang. |

### Perintah darurat

```bash
# Status cepat
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs api --tail 100
# Log
docker compose -f deploy/docker-compose.yml logs -f api
# Rollback total (ke v2.0)
sudo ./deploy/rollback.sh
```

## Dokumen terkait

- `docs/BLUEPRINT.md`: arsitektur dan keputusan desain
- `docs/MIGRATION-MAP.md`: peta 52 endpoint v2 ke router v3
- `docs/SECURITY-CHECKLIST.md`: daftar periksa keamanan
- `docs/CUTOVER.md`: runbook cutover ke `netra.mamura.net.id`
- `docs/GOOGLE-DRIVE.md`: rekaman ke Google Drive
- `docs/HARDENING.md`: pengerasan server
- `docs/analisa-menyeluruh-2026-11-11.md`: audit menyeluruh (133 temuan) dan perbaikannya
- `docs/analisa-v2/`: analisis kesenjangan v2 vs v3
