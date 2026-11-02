# 04 — Fungsional Backend: Inventarisasi V2 vs Paritas V3

> Analisa READ-ONLY. Sumber V2: `/tmp/v2-ref/backend/main.py` (5.374 baris, "Mamura Stream" v2.0).
> Pembanding V3: `~/workspace/netravision/apps/api/app`.
> Aturan Zero Deprecation: yang dicatat di sini adalah FUNGSI, bukan sekadar path URL.
> Status: **ADA** = fungsi tersedia di V3 · **BERBEDA** = ada tapi perilaku/kontrak berubah ·
> **HILANG** = tidak ada di V3 (wajib dipulihkan).

**Ringkasan angka:** V2 = **52 endpoint**. V3 = **67 route** (52 + tambahan: refresh/logout/me,
drive-accounts, scan-subnet, role-access, playback/file, dsb).
Dari 52 fungsi V2: **~28 ADA penuh**, **~18 BERBEDA**, **18 item HILANG** (daftar §9).

---

## 1. Katalog Endpoint V2 → Status Paritas V3

### 1.1 Auth & sesi

| # | Method & Path (V2) | Fungsi (bahasa sehari-hari) | Akses V2 | Dipakai UI | Status V3 |
|---|---|---|---|---|---|
| 1 | `POST /api/auth/login` | Login username+password → token JWT. Punya pelacakan gagal-login per IP+username (`_cek_login_gagal`/`_catat_login_gagal`, anti brute-force). | Publik | login | **BERBEDA** — `app/routers/auth.py`. Rate-limit 5/menit ada, tapi **pelacakan gagal-login progresif HILANG**. Respons V2 menyertakan `username`+`role`. |
| 2 | `POST /api/auth/guest` | Login tamu → token. Otomatis **membuat baris DB `guest`** bila belum ada. | Publik | login tamu | **BERBEDA** — `auth.py`. V3 memakai guest **ephemeral** (id=0, tanpa baris DB), sehingga grant per-kamera untuk tamu tidak tersimpan seperti V2. |
| — | `POST /api/auth/refresh`, `/logout`, `GET /me` | — | — | — | Tambahan V3 (diizinkan: penambahan). |

### 1.2 Daftar kamera & reconnect

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 3 | `GET /api/streams` | Daftar kamera yang boleh ditonton user, **paginasi** (`page`, `limit` default 9, `group`, `no_check`), urut grup→nama. Status dari cache monitor (optimistis "online"). Tiap item: `webrtc_url`, `webrtc_url_sub` (hanya bila path sub terdaftar), `coordinates`, `has_poster`. | Login | **BERBEDA** — `streams.py`. Param `page/limit/group/no_check` dipulihkan, tapi **default limit 20 (bukan 9)**, tanpa param = list penuh (bukan paginasi), **tanpa `has_poster`**, koordinat kini `latitude/longitude` (bukan string `coordinates`), `webrtc_url_sub` selalu dihitung (bukan hanya bila terdaftar). |
| 4 | `POST /api/streams/{id}/reconnect` | Paksa reconnect: lepas path MediaMTX, daftar ulang, cek status langsung, refresh poster bila online. | Login + boleh_tonton | **ADA** — `streams.py`. |

### 1.3 Admin kamera

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 5 | `GET /api/admin/streams` | Daftar semua kamera versi admin (dengan detail RTSP). Super_admin: semua. Admin: hanya yang `boleh_tonton` + **masking RTSP** (`saring_rtsp`: kredensial dikosongkan + flag `dipasang_sendiri=false` bila bukan pasangannya). Status dari cache. | super_admin/admin (pemeriksa `verify_pengelola_kamera`) | **BERBEDA** — `admin_streams.py`. Masking ada, tapi **tanpa filter `boleh_tonton`** (semua admin lihat semua kamera) dan **tanpa flag `dipasang_sendiri`** di respons. |
| 6 | `POST /api/admin/streams` | Tambah kamera. Mencatat `owner_id` **dan** `created_by` = admin pembuat. Langsung cek status + daftar ke MediaMTX di background. | super_admin/admin | **BERBEDA** — `admin_streams.py`. `created_by` dicatat, tapi **`owner_id` TIDAK dicatat** (kolom tetap NULL) → dasar `boleh_ubah`/`dipasang_sendiri` pincang untuk kamera baru. |
| 7 | `PUT /api/admin/streams/{id}` | Ubah kamera. **Ditolak 403 bila bukan `boleh_ubah`** (admin tak bisa sunting kamera super_admin/pemberian). | super_admin/admin | **BERBEDA** — `admin_streams.py`. **Cek `boleh_ubah` HILANG**: admin mana pun bisa sunting kamera siapa pun. |
| 8 | `DELETE /api/admin/streams/{id}` | Hapus kamera + lepas path MediaMTX + bersihkan cache. 403 bila bukan `boleh_ubah`. | super_admin/admin | **BERBEDA** — `admin_streams.py`. **Cek `boleh_ubah` HILANG**. |

### 1.4 Admin pengguna

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 9 | `GET /api/admin/users` | Daftar akun. Otomatis buatkan akun `guest` bila belum ada. Admin biasa hanya lihat **dirinya + bawahannya** (`bawahan_saya`). Kolom: `parent_admin_id`, `dibuat_oleh`, `admin_group`, `show_ads`, `stream_ids`. | super_admin/admin (`verify_pengelola_pengguna`) | **BERBEDA** — `admin_users.py`. `admin_group` **HILANG** (arsitektur grup-user tak ada di V3); `stream_ids` tidak dikembalikan. |
| 10 | `PUT /api/admin/groups/{group_name}/ads` | Nyalakan/matikan iklan **untuk semua anggota satu grup user sekaligus** (`__tanpa_grup__` = yang tanpa grup, kecuali super_admin). | super_admin/admin | **HILANG (fungsi)** — `admin_ads.py` punya path yang sama tapi hanya menulis key mati `group:<nama>` yang tidak dibaca siapa pun. |
| 11 | `GET /api/admin/admins/{admin_id}/camera-grants` | Lihat kamera apa saja yang dipegang seorang admin + caranya (milik/pemberian). | super_admin | **ADA** — `admin_users.py`. |
| 12 | `POST /api/admin/admins/{admin_id}/camera-grants` | Beri/cabut kamera ke admin (grant `can_view`/`can_playback`/`can_manage` + `can_reshare`). | super_admin | **ADA** — `admin_users.py` (cek `can_reshare`: tidak ada di V3 → reshare HILANG, lihat §5). |
| 13 | `POST /api/admin/users/{user_id}/camera-access` | Tetapkan kamera untuk satu akun (user/guest), **live & rekaman terpisah**. Aturan ketat: hanya bawahan, hanya kamera yang `boleh_bagi`, hanya cabut pemberian sendiri (`granted_by`), tolak entri tanpa izin. Sinkron ke pivot lama. | super_admin/admin | **BERBEDA** — `admin_users.py`. Aturan `boleh_bagi`/`granted_by`/`dilewati_bukan_milik_anda` **disederhanakan HILANG**. |
| 14 | `GET /api/admin/users/{user_id}/camera-access` | Lihat status akses satu akun per kamera + flag `terkunci` (pemberian orang lain tampil tapi tak bisa diubah). Kamera difilter `boleh_bagi`. | super_admin/admin | **BERBEDA** — `admin_users.py`. Tanpa flag `terkunci`, tanpa filter `boleh_bagi`. |
| 15 | `PUT /api/admin/groups/{nama_grup}` | **Ganti nama grup user**: pindahkan seluruh anggota ke nama baru dalam satu transaksi. Hanya super_admin. | super_admin | **HILANG (fungsi)** — V3 punya `PUT /admin/groups/{nama_grup}` tapi itu **grup kamera** (`StreamGroup`), bukan grup user. Rename grup-user tidak ada. |
| 16 | `GET /api/admin/groups/{nama_grup}/camera-grants` | Grant kamera per grup user. | super_admin | **BERBEDA** — `admin_streams.py`. Ada path-nya, tapi untuk grup kamera. |
| 17 | `POST /api/admin/groups/{nama_grup}/camera-grants` | Set grant kamera per grup user. | super_admin | **BERBEDA** — sama, grup kamera. |
| 18 | `GET /api/admin/access-overview` | Ringkasan: jumlah user per role + grant per stream. | super_admin/admin | **ADA** — `admin_users.py`. |
| 19 | `GET /api/admin/streams/{id}/sharing` | Siapa saja berhak atas satu kamera: daftar calon (user/guest, bawahan saja utk admin) + `can_view`/`can_playback`/`granted_by`/`terkunci` + daftar admin + `boleh_pindah_pemilik`. | super_admin/admin | **BERBEDA** — `admin_streams.py`. V3 hanya kembalikan `{user_ids}` — **detail per-izin HILANG**. |
| 20 | `POST /api/admin/streams/{id}/sharing` | Tetapkan penerima per kamera (`can_view`/`can_playback` per orang, `granted_by`, aturan bawahan & `boleh_bagi`). | super_admin/admin | **BERBEDA** — `admin_streams.py`. V3 hanya terima `{user_ids}` → `can_view=True` semua; **pemisahan playback HILANG di endpoint ini**. |
| 21 | `POST /api/admin/streams/{id}/owner` | Pindahkan pemilik kamera. | super_admin | **ADA** — `admin_streams.py`. |
| 22 | `POST /api/admin/users/{user_id}/access` | Petakan akses user → daftar kamera (tulis `StreamPermission` + `granted_by`, cek `boleh_bagi`). | super_admin/admin | **BERBEDA** — `admin_users.py`. Penyederhanaan; cek `boleh_bagi` tidak ada. |
| 23 | `POST /api/admin/users` | Buat akun. Aturan: **tolak akun guest kedua** (`tolak_guest_baru`), admin tak bisa buat super_admin, admin tanpa grup tak bisa buat admin, `parent_admin_id` & `admin_group` otomatis ikut pembuat. | super_admin/admin | **BERBEDA** — `admin_users.py`. **`tolak_guest_baru` HILANG**, `admin_group` HILANG. |
| 24 | `PUT /api/admin/users/{user_id}` | Ubah akun (username, role, password, `parent_admin_id` & `admin_group` hanya super_admin, `show_ads` per user). Aturan bawahan. | super_admin/admin | **BERBEDA** — `admin_users.py`. Tanpa `admin_group`, tanpa `tolak_guest_baru`. |
| 25 | `DELETE /api/admin/users/{user_id}` | Hapus akun (bukan super_admin lain, bukan diri sendiri). | super_admin/admin | **ADA** — `admin_users.py` (aturan bawahan ada). |

### 1.5 Scanner & disk

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 26 | `POST /api/admin/scan` | **Scan CIDR** (maks 256 host, 50 worker, timeout 0.2 dtk): untuk tiap host yang port-nya terbuka, rakit `rtsp://user:pass@ip:port/codec`. Hasil nyata saja (tanpa karangan). | super_admin (`verify_admin_role`) | **BERBEDA** — `admin_streams.py` `/admin/scan` kini resolver satu host. Fungsi CIDR dipulihkan di **`POST /api/admin/scan-subnet`** (`admin_scan.py`) — ADA di sana. |
| 27 | `POST /api/admin/scan/preview` | Preview hasil scan: daftarkan path sementara `scan_preview_{hash}` ke MediaMTX → kembalikan `webrtc_url` asli. | super_admin | **BERBEDA** — `admin_streams.py`. Path ada tapi **tidak mendaftarkan ke MediaMTX** (TODO) → preview tidak benar-benar jalan. |
| 28 | `GET /api/admin/disks` | Daftar **semua disk ter-mount** (`df`, >1GB): mount, size, avail, fstype, usage_pct. | super_admin | **BERBEDA** — `admin_streams.py`. V3 kembalikan **satu objek** (bukan list) + entri Drive opsional. |

### 1.6 Rekaman & playback

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 29 | `GET /api/recordings/cameras` | Kamera yang rekamannya aktif + `record_path` (disembunyikan untuk API key) + `has_recordings`. Disaring `boleh_playback`. | login/kunci | **BERBEDA** — `recordings.py`. Tanpa `record_path`/`has_recordings`. |
| 30 | `GET /api/recordings/{id}/dates` | Daftar tanggal + `segment_count`, urut terbaru. | login/kunci (playback) | **BERBEDA** — `recordings.py`. V3: `{dates:[...]}` **tanpa jumlah segmen**. |
| 31 | `GET /api/recordings/{id}/segments` | Segmen satu tanggal (`?date=` wajib): `{stream_id, date, mediamtx_segments:[], disk_segments:[{url: /file?rel=...}]}`. | login/kunci (playback) | **BERBEDA** — `recordings.py`. `?date=` opsional + `?hour=` (tambahan OK), tapi bentuk respons **berubah total** (list `SegmentOut`, bukan `{disk_segments}`). |
| 32 | `GET /api/recordings/{id}/file` | Sajikan satu file segmen (`?rel=`), dengan **proteksi path traversal** (realpath harus di dalam dir kamera). | login/kunci (playback) | **ADA** — `recordings.py`. |
| 33 | `GET /api/recordings/{id}/timeline` | Rentang rekaman kontinu (segmen MediaMTX digabung bila gap ≤5 dtk) + `?segments=` untuk daftar mentah. | login/kunci (playback) | **BERBEDA** — `recordings.py`. Bentuk respons berbeda (`ranges` ada, tapi struktur tidak sama persis). |
| 34 | `GET /api/recordings/{id}/next-playable` | Cari titik putar berikutnya. | login/kunci (playback) | **ADA** — `recordings.py`. |
| 35 | `GET /api/recordings/{id}/stream` | Proxy fMP4 MediaMTX (`?token=`/`?key=`+`?pass=`, karena `<video>` tak bisa kirim header). Cek `include_playback` untuk kunci. | login/kunci | **ADA** — `recordings.py`. |
| 36 | `GET /api/recordings/{id}/playback-url` | URL HLS playback (internal + publik via proxy). | login/kunci (playback) | **ADA** — `recordings.py`. |

### 1.7 Iklan

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 37 | `GET /api/ad-config` | Konfigurasi banner (16 field). **Nonaktif otomatis** bila user login `show_ads=False` (super_admin dikecualikan). | publik/login/kunci | **ADA** — `admin_ads.py` (+ `?token=`). |
| 38 | `POST /api/admin/ad-config` | Simpan konfigurasi iklan. | super_admin | **ADA** — `admin_ads.py`. |
| 39 | `POST /api/admin/ad-config/upload-image` | Upload logo sponsor (sanitasi nama, whitelist ekstensi tanpa html/svg, maks 5MB, prefix timestamp). | super_admin | **ADA** — `admin_ads.py` (disimpan ke `data/uploads/ads`, URL `/uploads/ads/...`; V2: `static/ads`, URL `/api/static/ads/...` — beda path, fungsi sama). |

### 1.8 External / embed (kontrak FROZEN)

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 40 | `GET /api/external/cameras` | Daftar kamera milik satu kunci API (nama dibersihkan dari IP, `is_primary`, `has_recording`, `include_playback`). Dipakai pemilih kamera embed.php. | kunci API (?key=&?pass=) | **ADA** — `external.py` (+ `?camera=`). |
| 41 | `GET /api/external/playback` | Playback via kunci: `?camera=` = **nomor urut** (1=utama, id asli juga diterima) + `?date=`. Tanpa date → daftar tanggal; dengan date → segmen + URL putar + `ranges` MediaMTX. Hormati `include_playback`. | kunci API | **BERBEDA** — `external.py`. Bug 503 diperbaiki; nomor-urut kamera & `custom_camera_name` perlu verifikasi lanjutan. |
| 42 | `GET /api/external/stream` | Sesi embed satu kamera: `{stream:{id,name,webrtc_url,webrtc_url_sub,coordinates,embed_timeout_seconds,click_to_play}, ad:{...}}` + tulis access log (hit/denied). | kunci API | **ADA** — `external.py` (field V2 dipulihkan aditif + `url`/`expires_at` V3). |

### 1.9 Log & API key

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 43 | `GET /api/admin/api-access-logs` | Log akses (`?key_id=`, `?status=hit\|denied`, `?limit=`, `?offset=`). | super_admin | **ADA** — `admin_keys.py` (+ `?status=`/`?offset=` dipulihkan). |
| 44 | `GET /api/admin/api-access-logs/summary` | Statistik: total/hit/denied/IP unik. | super_admin | **ADA** — `admin_keys.py`. |
| 45 | `DELETE /api/admin/api-access-logs` | Hapus log (`?days=N` opsional; kosong = semua). | super_admin | **ADA** — `admin_keys.py`. |
| 46 | `GET /api/admin/api-keys` | Daftar kunci. **Hanya super_admin** (`tolak_bukan_super`). Kembalikan `key_value` plaintext + `has_secret_pass` (flag, bukan hash). | super_admin | **BERBEDA** — `admin_keys.py`. V3 simpan `key_hash` SHA-256: **key plaintext hanya tampil sekali saat create** (tidak bisa ditampilkan ulang di GET — perubahan perilaku "salin kunci", disengaja demi keamanan). |
| 47 | `POST /api/admin/api-keys` | Buat kunci + `owner_id`, `camera_id` utama + daftar kamera, `secret_pass` **bcrypt** (plaintext dikembalikan **sekali**), `allowed_domain`, `embed_timeout_seconds`, `click_to_play`, `include_playback`, `custom_camera_name`. Hanya untuk kamera yang `boleh_bagi`. | super_admin | **BERBEDA** — `admin_keys.py`. Password kunci **ADA** (`password`→`password_hash`, diverifikasi di `external.py:_validate_key`); raw key dikembalikan sekali saat create (`out["key"]`). Yang berubah: V2 menyimpan `key_value` plaintext (bisa ditampilkan ulang di GET), V3 menyimpan hash (tampil sekali saja). `owner_id` tidak dicatat di V3. |
| 48 | `PUT /api/admin/api-keys/{id}` | Ubah kunci (password hanya tertimpa bila diisi; hash tak pernah bocor). Bukan pemilik → 403. | super_admin | **ADA** — `admin_keys.py` (password opsional, `password_hash`). |
| 49 | `DELETE /api/admin/api-keys/{id}` | Cabut kunci. Bukan pemilik → 403. | super_admin | **ADA** — `admin_keys.py`. |

### 1.10 Poster & health & landing

| # | Method & Path (V2) | Fungsi | Akses V2 | Status V3 |
|---|---|---|---|---|
| 50 | `GET /api/posters/stream_{id}.jpg` | Thumbnail kamera. Request dari daftar ikut memicu capture bila perlu. | login | **ADA** — `system.py` (+ `?token=` untuk `<img>`). |
| 51 | `GET /api/health` | Status API + komponen. | publik | **ADA** — `system.py` (bentuk respons berbeda: `status: degraded` dsb — wajar). |
| 52 | `GET /` | Halaman landing HTML sederhana. | publik | **HILANG** — tidak ada di V3. |

---

## 2. Background Job

| Job V2 (main.py) | Jadwal / Pemicu | Input → Output / Efek | Status V3 |
|---|---|---|---|
| `background_status_monitor` | Tiap `RTSP_CACHE_TTL_SECONDS` | Cek RTSP semua kamera aktif (thread pool) → `RTSP_STATUS_CACHE`; **resync path MediaMTX yang hilang**; **bersihkan path sampah tiap 5 siklus**; trigger poster bila kamera baru online | **BERBEDA** — `app/main.py` (`_status_broadcaster` + poller di `services/`). **Resync & cleanup path sampah HILANG** (kamera bisa berhenti merekam diam-diam setelah MediaMTX restart). |
| `background_frame_capturer` | Tiap `POSTER_CAPTURE_INTERVAL_SECONDS`, hanya kamera online, semaphore + jeda 0.75 dtk | Capture frame via MediaMTX/ffmpeg → `posters/stream_{id}.jpg` | **ADA** — `_poster_loop` |
| `cleanup_blank_posters_background` | Sekali saat startup (+8 dtk) | Hapus poster yang kosong/blank | **HILANG** — tidak ada di V3 |
| `request_poster_capture` (on-demand) | Saat daftar/poster diminta (cooldown 45 dtk) | Capture satu frame bila belum ada | **HILANG** — tidak ada di V3 |
| Perekam segmen | — | **V2 merekam via MediaMTX** (path `record_enabled`, bukan worker Python) | **BERBEDA** — V3 punya pipeline rekaman sendiri (`services/recording.py`) + `RETENTION_ENABLED`/`_retention_loop` (pembersih retensi — **baru di V3**, di V2 retensi diatur per-path MediaMTX) |
| Mirror Drive (fieriindra) | Tiap 30 dtk, file stabil (>20 dtk) | Salin ke mount rclone | **ADA** — `services/drive_mirror.py` (tambahan V3, bukan dari V2 ini) |
| Uploader Drive OAuth | — | — | Tambahan V3 (`services/drive.py`) |

## 3. Integrasi MediaMTX

| Fungsi V2 | Status V3 (`services/mediamtx.py`) |
|---|---|
| `register_stream_in_mediamtx` / `register_single_mediamtx_path` (daftar path + sub) | **ADA** — `create_path` |
| `delete_single_mediamtx_path` | **ADA** — `delete_path` |
| `restart_mediamtx_path` (soft reconnect) | **HILANG** — tidak ada padanan |
| `persist_mediamtx_path` (simpan konfigurasi path: record_enabled, retensi, disk, grup) | **HILANG** — V3 tidak persist konfigurasi path ke MediaMTX |
| `resync_missing_mediamtx_paths` (pulihkan path hilang setelah restart) | **HILANG** |
| `cleanup_stale_mediamtx_paths` (bersihkan path sampah) | **HILANG** |
| `REGISTERED_PATHS` (cache path terdaftar) | **BERBEDA** — V3 query `get_paths()` langsung, tanpa cache lokal |
| Playback API MediaMTX (`/get?path=&start=&duration=`, HLS `/playback/index.m3u8`) | **ADA** — `recordings.py` |

## 4. Resolver Sub-stream

V2 `get_substream_url()` (main.py:107): 4 pola substitusi string — `_main`→`_sub`,
`/stream1`→`/stream2`, `/h264`→`/h264_sub`, `/h.264`→`/H.264_sub`.
**Status V3: ADA (superset)** — `services/stream_resolver.py` + `services/brands.py`:
ONVIF-first → 12 template brand (hikvision, dahua, uniview_ipc/nvr, hanwha, axis,
tplink_vigi, reolink, ezviz, foscam, milesight, panasonic) → fallback pola generik.
Per-kamera tersimpan eksplisit: `brand`, `main_url`, `sub_url`, `onvif_profile`.

## 5. Sistem Iklan

- Skema 16 field (`AdConfigSchema`) — **ADA** penuh di V3 (`admin_ads.py`).
- `show_ads` per user — **ADA** (`users.show_ads`, migrasi 0005).
- Toggle iklan **per grup user** (`PUT /admin/groups/{group}/ads`) — **HILANG (fungsi)** (lihat #10).
- Upload logo (sanitasi, 5MB) — **ADA**.
- `embed_timeout_seconds` / `click_to_play` — **ADA** di skema & `/external/stream`; **UI-nya** ada di halaman API Key V3 ("Pengaturan Embed Player").
- Penayangan banner di popup live & halaman embed — **ADA** di V3 (`AdBanner.tsx`, FocusModal, embed).

## 6. API Key — Fitur Detail

| Fitur V2 | Status V3 |
|---|---|
| Nilai kunci acak aman | **ADA** — `secrets.token_urlsafe(32)`, raw dikembalikan **sekali** saat create |
| `secret_pass`/password kunci (bcrypt, dicek tiap pakai) | **ADA** — `ApiKey.password_hash`, diverifikasi di `external.py:_validate_key` |
| `allowed_domain` + `_enforce_key_domain`/`_domain_cocok` (boleh subdomain) | **ADA** — `external.py` (`domain_lock`, `_domain_match`) |
| `include_playback` (kunci tanpa playback → 403 di endpoint rekaman) | **ADA** |
| `custom_camera_name` (nama samaran kamera utama) | **ADA** |
| Multi-kamera per kunci (`api_key_streams`, `_key_camera_ids`, `_sync_key_cameras`) + **urutan** | **ADA** (kolom `position` ada; pengurutan masih pakai `id` — perlu verifikasi) |
| Nomor urut kamera di external (`?camera=1..N`, id asli juga diterima) | **ADA** (perlu verifikasi `custom_camera_name` dipakai di label) |
| Sesi embed: JWT `?session=` + `embed_timeout_seconds` + countdown | **ADA** — `external.py` |
| Access log: tulis tiap hit/denied (non-blocking) + **auto-prune 5/IP** | **BERBEDA** — tulis log ADA; **auto-prune HILANG** (log tumbuh tanpa batas) |
| Error selalu **403** (jangan bocorkan mana yang salah) | **ADA** — `external.py` |

## 7. Sistem User, Peran & Grant

| Konsep V2 | Status V3 |
|---|---|
| 4 peran: `super_admin` (kuasa penuh), `admin` (terbatas wilayah), `user`, `guest` (satu akun `guest` sungguhan) | **BERBEDA** — peran ADA (`core/rbac.py`), tapi guest **ephemeral** (bukan baris DB) dan **`tolak_guest_baru` HILANG** |
| `KUASA_PENUH = ("super_admin",)` | **ADA** — `is_super_admin` |
| `boleh_tonton` vs `boleh_playback` (terpisah) | **ADA** — `_check_camera_access(need_playback=)` |
| `boleh_ubah` (sunting/hapus hanya kamera sendiri) | **BERBEDA** — fungsi `mask_rtsp_url` ADA, tapi **penegakan di PUT/DELETE streams HILANG** |
| `boleh_bagi` / `can_reshare` (teruskan akses ke bawahan) | **HILANG** — tidak ada konsep reshare di V3 |
| `boleh_lihat_rtsp` / `saring_rtsp` (masking kredensial) | **ADA** — `mask_rtsp_url` di `GET /admin/streams` |
| `boleh_kelola_izin` (hanya cabut pemberian sendiri) | **HILANG** |
| `bawahan_saya` (admin_group + bukan sesama admin) | **BERBEDA** — V3: `can_manage_user` pakai `parent_admin_id` saja; **`admin_group` HILANG** |
| `parent_admin_id` (pencatat pembuat) + `dibuat_oleh` | **ADA** |
| `StreamPermission`: `user_id`/`role`, `can_view`, `can_playback`, `granted_by` | **ADA** (+ endpoint `role-access` untuk guest per kamera — tambahan V3) |
| `StreamAdminGrant`: `can_view`, `can_playback`, `can_manage`, `granted_by` | **BERBEDA** — `can_reshare` **HILANG** |
| Pivot lama `user.streams` (disinkron) | **HILANG** — V3 tidak punya relasi ini (disengaja; V2 sendiri menandainya legacy) |
| Rate-limit login/guest/refresh/scan | **ADA** (baru di V3, pola mirip) |
| Audit log mutasi `/api/admin/*` | Tambahan V3 (diizinkan) |

## 8. Penyimpanan & Skema Data

- V2: `record_enabled`, `record_path`, `record_disk`, `record_retention_days`, `group_name`, `coordinates` (string) per kamera.
  V3: `recording_enabled`, `retention_days`, `storage_mode` (local/drive/both), `drive_account_id`, `latitude/longitude` (float).
  **BERBEDA**: `record_path` & `record_disk` **HILANG** (V3: satu `recordings_dir` global + `stream_{id}/`); `coordinates` string → float (tanpa migrasi konversi otomatis).
- Drive: V2 ini **tidak punya** kode Drive (itu dari fork fieriindra). V3: OAuth multi-akun + folder-link/rclone — murni tambahan.

## 9. Daftar HILANG (wajib dipulihkan — Zero Deprecation)

1. `GET /` landing HTML (#52).
2. Fungsi toggle iklan per grup user (#10) — path ada, implementasi mati.
3. Rename grup user (#15) — path dipakai untuk grup kamera.
4. `boleh_bagi`/`can_reshare`: teruskan akses kamera ke bawahan (#12, §7).
5. `boleh_kelola_izin`: admin hanya cabut pemberiannya sendiri (§7).
6. `tolak_guest_baru`: cegah akun guest kedua (#23).
7. Penegakan `boleh_ubah` di PUT/DELETE `/api/admin/streams` (#7, #8).
8. Filter `boleh_tonton` di `GET /api/admin/streams` untuk admin non-super (#5).
9. `admin_group` (grup user sebagai batas wilayah admin) (#9, #24, §7).
10. `owner_id` dicatat saat kamera dibuat (#6).
11. `cleanup_blank_posters_background` + `request_poster_capture` on-demand (§2).
12. `restart_mediamtx_path`, `persist_mediamtx_path`, `resync_missing_mediamtx_paths`, `cleanup_stale_mediamtx_paths` (§3).
13. Preview scan sungguhan via MediaMTX (#27).
14. Auto-prune access log 5/IP (§6).
15. Pelacakan gagal-login progresif (#1).
16. `record_path`/`record_disk` per kamera (§8).
17. Detail respons sharing per-izin (`can_view`/`can_playback`/`granted_by`/`terkunci`) (#19, #20).
18. Aturan ketat `camera-access` (boleh_bagi, granted_by, dilewati) (#13, #14, #22).

## 10. Daftar BERBEDA (perilaku/kontrak berubah — perlu keputusan)

- Paginasi `/api/streams`: default limit 9→20; tanpa param = list penuh.
- Respons `segments`/`dates`/`timeline` rekaman: bentuk berubah (klien lama pecah).
- `/api/admin/disks`: list → objek tunggal.
- `StreamOut` tanpa `coordinates` string & `has_poster`; koordinat jadi float.
- API key: plaintext sekali-tampil → hash permanen (salin-ulang tak mungkin).
- Upload iklan: path `/api/static/ads/` → `/uploads/ads/`.
- Guest: baris DB → ephemeral.
- Pivot `user.streams` dihapus (V2 sendiri menyebutnya legacy — dapat diterima).
