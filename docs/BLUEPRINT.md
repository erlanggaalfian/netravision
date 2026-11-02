# NetraVision v3.0 — Blueprint Modernisasi Full-Stack

Dokumen perencanaan. Status: **DRAFT untuk dibahas**, belum ada kode ditulis.
Disusun 2026-11-02 dari inventarisasi repo `erlanggaalfian/cctv-monitoring` (v2.0.0 "Mamura Stream").

---

## 1. Ringkasan eksekutif

v2.0 adalah aplikasi yang *berfungsi* tapi dibangun dengan pola lama:

- Backend = **satu file** `main.py` 5.374 baris (semua endpoint, semua logika, campur aduk)
- Frontend = halaman PHP terpisah + vanilla JS (pola multi-page, bukan aplikasi real-time)
- Tanpa migrasi skema database yang terkontrol, tanpa test otomatis yang rapi, tanpa observability

v3.0 = **tulis ulang penuh (full rewrite), full-stack**, dengan teknologi terkini,
mempertahankan semua fitur yang sudah jalan dan semua pelajaran dari audit
keamanan v2.0 (48 temuan — dijadikan checklist wajib di §8).

Prinsip: **fitur dipertahankan, fondasi diganti.**

---

## 2. Inventarisasi v2.0 (faktual, dari repo)

| Aspek | Temuan |
|---|---|
| Endpoint API | 52 route (`/api/auth/*`, `/api/streams/*`, `/api/recordings/*`, `/api/admin/*`, `/api/external/*`) |
| Tabel database | 9: `users`, `cctv_streams`, `user_cctv_access`, `stream_permissions`, `stream_admin_grants`, `api_keys`, `api_key_cameras`, `api_access_logs`, `ad_config` |
| Halaman frontend | `live-monitor`, `playback`, `maps`, `custom-monitor`, `admin-console`, `login`, `embed` |
| Peran & akses | 3 peran (`admin`, `user`, `guest`) + hak per kamera per pengguna + grup wilayah |
| Rekaman | File segmen di disk + API timeline/segmen/unduh, retensi per kamera |
| Streaming | MediaMTX: RTSP kamera → WebRTC ke browser |
| Embed pihak ketiga | API key per kamera + batasan domain + kata sandi opsional + batas sesi + log akses |

Semua baris di tabel di atas **wajib ada** di v3.0 (peta migrasi di §7).

---

## 3. Arsitektur target v3.0

```
                    ┌─────────────┐
Kamera IP ──RTSP──▶ │   MediaMTX  │ ──WebRTC/WHEP──▶ Browser (Next.js)
                    └──────┬──────┘
                           │ recording
                    ┌──────▼──────┐      ┌──────────────┐
                    │  API (FastAPI modul) │◀────▶│  PostgreSQL  │
                    │  + WebSocket     │      │  +TimescaleDB│
                    └──────┬──────┘      └──────────────┘
                           │ events
                    ┌──────▼──────┐
                    │ AI Detector │ (worker terpisah, opsional GPU)
                    │ (YOLO)      │
                    └─────────────┘
```

### 3.1 Backend — Python + FastAPI (modular)

**Tetap Python/FastAPI** (bukan ganti bahasa) karena: tim sudah menguasainya,
ekosistemnya paling matang untuk kebutuhan CCTV modern (streaming + AI vision),
dan FastAPI adalah standar industri saat ini. Yang diganti adalah *polanya*:

- **Pecah monolith**: `routers/` (auth, streams, recordings, admin, external),
  `services/` (logika bisnis), `repositories/` (akses DB), `schemas/` (Pydantic v2),
  `core/` (config, security, deps). Target: tidak ada file > 500 baris.
- **Python 3.13/3.14**, **SQLAlchemy 2 async**, **Alembic** (migrasi skema terkontrol —
  v2.0 tidak punya ini), **Pydantic v2** untuk validasi.
- **Auth**: JWT access (pendek) + refresh token rotation (v2.0 memakai token
  statis yang lebih berisiko); RBAC 3 peran + grant per kamera dipertahankan;
  siap OIDC/passkey bila nanti dibutuhkan.
- **Upload/berkas**: tetap di disk untuk rekaman (pola v2.0 terbukti), dengan
  opsi S3-compatible (MinIO) untuk arsip jangka panjang.
- **Test**: pytest + httpx (v2.0 punya skrip `uji_*` manual — diganti test otomatis
  di CI).

*Alternatif yang dipertimbangkan dan tidak dipilih*: NestJS/TypeScript — bagus,
tapi memaksa tim pindah bahasa dan ekosistem AI vision-nya lebih tipis.

### 3.2 Frontend — Next.js + React + TypeScript

- **Next.js (App Router) + React 19 + TypeScript + Tailwind CSS v4**.
  Alasan: dashboard CCTV adalah aplikasi *real-time* (grid live, status kamera,
  timeline) — pola SPA modern jauh lebih cocok daripada halaman PHP terpisah.
  TypeScript menangkap bug sebelum runtime; ini kelas aplikasi yang paling
  diuntungkan.
- **PWA**: bisa "di-install" di HP petugas tanpa bikin aplikasi native dulu.
- **Fokus ganda mobile & desktop (terkunci 2026-11-02)**: keduanya warga kelas satu,
  bukan salah satu versi "ciutan" dari yang lain.
  - Mobile: pola collapsed-first accordion (ringkasan dulu, detail setelah tap),
    target sentuh ≥44px, input 16px (mencegah auto-zoom iOS), kontrol kamera
    tap-toggle ala YouTube, **tile kamera tidak pernah dilipat**,
    navigasi bawah yang ramah jempol.
  - Desktop: grid padat multi-kamera, panel admin lengkap, keyboard shortcut
    untuk operator (misal spasi = pause semua, F = fullscreen tile fokus).
  - PWA installable di kedua platform; app shell ter-cache.
- **Player**: WebRTC via WHEP (latensi rendah, seperti sekarang) + fallback HLS
  untuk jaringan buruk — v2.0 hanya mengandalkan satu jalur.
- **Peta**: tetap Leaflet (sudah dikuasai tim) atau MapLibre bila butuh vektor modern.
- **Design language**: adopsi vibekoding (sudah berjalan di beta v2.0) dalam warna
  NetraVision — tidak mulai dari nol secara visual.

*Alternatif*: Laravel + Livewire (konsisten dengan ARCHA). Layak **hanya** bila
prioritasnya satu bahasa di semua produk; untuk dashboard real-time berat,
Next.js lebih tepat. Keputusan final di tangan kamu (§9).

### 3.2 Streaming — MediaMTX dipertahankan

MediaMTX **sudah** teknologi terkini untuk kasus ini — tidak perlu diganti.
Yang ditingkatkan: pakai **WHIP/WHEP** (standar WebRTC modern) untuk publish/play,
tambah **HLS fallback**, dan health-check otomatis per path (auto-reconnect yang
sekarang manual di v2.0 dijadikan otomatis + terlihat statusnya di UI).
**Sub stream & main stream dipertahankan** (terkunci 2026-11-02): v2.0 menurunkan
URL sub-stream otomatis dari URL utama (`_main`→`_sub`, `/stream1`→`/stream2`,
dst.) dan mendaftarkan path `stream_{id}_sub` di MediaMTX — pola ini dibawa ke
v3.0 dan dijadikan strategi hemat bandwidth: **sub stream untuk grid** (banyak
kamera, ringan), **main stream untuk fokus/fullscreen** (satu kamera, tajam).

**Brand-aware stream resolver (terkunci 2026-11-02 — "lebih pintar untuk berbagai
macam brand CCTV")**: v2.0 hanya menebak pola URL dari segelintir brand. v3.0
memakai strategi berlapis:
1. **ONVIF dulu** (paling pintar): via WS-Discovery + GetProfiles + GetStreamUri,
   URI stream diambil *langsung dari kameranya* — tidak peduli brand apa.
   Ini standar industri dan menghilangkan tebakan.
2. **Template per brand** (bila ONVIF mati/tidak didukung): registry profil brand —
   Hikvision (`/Streaming/Channels/101`→`/102`), Dahua (`?channel=1&subtype=0`→`1`),
   Uniview (`/media/video1`→`/video2`, NVR `/unicast/c1/s0/live`→`/s1/live`),
   Hanwha (`/profile1/media.smp`→`/profile2/media.smp`), Axis
   (`/axis-media/media.amp`), TP-Link Vigi (`/stream1`→`/stream2`), Reolink,
   Foscam (`/videoMain`→`/videoSub`), Milesight (`/main`→`/sub`), dsb.
3. **Pola generik terakhir**: tebakan pola v2.0 sebagai usaha terakhir.
4. **Scan & preview ditingkatkan**: v2.0 sudah punya `/api/admin/scan` +
   `/scan/preview` — di v3.0 user pilih brand (atau "otomatis"), sistem mencoba
   kandidat berurutan, menampilkan preview tiap kandidat, user konfirmasi.
   Hasilnya disimpan eksplisit per kamera (`brand`, `main_url`, `sub_url`,
   `onvif_profile`) — tidak di-derive ulang setiap request.

### 3.4 Database — PostgreSQL (+ TimescaleDB)

- **PostgreSQL** menggantikan MariaDB: fitur JSONB, full-text search, dan
  `TimescaleDB` (hypertable) sangat cocok untuk **event kamera & timeline** —
  data deret-waktu yang di v2.0 tidak punya rumah yang layak.
- 9 tabel v2.0 dimigrasi 1:1 secara skema (peta di §7), lalu ditambah tabel baru:
  `detection_events`, `alerts`, `audit_logs` (jejak audit admin — temuan audit v2.0).
- Migrasi terkontrol via Alembic; data v2.0 bisa diimpor (skrip migrasi sekali jalan).

### 3.5 Real-time — WebSocket

Satu channel WebSocket terautentikasi untuk: status kamera (online/offline),
progres rekaman, alert deteksi, dan notifikasi admin. v2.0 melakukan polling
HTTP untuk hal-hal seperti ini — boros dan lambat.

### 3.6 AI Detection (fitur baru — yang bikin "terbaru" terasa)

Worker terpisah (bukan di API utama) menjalankan model **YOLO generasi terbaru**
untuk: deteksi orang, kendaraan, dan gerakan di zona yang ditentukan.
Hasilnya → `detection_events` → alert real-time via WebSocket + tandai di timeline
playback ("ada orang terdeteksi di menit 14:32" — bisa diklik langsung).
Berjalan di CPU (lambat, untuk 1–2 kamera) atau GPU (disarankan bila banyak kamera).
**Ini modul opsional** — v3.0 tetap rilis tanpanya, AI bisa Fase berikutnya.

### 3.7 Observability & DevOps (revisi 2026-11-02: Docker BOLEH, Apache tetap di 80/443)

Keputusan user (final): instalasi & update **langsung dari bash** via `install.sh`
/ `update.sh` (pola v2.0). **Komponen apa pun boleh di-Docker**, dengan satu
syarat keras: **port 80 dan 443 tetap milik Apache** untuk banyak virtualhost —
tidak ada container yang bind 80/443.

- **Front door**: Apache tetap memegang 80/443 + semua virtualhost yang sudah ada
  (termasuk TLS via certbot). Vhost `netra.mamura.net.id`: DocumentRoot →
  hasil build frontend; `ProxyPass /api/*` dan `/ws` → `127.0.0.1:<port-api>`.
- **Services di Docker** (bridge network, publish **hanya ke 127.0.0.1**):
  PostgreSQL (volume data di disk server), Redis, FastAPI (uvicorn),
  MediaMTX (**port UDP range** di-publish ke host untuk WebRTC — UDP tidak
  bentrok dengan 80/443), worker AI (Fase 6).
- **Frontend (Next.js)**: di-build menjadi static export di CI / saat update,
  disajikan Apache sebagai DocumentRoot — tanpa runtime Node di produksi.
- **`install.sh`**: cek/install Docker bila belum ada → buat volume & network →
  `docker compose up -d` → pasang config vhost Apache → `apachectl configtest` →
  reload. Idempoten (aman dijalankan ulang).
- **`update.sh`**: `git pull` → build frontend → `alembic upgrade head` →
  `docker compose up -d --build` → verifikasi health endpoint.
  Push ≠ deploy, tetap eksplisit.
- **CI GitHub Actions**: lint + typecheck + test + build di setiap push.
- **Observability**: logging terstruktur (JSON via `docker logs`/journald) +
  metrik Prometheus/Grafana.

Konsekuensi yang diterima: server butuh Docker terinstal (satu komponen baru),
ditukar dengan versi service yang terkunci rapi (Postgres/Redis/MediaMTX tidak
tergantung versi apt OS).

### 3.8 Penyimpanan rekaman: lokal / Google Drive / keduanya (terkunci 2026-11-02)

Opsi per kamera: **lokal saja** (pola v2.0), **Google Drive saja**, atau **keduanya**.

- **Lokal dulu, selalu**: segmen selalu ditulis ke disk lokal dulu (buffer) —
  perekaman tidak pernah bergantung pada jaringan/internet.
- **Uploader asinkron**: worker terpisah mengunggah segmen ke Google Drive
  (resumable upload + antrean retry). Struktur folder: `NetraVision/<nama-kamera>/`.
- **Auth**: OAuth2 akun Google milik user (setup sekali, refresh token disimpan
  di server) — file masuk ke Drive user sendiri, bukan akun service asing.
- **Playback**: segmen Drive di-stream via backend (proxy dengan Range request),
  jadi pemutar timeline tidak peduli segmennya di lokal atau di Drive.
- **Retensi per destinasi**: misal lokal 7 hari, Drive 30 hari — diatur per kamera.
- Keduanya = lokal + antrean upload; bila upload gagal, segmen tetap aman di lokal
  dan dicoba lagi otomatis.

Catatan jujur: butuh bandwidth upload yang cukup di server dan kuota Drive yang
memadai — ini dihitung saat Fase 3 (recording pipeline).

### 3.9 Keamanan (non-negotiable)

48 temuan audit v2.0 menjadi **checklist wajib lolos** sebelum v3.0 rilis —
termasuk: tidak ada kredensial di kode, rate-limit login, validasi ketat semua
input, security header, secret management via environment/vault, dan audit log
untuk semua aksi admin.
## 4. Struktur repo yang diusulkan (monorepo)

```
netravision-v3/
├── apps/
│   ├── api/                 # FastAPI modular
│   │   ├── routers/         # auth, streams, recordings, admin, external, ws
│   │   ├── services/        # logika bisnis
│   │   ├── repositories/    # akses DB
│   │   ├── schemas/         # Pydantic v2
│   │   ├── core/            # config, security, deps
│   │   └── alembic/         # migrasi skema
│   ├── web/                 # Next.js + TypeScript + Tailwind
│   │   └── app/             # (dashboard)/live, /playback, /maps, /admin, /embed
│   └── detector/            # worker AI (YOLO), opsional Fase 2
├── packages/
│   └── contracts/           # skema API bersama (OpenAPI → tipe TS otomatis)
├── deploy/
│   ├── apache/                  # vhost netra.mamura.net.id (DocumentRoot → apps/web/out, proxy /api/* & /ws → 127.0.0.1)
│   ├── docker-compose.yml       # postgres, redis, api, mediamtx, worker — publish HANYA ke 127.0.0.1 (80/443 tetap milik Apache)
│   ├── mediamtx.yml
│   ├── install.sh               # idempoten: cek docker → volume/network → compose up → vhost → apache reload
│   └── update.sh                # git pull → build frontend → alembic upgrade → compose up --build → health check
└── docs/
    ├── BLUEPRINT.md         # dokumen ini
    └── MIGRATION-MAP.md     # §7 yang diperluas saat eksekusi
```

Satu kontrak API (`contracts/`) dipakai backend & frontend — tipe TypeScript
di-generate otomatis dari OpenAPI. Ini menghilangkan seluruh kelas bug
"frontend kirim field yang backend tidak kenal" yang umum di v2.0.

## 5. Peta migrasi fitur (v2.0 → v3.0)

| v2.0 | v3.0 | Catatan |
|---|---|---|
| 52 endpoint di `main.py` | Router per domain di `apps/api/routers/` | Path `/api/*` **dipertahankan kompatibel** supaya embed pihak ketiga tidak rusak |
| Halaman PHP: live-monitor, playback, maps, custom-monitor, admin-console | Rute Next.js: `/live`, `/playback`, `/maps`, `/monitors`, `/admin` | custom-monitor → "tata letak kisi tersimpan" (fitur dipertahankan) |
| Embed `embed.php` + API key | Rute `/embed` + SDK kecil | Kontrak `/api/external/*` tidak berubah |
| Poster JPG per kamera | Tetap, via job terjadwal di API | — |
| Rekaman file + timeline API | Tetap + penanda event AI di timeline | Format segmen dipertahankan agar arsip lama tetap bisa diputar |
| Iklan/banner (`ad_config`) | Modul "pengumuman" di admin | Fitur dipertahankan apa adanya |
| Skrip `uji_*.py/js` manual | pytest + Playwright di CI | — |

## 6. Strategi eksekusi (full rewrite, paralel, bertahap)

v2.0 **tetap jalan di produksi** selama v3.0 dibangun. Tidak ada big-bang cutover.

- **Fase 0 — Fondasi** (repo, kontrak API dari 52 endpoint v2.0, Docker, CI, Alembic + skema 9 tabel)
- **Fase 1 — API inti**: auth + RBAC + streams + WebSocket status (frontend v2.0 masih bisa dipakai untuk verifikasi)
- **Fase 2 — Web v3.0**: live grid, playback+timeline, peta, admin console (paralel dengan Fase 1 akhir)
- **Fase 3 — Rekaman & embed**: recording pipeline, `/api/external/*` kompatibel penuh, migrasi data v2.0
- **Fase 4 — Hardening**: 48 checklist audit, observability, uji beban, PWA
- **Fase 5 — Cutover**: deploy berdampingan → alihkan domain → v2.0 pensiun
- **Fase 6 (opsional) — AI detection**: worker YOLO + alert + penanda timeline

Setiap fase berakhir dengan **demo yang bisa dibuka di browser** dan **gate persetujuan kamu**
sebelum lanjut — pola yang sama seperti project-project sebelumnya.

## 7. Yang TIDAK berubah (kontrak ke pengguna & mitra)

1. Path `/api/*` dan `/api/external/*` — embed pihak ketiga tidak boleh rusak.
2. Format segmen rekaman — arsip lama tetap bisa diputar.
3. Model peran: `admin` / `user` / `guest` + hak per kamera.
4. Domain produksi `netra.mamura.net.id` (cutover di Fase 5).
5. **Tidak ada fitur, grouping, maupun halaman yang dihilangkan** — semua yang ada
   di v2.0 dipertahankan dan hanya boleh *diperbarui/dimodernisasi*
   (keputusan terkunci 2026-11-02). Ini mencakup: grouping kamera/grup wilayah,
   custom monitor (tata letak kisi tersimpan), API key + embed, ad_config,
   poster otomatis, dan seluruh 52 endpoint.
6. **Deploy berdampingan** — v3.0 harus bisa jalan di server yang sama dengan
   banyak virtualhost Apache yang sudah ada, tanpa mengganggu vhost lain
   (pola: container di localhost port + reverse proxy per vhost; WebRTC/UDP
   langsung ke MediaMTX seperti sekarang).

## 8. Keputusan yang perlu kamu ambil

1. **Frontend: Next.js (rekomendasi saya) atau Laravel?** — Lihat §3.2. Ini keputusan
   terbesar; sisanya mengikuti.
   → **TERKUNCI 2026-11-02: Next.js** (React 19 + TypeScript + Tailwind v4).
   Mandat desain dari user: boleh diubah total **asal terlihat lebih modern,
   bagus, dan enak dilihat** — mengikuti design language vibekoding dalam warna
   NetraVision (konsisten dengan selera yang sudah dikunci di project lain:
   anti-slop, tidak terlihat AI-generik).
2. **Database: PostgreSQL (rekomendasi) atau tetap MariaDB?** — Postgres membuka
   TimescaleDB untuk event; MariaDB meminimalkan migrasi.
   → **TERKUNCI 2026-11-02: PostgreSQL** (user: "kalau memang lebih bagus" —
   dikonfirmasi: ya, lebih bagus untuk kebutuhan event/timeline/AI v3.0).
   Catatan deploy: server PostgreSQL diinstal di level OS (apt + systemd),
   bukan di venv — yang masuk venv hanya driver Python-nya (`psycopg`/`asyncpg`)
   + SQLAlchemy.
3. **AI detection**: masuk Fase 6 terpisah (rekomendasi), atau bareng v3.0?
   → **TERKUNCI 2026-11-02: modul opsional** — bisa di-enable/disable kapan saja;
   v3.0 inti di-build dulu tanpa AI. Arsitektur: worker terpisah (`apps/detector`)
   + tabel `detection_events`/`alerts` + flag konfigurasi per deployment;
   timeline playback disiapkan menampilkan penanda event (tampil hanya bila
   modul aktif).
4. **Nama produk**: ~~tetap **NetraVision**, atau kembali ke "Mamura Stream", atau nama baru?~~
   → **TERKUNCI 2026-11-02: NetraVision** (repo `erlanggaalfian/netravision` sudah dibuat, publik).
5. **Repo**: ~~monorepo baru `netravision-v3`, atau branch/repo dari `cctv-monitoring`?~~
   → **TERKUNCI 2026-11-02: repo baru** https://github.com/erlanggaalfian/netravision.git
   (monorepo `apps/api`, `apps/web`, `apps/detector` sesuai §4; upload dilakukan
   saat eksekusi dimulai — "nantinya").

## 9. Langkah berikut yang konkret

Setelah 5 keputusan di atas dikunci, saya susun:
`MIGRATION-MAP.md` (52 endpoint → router, per endpoint) + backlog Fase 0 yang siap dikerjakan.
Eksekusi tetap dengan gate per fase — tidak ada kode yang ditulis sebelum kamu bilang mulai.

---

*Catatan versi teknologi: "terbaru" di dokumen ini = versi stabil terkini saat blueprint
ditulis (Nov 2026). Saat eksekusi dimulai, versi dikunci ulang di `deploy/` dan dicatat.*
