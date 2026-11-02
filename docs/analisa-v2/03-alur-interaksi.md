# 03 — Alur & Interaksi Pengguna: v2.0 (Mamura Stream) → v3.0 (NetraVision)

> Analisa READ-ONLY oleh 4 subagent paralel, 2026-11-02. Tidak ada file repo yang diubah.
> Sumber v2: `/tmp/v2-ref` (Mamura Stream v2.0). Pembanding v3: `~/workspace/netravision`.
> Aturan acuan: **Zero Deprecation** — semua yang ada di v2 wajib ada di v3; boleh tambah, dilarang kurang.

## 0. Ringkasan eksekutif

| Area | Alur diinventarisasi | ADA | BERBEDA | HILANG |
|---|---|---|---|---|
| 1. Login, logout, guard, router | 9 | 4 | 4 | 1 |
| 2. Embed | 8 | 2 | 6 | 0* |
| 3. Live | 13 | 4 | 5 | 4 |
| 4. Playback | 11 | 1 | 5 | 5 |
| 5. Peta | 12 | 2 | 2 | 8 |
| 6. Monitor kustom | 10 | 3 | 4 | 3 |
| 7. Realtime & polling | 7 | 1 | 3 | 3 |
| 8. Notifikasi & konfirmasi | 8 | 1 | 5 | 2 |
| 9. Fullscreen & mode tampilan | 3 | 0 | 1 | 2 |
| 10. Berbagi kamera & akses | 5 | 0 | 4 | 1 |
| 11. Modal admin | 13 | 3 | 7 | 3 |
| 12. Keyboard shortcut | 6 | 1 | 1 | 4 |
| **TOTAL** | **~105** | **22** | **47** | **36** |

\* Embed: tidak ada yang hilang total, tapi 6 BERBEDA memuat sub-fitur yang hilang (parameter `pass`, teks timeout spesifik, pesan error spesifik).

**Kesenjangan terbesar (dampak UX nyata):**
1. **Sistem toast global hilang** — v3 tidak punya `showToast`; sukses ditandai tutup modal diam-diam.
2. **Auto-reconnect WebRTC hilang** — v3 sekali gagal langsung "Gagal memuat", tanpa retry 4× + force-reconnect diam-diam ala v2.
3. **Playback berubah total** — timeline kontinu + scrub + auto-lanjut/skip-gap otomatis v2 menjadi klik segmen diskrit di v3.
4. **Peta: clustering, klik→langsung-live, bottom-sheet mobile hilang.**
5. **Camera popup kaya fitur** (prev/next, quality toggle, tombol peta, bitrate, theater, orientasi) menjadi FocusModal sederhana.
6. **Pagination** hilang di Live & Monitor (risiko performa ratusan kamera).
7. **Izin granular Berbagi** (Lihat/Rekaman/Bagikan per akun) menjadi satu checkbox "boleh melihat".
8. **Shortcut keyboard** hampir semua hilang (hanya Esc di FocusModal yang tersisa).

---

## 1. Login, logout, guard, router

### 1.1 Redirect bila sudah login
1. v2 `frontend/login.php:16-18`: jika `localStorage["cctv_auth_token"]` ada → `window.location.href = "index.php"`.
2. v3 `apps/web/app/login/page.tsx:28-31`: `if (!loading && user) router.replace("/live")`.
3. **Status: ADA** (beda target: `/live` vs `index.php`, wajar karena struktur rute beda).

### 1.2 Theme toggle di halaman login
1. v2 `frontend/login.php:33-46,72-80`: tombol `toggleTheme()` pojok kanan atas, simpan `localStorage["theme"]`.
2. v3: tidak ada toggle di halaman login.
3. **Status: HILANG** (toggle tema ada di AppShell v3, tapi tidak di halaman login).

### 1.3 Form login kredensial
1. v2 `frontend/login.php:59-74`: satu form `#login-form` (TIDAK ada tab terpisah admin/user — peran dibedakan server-side), field `username` (required, placeholder "admin"), `password` (required, placeholder "••••••••"), tombol "Masuk".
2. Submit `login.php:99-123`: `POST ${API_URL}/auth/login` `{username, password}` → sukses: `simpanSesi()` simpan `access_token`, `role`, `username` → redirect `index.php`. Gagal → pesan `"Login gagal. Periksa kembali kredensial."` (`login.php:66,121`).
3. Tidak ada di v2: checkbox "ingat saya", field kode/OTP.
4. v3 `app/login/page.tsx:33-47` + `lib/auth.tsx:52-58`: form setara → `router.push("/live")`.
5. **Status: ADA**, dengan **BERBEDA**: v3 meneruskan pesan error server apa adanya (fallback `"Gagal masuk. Coba lagi."`, `page.tsx:41-45`) — tidak lagi memakai teks baku v2. Catatan keamanan: pesan server mentah di UI login berisiko enumerasi user.

### 1.4 Login tamu (tanpa kode)
1. v2 `frontend/login.php:76-90,125-143`: tombol "Masuk sebagai tamu" → `loginAsGuest()`: `POST ${API_URL}/auth/guest` **tanpa body** → sesi seperti login biasa. Error: `"Sesi tamu gagal dibuat. Hubungi administrator."` (`login.php:140`).
2. v3 `lib/auth.tsx:64-70` + `app/login/page.tsx:49-58`: tombol "Guest login" → `loginGuest("")` → `POST /auth/guest` body `{code:""}`.
3. **Status: ADA** (beda: v3 mengirim body `{code:""}`; v2 tanpa body).

### 1.5 Logout
1. v2 `frontend/logout.php:9-14`: proteksi anti-CSRF — cek header `Sec-Fetch-Site`; bukan `same-origin`/`same-site`/`none` → `403 "Forbidden."`.
2. v2 `logout.php:22-27`: JS hapus 3 key localStorage → redirect `login.php`. Fallback non-JS (`logout.php:30`): `"Logout... Jika tidak redirect otomatis, klik di sini."`. TIDAK ada panggilan API (token dibiarkan kedaluwarsa).
3. v3 `lib/auth.tsx:72-79`: `POST /auth/logout` (revokasi server-side) → `clearTokens()` → `router.push("/login")`.
4. **Status: BERBEDA** — v3 lebih kuat (revoke server-side + refresh-token rotation), tapi **HILANG**: proteksi `Sec-Fetch-Site` dan fallback teks non-JS.

### 1.6 Router & guard
1. v2 `assets/js/modules/router.js`: rute `index.php?page=<nama>` (`monitor`, `custom`, `maps`, `admin`, `playback`); alias `viewer`→`monitor`; page tak dikenal → `monitor` (fallback, bukan 404). Guard: tanpa token → `handleLogout()`. Guard menu admin: `bolehKelola()` = `super_admin`/`admin`.
2. v3: rute Next.js (`/live`, `/playback`, `/maps`, `/admin/...`, `/monitors`, `/embed`, `/login`); guard via `AuthProvider` + `AdminGuard`; 401 → coba refresh token dulu (`lib/api.ts`).
3. **Status: BERBEDA** (setara fungsi, implementasi modern). Guard admin: **ADA** — `isAdminRole()` (`lib/auth.tsx`) + `AdminGuard` redirect `/live`, setara `bolehKelola()` v2.

---

## 2. Embed (`frontend/embed.php` → `app/embed/page.tsx`)

### 2.1 Parameter URL
1. v2 `embed.php:337-340`: membaca `key`, `pass`, `camera`. TIDAK ada `?session=` di v2.
2. v3 `app/embed/page.tsx:232-234`: hanya `key` dan `camera`.
3. **Status: BERBEDA** — **`pass` HILANG** di v3 (tidak diteruskan ke `/external/stream`). Regresi potensial bagi konsumen embed berkunci password.

### 2.2 Validasi key
1. v2: `key` kosong → error `"Akses Ditolak"` / `"Parameter API Key (key) wajib disertakan untuk mengakses stream."` (`embed.php:342-345`). Satu request `GET /api/external/stream?key=...[&pass=...][&camera=...]`; non-OK → `"Gagal Memutar CCTV"` + detail server.
2. v3 dua tahap: (1) `GET /external/cameras?key=` — 404 → `"Kunci API tidak dikenal."`; key kosong → `"Tautan embed tidak valid"` / `"Parameter ?key= tidak ditemukan atau tidak dikenal."` (`page.tsx:272-292`). (2) sesi per kamera saat tombol play ditekan.
3. **Status: BERBEDA** — v3 memisahkan "key valid tapi kamera tak tersedia" (notice kuning, kamera lain tetap tampil); v2 gagal total.

### 2.3 Player & click-to-play
1. v2 `embed.php:375-411`: `data.stream.click_to_play` dari API (default true) → overlay play besar; false → autoplay. Poster `/api/posters/stream_<id>.jpg`; label `"<nama> - Live"`; loading `"Menghubungkan ke server stream..."` (`embed.php:163-166`).
2. v3: selalu tampilkan tombol play (klik untuk memutar); tombol stop; overlay nama; poster; loading state.
3. **Status: ADA (sebagian) / BERBEDA** — v3 **mengabaikan flag `click_to_play`** (tidak ada mode autoplay) dan tidak membaca `embed_timeout_seconds` dari API (memakai `expires_at` sesi).

### 2.4 Countdown / auto-stop / keep-alive
1. v2 `embed.php:232-266`: `embedTimeoutSeconds` default 300 dari API. Toast keep-alive 15 detik sebelum habis: `"Pemutaran akan dihentikan dalam <N> detik."` + tombol `"Lanjutkan Menonton"` → `extendPlaytime()` **reset timer lokal tanpa request sesi baru**. Setelah habis: overlay `"Waktu pemutaran habis. Klik untuk memutar kembali."` (`embed.php:285-288`). `embedTimeoutSeconds = 0` = tanpa batas.
2. v3 `page.tsx:38-129,195-210`: countdown dari `expires_at` sesi (tick 1 detik); toast bila sisa < 90 detik: `"Sesi berakhir dalam M:SS"` + tombol `"Perpanjang"` (**mengambil sesi baru dari server**); habis: `"Sesi berakhir — tekan Perpanjang untuk lanjut."`.
3. **Status: BERBEDA** — ambang 90 dtk vs 15 dtk; "Perpanjang" v3 = sesi baru (lebih benar); **HILANG**: teks `"Waktu pemutaran habis. Klik untuk memutar kembali."`.

### 2.5 Tombol Stop — **ADA**
v2 `embed.php:212-223` "Stop Feed" → tutup RTCPeerConnection, reset overlay. v3 `page.tsx:58-64,225-235` tombol "Stop", perilaku identik.

### 2.6 Overlay iklan — **ADA**
v2 `embed.php:226-248,414-510`: banner bawah (gambar + marquee, 16 field AdConfig). v3 `{ad?.is_active && <AdBanner config={ad} />}` (`page.tsx:147`) dari `GET /ad-config` publik.

### 2.7 Pesan error embed (inventaris verbatim v2)
| Kondisi | Judul | Pesan |
|---|---|---|
| `?key=` tidak ada | `Akses Ditolak` | `Parameter API Key (key) wajib disertakan untuk mengakses stream.` |
| API non-OK | `Gagal Memutar CCTV` | `<detail server>` / `HTTP <status>` |
| Tanpa `webrtc_url` | `Gagal Memutar CCTV` | `Respons API tidak memuat URL WebRTC.` |
| ICE failed | `Koneksi Gagal` | `Koneksi WebRTC ke media server terputus.` |
| WHEP handshake gagal | `Gagal Handshake WHEP` | `Media server tidak merespons koneksi stream.` |
| Timeout (overlay) | — | `Waktu pemutaran habis. Klik untuk memutar kembali.` |
| Keep-alive toast | — | `Pemutaran akan dihentikan dalam <N> detik.` + `Lanjutkan Menonton` |
| Loading | — | `Menghubungkan ke server stream...` |
| Default HTML | `Akses Ditolak` | `Kunci API tidak valid atau tidak memiliki akses ke kamera ini.` |

**Status: BERBEDA** — v3 memakai pesan generik + pesan server (`"Tautan embed tidak valid"`, `"Kunci API tidak dikenal."`, `"Coba lagi"`, `"Sesi berakhir — tekan Perpanjang untuk lanjut."`); pesan spesifik ICE/handshake **HILANG**; tidak ada pola judul+pesan `showError(title, msg)`.

### 2.8 Kamera offline di embed
v2: tanpa penanganan eksplisit (andalkan error WHEP). v3: tombol play disabled + `"Kamera offline"` + dot merah (`page.tsx:215-219`). **Status: v3 LEBIH LENGKAP.**

---

## 3. Live (`views/live-monitor.php` → `app/live/page.tsx`)

### 3.1 Pemilih grid 1x1/2x2/3x3/4x4 — **ADA**
v2 `live-monitor.php:39-44`, `webrtc.js:424-463`; default 3x3. v3 segmented control pill; default 4. Ganti layout → reset pagination (v2).

### 3.2 Filter grup — **HILANG**
v2 `live-monitor.php:24-38` (`viewer-group-filter`, `webrtc.js:419-422`). v3: diganti search teks + filter status Semua/Online/Offline (tidak setara 1:1).

### 3.3 Pagination — **HILANG**
v2 `includes/pagination-bar.php` (`live-monitor.php:54-56`); kapasitas = `layout²` (`webrtc.js:1288`); tombol first/prev/nomor/next/last. v3 memuat semua kamera sekaligus (risiko performa ratusan kamera).

### 3.4 Tile: badge nama/status/rec — **BERBEDA**
v2: badge nama, status Live/Offline, indikator rec (`webrtc.js:~1340`). v3: dot status + nama + chip LIVE; **indikator rec HILANG**.

### 3.5 Poster skeleton + fallback chain — **BERBEDA**
v2 `webrtc.js:749-765`: skeleton + kandidat poster berlapis + `onerror` handler. v3: spinner "Menghubungkan…" / `poster_url` tunggal, tanpa fallback berlapis.

### 3.6 Error overlay + "Coba Hubungkan Paksa" — **HILANG**
v2 `webrtc.js:766-783,485`: overlay `"Gagal Konek ke RTSP"` + detail `"RTSP / WebRTC gagal"` + tombol → `POST /streams/{id}/reconnect`. v3: state statis "Offline"/"Gagal memuat", tanpa tombol reconnect.

### 3.7 Telemetry overlay (fps/res/codec) — **HILANG**
v2 `webrtc.js:1100-1175,1187-1267`: tap-toggle overlay chip fps/res/codec + tombol "Buka Kamera", auto-hide 2-3 dtk. v3 overlay: nama + fullscreen + expand saja.

### 3.8 Klik tile → popup — **ADA (beda)**
v2: double-click → popup (`webrtc.js:1129-1135`); tombol expand → popup. v3: tap-toggle overlay, tombol expand → `FocusModal`. Double-click tidak ada.

### 3.9 Camera popup kaya fitur — **BERBEDA** (banyak HILANG)
v2 `webrtc.js:1944+`: Prev/Next sequence, play/pause, **quality toggle sub/main**, volume/audio, **theater mode**, **orientation button**, **tombol peta**, fullscreen, loading bar, ad overlay, rec dot, bitrate readout, metadata bar.
v3 `FocusModal`: **HILANG** prev/next, quality toggle (selalu main), theater, orientation, tombol peta, bitrate, rec dot. **BARU**: tombol Snapshot, AdBanner lower-third, tutup via ESC/backdrop.

### 3.10 Cache-first saat refetch — **BERBEDA**
v2 `webrtc.js:394-398,1284-1286`: grid lama tetap tampil (opacity-25→100), tidak dikosongkan. v3: `SkeletonGrid` 8 tile (lebih rapi, tapi bukan cache-first).

### 3.11 Empty state role-aware — **BERBEDA**
v2 `live-monitor.php:58-67`, `webrtc.js:340-352`: admin → `"Belum ada kamera yang terdaftar. Tambahkan kamera melalui menu Admin Console."`; non-admin → `"Belum ada kamera yang di-assign ke akun Anda. Hubungi administrator…"`. v3: pesan statis (`"Tambahkan kamera lewat halaman Admin"`); varian role **HILANG**.

### 3.12 Error halaman — **ADA**
v2: `showApiErrorBanner("Gagal memuat data kamera: …")` + fallback empty `"Error: {msg}"`. v3: card error + tombol "Coba lagi".

### 3.13 Perbedaan mobile vs desktop (v2)
- Grid collapse: semua layout → `grid-cols-1` di mobile; 2x2→`sm:2`; 3x3→`sm:2 lg:3`; 4x4→`sm:2 md:3 lg:4` (`webrtc.js:445-459`).
- Tile: desktop = double-click buka popup; mobile/touch = single tap toggle overlay + ghost-click prevention (tap <300ms & gerak <10px, `webrtc.js:1147-1167`).
- Fullscreen per tile TIDAK ada di v2 (hanya di popup & custom-monitor). v3 justru menambah fullscreen per tile (BARU).
- Control bar wrap di layar kecil.

---

## 4. Playback (`views/playback.php` → `app/playback/page.tsx`)

### 4.1 Grid kartu kamera + badge — **BERBEDA**
v2: kartu per kamera (poster, badge hijau `"ADA REKAMAN"` / abu `"KOSONG"`), hover ikon play, klik → modal. v3: dropdown select (single) / chip toggle (multi), auto-pilih pertama. **Badge status rekaman & poster HILANG.**

### 4.2 Filter grup — **HILANG** (v2 `pb-group-filter`).

### 4.3 Pemilih grid — **BERBEDA**
v2 `setPlaybackGrid`: grid 2x2/3x3/4x4 untuk **daftar kamera** (bukan playback simultan — v2 selalu satu kamera per modal). v3: grid picker hanya untuk mode **multi-kamera BARU**.

### 4.4 Modal playback — **BERBEDA/HILANG**
v2: modal diportal ke body, metadata bar (nama | grup), video 16:9 native controls, overlay `"Memuat rekaman..."`, tutup via × / backdrop / **Esc**. v3: inline di halaman (tanpa modal, tanpa Esc). **Mode multi-kamera BARU di v3** (toggle, grid 2×2/3×3/4×4, panel mandiri).

### 4.5 Pemilih tanggal — **BERBEDA**
v2: dropdown berisi **tanggal yang benar-benar ada rekamannya** + jumlah segmen (`GET /recordings/{id}/dates`); info "N tanggal tersedia". v3: `<input type="date">` bebas (max hari ini); user harus menebak tanggal.

### 4.6 Timeline kontinu + scrub — **HILANG**
v2: bar hijau per range, tick per jam, **playhead merah**, jam digital; scrub via Pointer Events (tap+drag, mouse/sentuh/pena satu jalur, `setPointerCapture`); teks `"Klik timeline untuk melompat ke jam tertentu"`. v3: **segmen diskrit sebagai tombol** (`entries`), klik segmen → `playback-url?time=`; scrub bebas & playhead kontinu **HILANG**.

### 4.7 Transport kustom ±30s — **HILANG**
v2 `pbSeekRelative`, `pbTogglePlay`: tombol ← 30s / Play-Pause / 30s →. v3: native `<video controls>`.

### 4.8 Chunked 120 dtk + auto-skip gap — **HILANG**
v2: streaming chunked 120 dtk per request; `ended` → lanjut chunk berikut otomatis; lewati jeda kosong otomatis (`rangeBerikutnya`); lewati potongan rusak via `GET /recordings/{id}/next-playable` (dibatasi `MAKS_LOMPAT=40`). v3: satu segmen = satu video; tanpa kelanjutan otomatis lintas segmen/gap. (Pengalaman "nonton rekaman seharian" hilang.)

### 4.9 Generation guard — **HILANG** (tidak relevan, arsitektur beda).

### 4.10 Tombol unduh — **BARU di v3** (`GET /recordings/{id}/file?start&end` → .mp4). v2 tidak punya.

### 4.11 State halaman
| State | v2 | v3 | Status |
|---|---|---|---|
| Loading daftar | `"Memuat daftar kamera..."` | skeleton per panel | ADA |
| Empty | `"Belum ada kamera dengan rekaman tersimpan"` | `"Pilih minimal satu kamera…"` / `"Belum ada kamera."` | ADA |
| Error | `"Gagal memuat tanggal rekaman"` / `"Gagal memuat timeline"` / `"Rekaman pada jam ini kosong atau rusak"` / `"Tidak ada rekaman berisi setelah titik ini"` | error box + retry | ADA |

### 4.12 Mobile vs desktop (v2)
Timeline scrub Pointer Events (sentuh & mouse satu kode). Grid kartu 1 kolom di mobile, naik per breakpoint. Modal `.ms-video-popup` terpusat; tidak ada varian bottom-sheet khusus mobile.

---

## 5. Peta (`views/maps.php` → `app/maps/page.tsx`)

### 5.1 Sidebar daftar CCTV — **BERBEDA**
v2: dikelompokkan per grup (header grup + count); item: dot status (hijau pulse/merah), nama, koordinat. Loading `"Loading..."`; empty `"Kamera tidak ditemukan"`; nol terpetakan: `"TIDAK ADA KAMERA TERPETAKAN"` + `"Gunakan menu Admin Console untuk menambahkan koordinat GPS"`; error `"Gagal memuat data CCTV."`.
v3: dua card **"Belum dipetakan"** / **"Di peta"** (BARU, lebih baik); **header grup HILANG**.

### 5.2 Search — **BERBEDA**
v2 `filterMapCCTVList`: filter nama **+ group_name + coordinates**. v3: hanya nama.

### 5.3 Badge total — **HILANG** (v2 `map-total-badge`; v3 punya count per card).

### 5.4 Marker — **ADA** (v2 pin 34px hijau/merah ikon kamera; v3 dot 20px).

### 5.5 Clustering — **HILANG**
v2: cluster otomatis threshold 50px, re-cluster tiap `zoomend`, badge count merah bila >1.

### 5.6 Popup cluster + "Lihat Semua Live Feed" — **HILANG**
v2: daftar kamera dalam cluster + tombol `"👁️ View"` per kamera + `"Lihat Semua Live Feed"`. v3: popup sederhana (nama, brand, status) + `"Lihat live"` → FocusModal.

### 5.7 Klik marker tunggal → langsung popup live — **HILANG**
v2 langsung `openCameraPopup` (tanpa popup Leaflet perantara). v3: 2 langkah (popup Leaflet → "Lihat live").

### 5.8 Klik sidebar → langsung live + sequence 100m — **HILANG**
v2 `focusCamera`: highlight + scroll, `setView` zoom 16, buka popup marker, langsung `openCameraPopup` dengan sequence = kamera dalam radius 100m (Haversine `getNearbyCameras`); prev/next menelusuri kamera terdekat. v3: klik item → `flyTo` zoom 15 saja.

### 5.9 Bottom sheet draggable (mobile) — **HILANG**
v2 `maps-sheet.js` (<640px): drag handle (Pointer Events), snap 25%/45%/80%, keyboard ArrowUp/Down, `role="separator"` + aria-label. Desktop: tidak dipasang (sidebar kiri tetap). v3 mobile: layout kolom (peta atas, panel bawah); tanpa drag/snap.

### 5.10 scrollWheelZoom off di mobile — **HILANG** (v2 `<767px` dimatikan, `tap:true`; v3 default Leaflet).

### 5.11 Tile CARTO dark/light per tema — **HILANG** (v3 selalu OSM standar).

### 5.12 Modal peta per kamera + link Google Maps — **HILANG**
v2 `maps.js openMapModal`: peta zoom 16 + marker status + info (nama, grup, koordinat) + **tombol link Google Maps**; tanpa koordinat → `"No coordinates configured for this camera"`.

### 5.13 BARU di v3
- **Admin drag marker** → PUT posisi + tombol "Tengah peta" untuk kamera belum-dipetakan.
- Legenda overlay: **ADA** di keduanya.

---

## 6. Monitor kustom (`views/custom-monitor.php` → `app/monitors/page.tsx`)

### 6.1 View mode Kustom vs Per Grup — **BERBEDA**
v2 `admin.js:1876 toggleCustomViewMode`: "Kustom (Pilih Manual)" vs "Per Grup Kamera". v3: toggle "Grup" pada layout terbuka → seksi per grup dari kamera di layout (bukan pilih satu grup dari daftar).

### 6.2 Checkbox + reorder naik/turun — **ADA** (pindah tempat)
v2 `admin.js:1623 moveCustomItem` di sidebar playlist. v3 di form buat/ubah (tombol ↑/↓, terpilih dulu).

### 6.3 Save & Load Playlist — **BERBEDA**
v2: satu playlist aktif, simpan ke `localStorage["cctv_custom_playlist"]`. v3: **banyak layout bernama** (`localStorage["nv_monitors"]`); konsep playlist tunggal hilang.

### 6.4 Daftar grouping: klik langsung muat — **BERBEDA**
v2: klik baris → langsung muat + `alert("Grouping … berhasil dimuat!")` (`applySavedScreen`). v3: accordion collapsed-first (klik = expand) + MiniPreview 3 sel + tombol Buka/Ubah/Hapus (2 langkah).

### 6.5 Hapus grouping + confirm — **ADA** (v3 `window.confirm`; v2 `confirm()` `admin.js:2114`).

### 6.6 Filter grup dropdown — **HILANG** (v2 `admin.js:1863 filterCustomGroupFeeds`; tertutup sebagian oleh mode grup v3).

### 6.7 Grid 1x1–4x4 — **ADA** (kelas responsif mirip v2; pilihan tersimpan di localStorage di keduanya).

### 6.8 Pagination — **HILANG** (v2 `pagination-bar.php`, kapasitas grid², `admin.js:1755`; v3 tampilkan semua).

### 6.9 Fullscreen grid — **ADA** (v3 tombol toggle "Penuh"; **tombol melayang "Keluar Fullscreen" HILANG** — v2 `exit-web-fullscreen-btn`).

### 6.10 Empty state — **ADA** (v2 `"Playlist Empty — Centang minimal satu kamera di panel kiri untuk mulai monitoring."`; v3 `"Belum ada monitor tersimpan"` + CTA).

### 6.11 Format storage — **BERBEDA / TIDAK KOMPATIBEL**
v2: `cctv_custom_screens` = `{name, playlist[{id,enabled}], gridSize}`. v3: `nv_monitors` = `{id, name, streamIds[], cols}`. **Layout lama pengguna v2 tidak terbaca v3** (hilang saat migrasi).

---

## 7. Realtime & polling

### 7.1 Polling status kamera — **BERBEDA** (peningkatan)
v2 `webrtc.js:54`: `setInterval(pollStatus, 15000)` — HTTP `GET /admin/streams` (admin) / `GET /streams?limit=1000&no_check=true`; update dot sidebar + badge admin + counter (`webrtc.js:1-55`).
v3 `hooks/useCameraStatus.ts`: **WebSocket `/ws`** (snapshot + delta), heartbeat ping 25 dtk (baris 65), auto-reconnect backoff `min(1000·2^retry, 15000)` ms. `app/live/page.tsx:90-96` merge hasil WS; tanpa `setInterval`.

### 7.2 Loop statistik WebRTC 2 dtk — **HILANG**
v2 `webrtc.js:3668`: `setInterval(updateWebRTCStatsLoop, 2000)` → FPS/resolusi/codec per stream (`webrtc.js:3587-3666`).

### 7.3 Auto-reconnect WebRTC — **HILANG**
v2 `startNativeWebRTC`: `maxAttempts = 4`, `retryDelayMs = 400` (`webrtc.js:989-990,1034-1037`); gagal total → 1× auto force-reconnect diam-diam `POST /streams/{id}/reconnect` (flag `window.autoReconnects[streamId]`, "R19", `webrtc.js:1069-1095`); tetap gagal → overlay error.
v3 `lib/whep.ts playWhep`: **satu kali coba**, `throw` saat `!res.ok`; `CameraTile:50` / `FocusModal:52` hanya `setFailed(true)`.

### 7.4 Overlay error stream — **BERBEDA**
v2: `"Gagal Konek ke RTSP"` / `"RTSP / WebRTC gagal"` (tile, `webrtc.js:770-777`); popup: `"Gagal Konek ke RTSP: {nama}"` / `"WHEP WebRTC gagal"`. v3: `"Gagal memuat"` / `"Stream tidak dapat diputar"` / `"Offline"` / `"Kamera tidak terjangkau"` (tile); `"Gagal memutar stream utama"` / `"Coba tutup dan buka kembali"` (FocusModal). Istilah "RTSP" hilang dari UI.

### 7.5 Timeout ganti kualitas 10 dtk — **HILANG** (v2 `webrtc.js:2449,2458` + toast; v3 tanpa pemilih LQ/HQ).

### 7.6 Interval minor
- Jam digital `ui.js:3` (`setInterval` 1 dtk, Asia/Jakarta + " WIB") — **HILANG** di v3.
- Poster capture: delay 800 ms lalu `setInterval` 30 dtk (`webrtc.js:860,864`) — **HILANG** (v3 `<img>` statis).
- Scanner progress `setInterval` 150 ms (`webrtc.js:2845`) — di luar fokus halaman ini.
- Fetch timeout sidebar 30 dtk (`webrtc.js:285`).

---

## 8. Notifikasi, toast, konfirmasi

### 8.1 Toast global — **HILANG**
v2 `window.showToast(message, type="success")` (`core.js:190-228`): container `fixed top-5 left-1/2 z-[9999]`; **auto-dismiss 3,5 dtk** (fade-out 350 ms, animasi masuk 300 ms); error → merah, selain itu (termasuk `"info"`) → hijau emerald (inkonsistensi v2: info jatuh ke gaya success). Wrapper `showApiErrorBanner`/`showApiSuccessBanner` (`ui.js:83-90`).
v3: **tidak ada Toast** — feedback via `ErrorBox` inline (`ui.tsx:301`), teks status halaman, tutup modal diam-diam.

### 8.2 Inventaris teks toast/alert v2 (verbatim, pilihan penting)
- `✅ Konfigurasi default Embed Player berhasil disimpan!`
- `✅ Kunci API berhasil digenerate!` / `✅ Kunci API berhasil diperbarui!` / `🗑 Kunci API berhasil dicabut.`
- `Pilih minimal satu kamera dan isi nama klien!` (error)
- `Koneksi kualitas baru lambat atau gagal terhubung.` (error)
- `Gagal mengunci orientasi. Silakan aktifkan auto-rotate di HP Anda.` (info)
- `Browser Anda tidak mendukung penguncian rotasi layar.` (info)
- `Berhasil menambahkan ${n} kamera!${' (Gagal/Sudah ada: '+m+')' bila ada}`
- `Berhasil menghapus ${n} kamera!${' (Gagal: '+m+')' bila ada}`
- `Berhasil memperbarui koordinat untuk ${n} kamera. Gagal: ${m}.\nDetail Error Terakhir: ${lastError}`
- `Grouping "${name}" berhasil disimpan!` / `Grouping "${screen.name}" berhasil dimuat!`
- `Berhasil disalin ke clipboard!` / `Gagal menyalin. Silakan salin secara manual.`
- `Akses disimpan. ${dilewati} pemberian dari admin lain dibiarkan utuh.`
- `Hapus semua log akses API? Tindakan ini tidak dapat dibatalkan.` (confirm, `core.js:1090`)

### 8.3 Konfirmasi hapus (native confirm → ConfirmModal)
| Aksi v2 | Teks v2 | v3 | Status |
|---|---|---|---|
| Hapus 1 kamera (`admin.js:777`) | `Are you sure you want to permanently delete this camera stream config?` | `"Hapus kamera"` / `Hapus "{name}"? Path MediaMTX ikut dilepas.` (`streams/page.tsx:489`) | BERBEDA (lebih informatif, ID) |
| Hapus massal (`webrtc.js:3541`) | `Apakah Anda yakin ingin menghapus secara permanen ${n} kamera terpilih dari direktori?` | `"Hapus kamera terpilih"` / `Hapus {n} kamera terpilih?` (`:504`) | BERBEDA |
| Hapus user (`admin.js:1373`) | `Are you sure you want to delete this user account?` | `"Hapus pengguna"` / `Hapus akun "{username}"?` (`users/page.tsx:208`) | BERBEDA |
| Hapus semua log API | `Hapus semua log akses API? Tindakan ini tidak dapat dibatalkan.` | `"Hapus semua log"` / `Hapus seluruh catatan akses API? Tindakan ini tidak bisa dibatalkan.` | ADA |
| Revoke API key | tanpa konfirmasi | `"Hapus API key"` / `Hapus key "{name}"? Embed yang memakainya ikut mati.` | BERBEDA (v3 menambah konfirmasi — perbaikan) |
| Hapus grouping (`admin.js:2114`) | `Apakah Anda yakin ingin menghapus grouping "${name}"?` | `window.confirm` `Hapus monitor "${nama}"?` (`monitors/page.tsx:706`) | BERBEDA |
| Timpa grouping (`admin.js:2012`) | `Grouping dengan nama "${name}" sudah ada. Apakah Anda ingin menimpanya?` | — (v3 form edit, tanpa timpa) | HILANG |

Catatan: v2 sukses hapus 1 kamera = diam (hanya `console.error` bila gagal — **tidak ada pesan ke user**); v3 konsisten via ConfirmModal.

---

## 9. Fullscreen & mode tampilan

### 9.1 Fullscreen — **BERBEDA**
v2: fullscreen di **popup** (`#popup-fullscreen-btn`, title `Layar Penuh (F)`, `webrtc.js:1587,1742-1760`, fallback webkit); saat `fullscreenchange` **ad bar dipindah ke dalam elemen fullscreen** (`webrtc.js:1769-1776`, class `ms-popup-ad-bar--fs`); ikon berubah; auto-unlock orientasi saat keluar (`webrtc.js:1822`); tap-toggle kontrol auto-hide 3 dtk di touch (`webrtc.js:1794`); tutup popup → `exitFullscreen` (`webrtc.js:2718-2720`).
v3: fullscreen **per tile** (`CameraTile.tsx:127-150`, `aria-label="Layar penuh {nama}"`); **FocusModal tanpa fullscreen**; tanpa logika ad-in-fullscreen.

### 9.2 Theater mode — **HILANG** (v2 `webrtc.js:1696-1707`, tombol `Mode Teater (T)`).

### 9.3 Kunci orientasi — **HILANG** (v2 `webrtc.js:1711-1739`, `screen.orientation.lock()`; toast gagal verbatim di §8.2).

---

## 10. Berbagi kamera & akses

### 10.1 Modal berbagi per kamera — **BERBEDA**
v2 `modals.php:300` `#berbagi-modal` (tombol Berbagi di tabel): judul `"Camera Sharing"` + subtitle nama kamera; pencarian akun (`#berbagi-cari`, `"Cari akun…"`); daftar akun dengan **kolom checkbox Lihat / Rekaman per akun**; badge hitung `#berbagi-hitung`; bagian grup **read-only** (`"Grup memegang kamera lewat Admin pemiliknya; ubah di baris grup."`); tombol Batal/Simpan ("Menyimpan…" saat busy). Centang Rekaman → otomatis centang Lihat; uncheck semua → baris dihapus. Sukses → tutup diam-diam; baris milik admin lain → `alert("Tersimpan. {n} baris dibiarkan utuh karena diberikan admin lain.")`; gagal → `alert("Gagal menyimpan: {msg}")`.
v3 `components/ShareModal.tsx`: judul `Bagikan — {name}`; **satu checkbox per akun (hanya "boleh melihat")**; badge peran; Batal/Simpan; ErrorBox bila gagal.
**HILANG**: kolom **Rekaman** per akun (backend v3 `set_sharing` hanya tulis `can_view=True`, `admin_streams.py:177-190`), bagian grup read-only, badge hitung.

### 10.2 Modal akses per akun — **BERBEDA**
v2 `modals.php:350` `#akses-modal` "Camera Access": dropdown Akun (`Pilih akun`), kolom **Kamera / LIVE / REKAMAN / BAGIKAN**, pencarian kamera, teks awal `"Pilih akun dahulu"`, tombol Cancel / Simpan Akses.
v3 `app/admin/access/page.tsx`: halaman "Akses Kamera" + toggle **Per akun | Per kamera** + pencarian; modal `Akses kamera — {username}` (checkbox per kamera + badge Online/Offline); modal `Akses — {stream.name}` (+ **baris "Tamu (semua sesi guest)"** — BARU, via endpoint role-access).
**HILANG**: kolom REKAMAN dan BAGIKAN per baris (v3 hanya "boleh melihat").

### 10.3 Modal tamu — tidak ada di v2 (tamu = opsi peran `GUEST (Akses Terbatas)` di dropdown peran, `modals.php:156`). Baris Tamu v3 = fitur BARU.

### 10.4 Alur kode tamu (guest link)
v2: login tamu via tombol `login.php` tanpa kode (lihat §1.4). Tidak ada "kode tamu" yang dibagikan untuk kamera spesifik di v2.
v3: guest login tanpa kode (`GUEST_ENABLED=true`); akses tamu per kamera via role-access. **Status: ADA** (setara, v3 menambah granularitas per kamera).

---

## 11. Modal admin

### 11.1 Tambah/edit kamera — **BERBEDA**
v2 `modals.php:2` `#stream-modal` "Add CCTV Stream URL" (desc `"Alamat RTSP, grup, dan koordinat kamera"`): Camera Name/ID (wajib), Camera Group (wajib, **datalist grup existing**), Coordinates (lat, lon), RTSP Target URL (wajib; hint `"RTSP credential links will remain securely hidden from user role profiles."`), toggle Active Feed (`"Camera will be visible to users"`), toggle Recording (`"Simpan rekaman ke disk"` → dropdown Save to Disk `/`, **preview Recording Path** `{disk}/recordings/{group}/{nama_kamera}/`, Retention 1–365 default 7). Tombol Cancel / Save Configuration.
v3 `AddStreamModal` (`streams/page.tsx:799-966`): nama, brand (+auto), host, user, password, recording toggle, retensi, storage mode local/drive.
**HILANG**: datalist grup, preview recording path, toggle Active Feed eksplisit. **BARU**: brand selector, storage mode.

### 11.2 Generate API key — **ADA** (dengan catatan)
v2 `modals.php:801` "Generate New API Key" (`"Buat kunci baru untuk pemutar di server lain"`): Nama Klien/Server (wajib), Judul Kamera Kustom (opsional), Domain lock (hint `"kosongkan = PUBLIC"`), Password tambahan (hint `&pass=...` wajib bila diisi), checklist kamera multi + **Semua/Kosong** + hitung `"0 dipilih"` + **pencarian kamera** (`api-cam-search`), hint `"Kamera pertama yang dicentang menjadi kamera utama"`, **Urutan Kamera** (`&camera=1/2/...`), toggle **"Sertakan playback jika ada"**. Tombol Cancel / Generate API Key. Validasi kosong → toast `"Pilih minimal satu kamera dan isi nama klien!"`. Sukses → toast `"✅ Kunci API berhasil digenerate!"`, **key hanya tampil di tabel** (tidak di modal).
v3 `KeyFormModal` (`keys/page.tsx:~594`): Nama key, domain, kata sandi embed, judul kamera kustom, toggle Sertakan playback, checklist kamera + urutan ↑/↓, tombol Buat Key. Setelah sukses: modal **"API key dibuat"** — `"Salin key ini sekarang — tidak akan ditampilkan lagi."` + blok mono + tombol Panduan Integrasi / Selesai (**alur baru**, v2 tidak ada).
**HILANG**: tombol **Semua/Kosong**, **pencarian kamera** di checklist.

### 11.3 Edit API key — **HILANG**
v2 `modals.php:704` "Edit API Key Integration" (field sama, tombol Simpan Perubahan). v3: hanya buat + hapus + panduan (grep edit/Edit nol hasil di `keys/page.tsx`).

### 11.4 Panduan integrasi — **BERBEDA**
v2 `modals.php:596` `#api-setup-modal` "API Integration Guide": **Catatan Keamanan** (domain/password), stat **Kamera / Playback (AKTIF/MATI) / Domain / Sandi (Ada/Tidak)**, subtitle `Integrasi Klien: {name} - {n} kamera`; toggle mode **Stream Langsung / Rekaman (Playback)**; **pemilih kamera tab** (`&camera=N`); Metode 1 Iframe ("Salin Code") / Metode 2 REST ("Salin URL") / Metode 3 URL pemutar ("Salin URL"); tombol Close.
v3 `IntegrationGuideModal` (`keys/page.tsx:512`): "Panduan Integrasi API"; field tempel API key manual (**BARU**); 3 metode + tombol Salin (→ `"Tersalin ✓"` 2 dtk); tutup via X/klik latar.
**HILANG**: ringkasan stat, Catatan Keamanan, toggle mode stream/playback, pemilih `&camera=N`, tombol Close eksplisit.

### 11.5 Bulk-add dari hasil scan — **HILANG** (modal opsinya)
v2 `webrtc.js:3025-3213` + `modals.php:491`: tombol `"+ Add Selected (n)"` + select-all → modal **"Bulk Add CCTV Config"**: checkbox "Kelompokkan ke dalam Grup" (default nama `"Scanned"`), Koordinat (lat, lon) opsional (auto-isi dari default scan), **Tipe Penamaan**: *Penamaan Asli* / *Nama Kustom + IP* / *Nama Kustom + Nomor Urut* + field Nama Kustom (Prefix). Submit → POST per kamera paralel, dedup by rtsp_url. Hasil: `alert("Berhasil menambahkan {n} kamera!" + " (Gagal/Sudah ada: {m})")`.
v3 `app/admin/scanner/page.tsx:49-127,216`: checkbox + toggle-all → `"+ Tambah terpilih (n)"` → langsung POST per kandidat (nama `Kamera {host}`); berhenti di error pertama.
**HILANG**: seluruh modal opsi (grup, 3 mode penamaan, koordinat).

### 11.6 Hapus massal — **ADA** (v3 lebih baik)
v2: checkbox + select-all → `"Delete Selected (n)"` → confirm count → DELETE paralel → alert hasil → `loadAdminData({keepPage:true})` (`webrtc.js:3537`, `admin-console.php:185`).
v3 `streams/page.tsx:348`: bulk bar (`"{n} dipilih"`, "Set koordinat (n)", "Hapus terpilih (n)", "Batalkan pilihan") → ConfirmModal → ErrorBox.

### 11.7 Set koordinat massal — **ADA** (v3 lebih baik)
v2 `admin-console.php:176`, `webrtc.js:3437`: `"Set Coords (n)"` → modal "Bulk Edit Coordinates" (field `"Koordinat Kamera Baru (lat, lon)"` bebas + hint jumlah) → PUT paralel → alert hasil/parsial.
v3 `BulkCoordsModal` (`streams/page.tsx:526`): `Set koordinat ({n} kamera)`, Latitude/Longitude terpisah + **validasi rentang**, `"Terapkan ke semua terpilih"`.

### 11.8 Rename grup — **HILANG**
v2 `modals.php:219` "Rename Group" (`"Seluruh anggota grup ikut berpindah sekaligus"`): field Nama Grup (maxlength 60), info `"{nama_lama} · {n} anggota ikut pindah"`, toggle **"Tampilkan Iklan"** (`"Berlaku utk seluruh anggota grup"`), Cancel / Save Group Name.
v3 `app/admin/groups/page.tsx`: modal "Tambah Grup" + "Kamera grup — {name}" saja; **tanpa rename, tanpa toggle iklan grup**.

---

## 12. Keyboard shortcut

| Shortcut v2 | Lokasi | v3 | Status |
|---|---|---|---|
| Esc tutup popup kamera | `webrtc.js:2761` | Esc tutup FocusModal (`FocusModal.tsx:66`) | BERBEDA (cakupan menyempit) |
| Esc tutup modal teratas (cerdas IME: Esc pertama batalkan isian) | `modal-tutup.js:30` | `ui.tsx Modal` tanpa handler Esc | HILANG |
| Klik latar tutup modal | `modal-tutup.js` | `Modal onClick={onClose}` | ADA |
| ArrowLeft/Right prev/next kamera di popup | `webrtc.js:1830` | — | HILANG |
| F fullscreen, T theater, M mute, Spasi play/pause (popup) | `webrtc.js:1830,1852-1860` | — | HILANG |
| ArrowUp/Down snap bottom-sheet peta | `maps-sheet.js:80` | — | HILANG |
| Esc keluar web-fullscreen (custom monitor) | `admin.js:2156` | — | HILANG |

---

## 13. Perbedaan mobile vs desktop (agregat v2)

| Area | Mobile | Desktop |
|---|---|---|
| Live grid | collapse ke 1 kolom (`webrtc.js:445-459`) | 2/3/4 kolom per layout |
| Live tile | single tap toggle overlay + anti ghost-click (<300ms, <10px) | double-click buka popup |
| Playback timeline | Pointer Events (satu jalur sentuh+mouse) | sama |
| Peta sidebar | bottom sheet draggable, snap 25/45/80%, keyboard accessible | sidebar kiri tetap |
| Peta zoom | `scrollWheelZoom` mati (<767px), `tap:true` | aktif |
| Control bar live | wrap di layar kecil | penuh |

v3 mempertahankan pola mobile-first (collapsed-first accordion, touch ≥44px, input 16px, bottom tabs) tetapi: bottom-sheet peta hilang, double-click→popup menjadi tap-toggle→expand, scrollWheelZoom mobile tidak dimatikan.

---

## 14. Daftar periksa Zero Deprecation — SEMUA yang HILANG di v3

### Kritis (mengubah alur kerja inti)
1. [ ] Pagination Live & Monitor (v2 `pagination-bar.php`, kapasitas grid²)
2. [ ] Force-reconnect per tile "Coba Hubungkan Paksa" (`webrtc.js:485,766-783`)
3. [ ] Auto-reconnect WebRTC: retry 4× @400ms + force-reconnect diam-diam (`webrtc.js:989-1095`)
4. [ ] Playback: timeline kontinu + scrub + auto-lanjut chunk 120 dtk + skip-gap otomatis (`views/playback.php`)
5. [ ] Playback: dropdown tanggal-yang-ada-rekaman + badge ADA REKAMAN/KOSONG
6. [ ] Peta: clustering + popup cluster + "Lihat Semua Live Feed"
7. [ ] Peta: klik marker/sidebar → langsung live (+ sequence 100m + prev/next)
8. [ ] Filter grup di Live, Playback, Monitor
9. [ ] Izin granular Berbagi: kolom Rekaman & Bagikan per akun (`modals.php:300,350`)
10. [ ] Toast global `showToast` 3,5 dtk (`core.js:190-228`)
11. [ ] Camera popup: prev/next, quality toggle LQ/HQ, tombol peta, bitrate, theater, orientasi-lock (`webrtc.js:1944+`)
12. [ ] Bulk-add scan: modal opsi grup/penamaan/koordinat (`modals.php:491`)
13. [ ] Edit API key (`modals.php:704`)
14. [ ] Rename grup + toggle iklan per grup (`modals.php:219`)

### Sedang
15. [ ] Telemetry overlay fps/res/codec (`webrtc.js:1100-1175`) + loop statistik 2 dtk (`webrtc.js:3668`)
16. [ ] Shortcut keyboard (Esc modal cerdas, panah/F/T/M/Spasi, snap peta, Esc fullscreen)
17. [ ] Bottom-sheet peta mobile + scrollWheelZoom-off (`maps-sheet.js`)
18. [ ] Tile CARTO dark/light per tema; legenda (legenda ADA di v3)
19. [ ] Modal peta per kamera + link Google Maps (`maps.js`)
20. [ ] Theme toggle di halaman login (`login.php:33-46`)
21. [ ] Proteksi logout `Sec-Fetch-Site` (`logout.php:9-14`)
22. [ ] Parameter embed `?pass=` (`embed.php:337-340`)
23. [ ] Empty state role-aware di Live (`webrtc.js:340-352`)
24. [ ] Checklist API key: tombol Semua/Kosong + pencarian (`modals.php:801`)
25. [ ] Panduan integrasi: stat ringkasan, Catatan Keamanan, toggle mode, pemilih `&camera=N` (`modals.php:596`)
26. [ ] Modal tambah kamera: datalist grup, preview recording path, toggle Active Feed (`modals.php:2`)
27. [ ] Tombol melayang "Keluar Fullscreen" monitor (`custom-monitor.php`)
28. [ ] Format `localStorage["cctv_custom_screens"]` tidak dibaca v3 (migrasi putus)
29. [ ] Fallback rute unknown→monitor + alias `viewer` (`router.js`)
30. [ ] Pesan error spesifik embed (ICE/handshake) & teks timeout `"Waktu pemutaran habis. Klik untuk memutar kembali."`
31. [ ] Jam digital Asia/Jakarta (`ui.js:3`); poster capture 30 dtk (`webrtc.js:864`)
32. [ ] Timpa grouping confirm (`admin.js:2012`) — v3 pakai form edit

### Catatan
- Item BERBEDA yang fungsinya setara (logout server-side, rute Next.js, WS ganti polling 15 dtk, ConfirmModal ganti `confirm()`, keep-alive "Perpanjang" ambil sesi baru) TIDAK masuk daftar — itu peningkatan, bukan kemunduran.
- v3 menambah yang tidak ada di v2: fullscreen per tile, snapshot, unduh rekaman, mode multi-kamera playback, drag-marker peta, kartu "Belum dipetakan", baris Tamu di akses kamera, modal "API key dibuat" (salin-sekarang), wizard Scanner CIDR, WebSocket status real-time.

---

## Metodologi

- 4 subagent baca-only paralel: (1) login+embed, (2) halaman operator, (3) realtime+notifikasi, (4) sharing+modal+shortcut.
- Setiap klaim paritas diverifikasi terhadap file v3 yang disebut (baris spesifik).
- Tidak ada file repo yang diubah; satu-satunya output adalah laporan ini.
- Celah kecil: perilaku CSS murni (`layout-body-split`) dan runtime sesungguhnya tidak diverifikasi — hanya yang terlihat dari PHP/JS/TSX dan kelas Tailwind.
