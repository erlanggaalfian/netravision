# Analisa V2 → V3 — Halaman Operator (Tamu & User Biasa)

> Sumber V2: `/tmp/v2-ref` (Mamura Stream v2.0, PHP + JS).
> Pembanding V3: `~/workspace/netravision/apps/web`.
> Aturan mutlak: **Zero Deprecation** — semua yang ada di V2 wajib ada di V3.
> Status paritas: **ADA** (setara) / **BERBEDA** (ada tapi perilaku/tampilan berbeda) / **HILANG** (tidak ada di V3).

---

## A. Navigasi & Shell Operator

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| A1 | Menu "Semua Kamera" | `frontend/includes/sidebar.php:15` (`#nav-viewer`) | Selalu tampil | Navigasi ke `index.php?page=monitor` | **ADA** (label "Live") | `app/live/page.tsx`, `components/AppShell.tsx` |
| A2 | Menu "Screen" | `sidebar.php:27` (`#nav-custom`) | Selalu tampil | Navigasi ke custom monitor | **ADA** (label "Monitor") | `app/monitors/page.tsx` |
| A3 | Menu "Peta Kamera" | `sidebar.php:39` (`#nav-maps`) | Selalu tampil | Navigasi ke peta | **ADA** (label "Peta") | `app/maps/page.tsx` |
| A4 | Menu "Playback" | `sidebar.php:52` (`#nav-playback`) | Selalu tampil | Navigasi ke playback | **ADA** (label "Putar Ulang") | `app/playback/page.tsx` |
| A5 | Menu "Admin" | `sidebar.php` (`#nav-admin`) | Hanya bila `bolehKelola(role)` (admin/super_admin); disembunyikan untuk user & tamu (`router.js:596`) | Navigasi ke admin console | **ADA** | `components/AppShell.tsx` (adminOnly) |
| A6 | Direktori stream sidebar ("Stream Trees") | `webrtc.js:211` (`#sidebar-stream-list`) | Selalu tampil setelah login | Daftar semua kamera + dot status (hijau pulse = Live, abu = Offline) + teks status; klik → `focusCameraTile(id)` (fokus ke tile di grid) | **HILANG** | — |
| A7 | Badge hitungan kamera sidebar | `webrtc.js:211` (`#sidebar-camera-count`) | Selalu tampil | Format "x/y" (online/total); "..." saat memuat | **HILANG** | — |
| A8 | Kartu profil sidebar | `router.js:585-591` (`#profile-name`, `#profile-role`, `#profile-initial`) | Selalu tampil | Nama user, ROLE (uppercase), inisial avatar | **ADA** | `components/AppShell.tsx` (user card) |
| A9 | Toggle tema gelap/terang | `login.php` + sidebar | Selalu tampil | Toggle class `dark`, simpan di localStorage | **ADA** | `components/ThemeToggle.tsx` |
| A10 | Tombol Keluar (logout) | sidebar | Selalu tampil | Hapus token, kembali ke login | **ADA** | `components/AppShell.tsx` |
| A11 | Navigasi bawah mobile | `router.js:603` (`#mobile-nav-admin`) | Mobile saja; Admin disembunyikan untuk non-admin | Tab bar bawah | **ADA** | `components/AppShell.tsx` |

---

## B. Halaman Live — "Semua Kamera" (`frontend/views/live-monitor.php`)

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| B1 | Intro box: judul "Semua Kamera", deskripsi "Pantau kamera langsung, saring grup, atur tata letak", ikon kamera | `live-monitor.php:11-17` | Selalu tampil | Header halaman | **BERBEDA** — V3 punya header "Live" + hitungan kamera/online, tanpa ikon & deskripsi pola intro | `app/live/page.tsx:121` |
| B2 | Dropdown filter grup `#viewer-group-filter` | `live-monitor.php:29` | Opsi "All Groups" + daftar grup; `onchange=filterViewerStreams()` | Filter grid per grup kamera | **HILANG** | — |
| B3 | Grid picker 1x1 / 2x2 / 3x3 / 4x4 | `live-monitor.php:39-44` | Tombol `#grid-btn-1..4`; default aktif 3x3 | `changeGridLayout(n, true)` — ubah kolom grid | **ADA** | `app/live/page.tsx:147` |
| B4 | Pagination bar: tombol « ‹, nomor halaman, › », + indikator "Halaman X / Y · N kamera" | `includes/pagination-bar.php:20-35` (`#cctv-pagination`, `#page-indicator`) | Muncul bila total halaman > 1; disembunyikan bila ≤1 (`webrtc.js:1310`) | `jumpToPage(i)`, `changePageOffset(±1)`; kapasitas halaman = grid² | **HILANG** | — |
| B5 | Empty state "No Feeds Available" / "Belum ada kamera untuk akun Anda. Hubungi administrator." | `live-monitor.php:53-60` (`#viewer-empty-state`) | Muncul bila daftar kamera kosong | Panel ilustrasi | **BERBEDA** — V3 ada empty state tapi teks berbeda | `app/live/page.tsx:306` |
| B6 | Filter status (Semua/Online/Offline) | — (tidak ada di V2) | — | — | ➕ Tambahan V3 (diizinkan) | `app/live/page.tsx:15` |
| B7 | Indikator WebSocket "Real-time" | — (tidak ada di V2) | — | — | ➕ Tambahan V3 (diizinkan) | `app/live/page.tsx` |

---

## C. Tile Kamera di Grid (`webrtc.js:1271-1420` — `renderVideoGrid`)

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| C1 | Badge kode kamera `CAM_001` (format `CAM_` + id 3 digit) | `webrtc.js:1340` (`.ms-badge--overlay`) | **Disembunyikan untuk role guest** (`showTopLeft`, `webrtc.js:1339`) | Label statis | **HILANG** | — |
| C2 | Pill status ONLINE (hijau) / OFFLINE (merah) | `webrtc.js:1343` | Selalu tampil (non-guest) | Label statis | **HILANG** (V3 hanya dot kecil + chip LIVE saat memutar) | `components/CameraTile.tsx:103` |
| C3 | Nama kamera (uppercase) | `webrtc.js:1349` | Selalu tampil (non-guest) | Label statis | **ADA** (tidak uppercase) | `components/CameraTile.tsx` |
| C4 | Badge REC (merah, online) / LOSS (abu, offline) kanan atas | `webrtc.js:1354` | Selalu tampil | Label statis | **HILANG** | — |
| C5 | Telemetri: chip fps (30.0), res (1080p), codec (H264) | `webrtc.js:1253-1262` (`#cam-telemetry-*`) | Selalu tampil di overlay bawah | Info statis per tile | **HILANG** | — |
| C6 | Tombol "Buka" (ikon expand + label) | `webrtc.js:1263` (`.cam-tile-expand-btn`) | Muncul di overlay bawah (hover / tap) | Buka popup kamera | **BERBEDA** — V3 ada tombol expand tapi ikon saja tanpa label "Buka" | `components/CameraTile.tsx` |
| C7 | Banner iklan overlay di tile (muncul saat hover) | `webrtc.js:1192` (`buildTileOverlayBottom`) | Hanya bila `ad.is_active`; logo + marquee | Overlay bawah mengikuti 16 field AdConfig | **HILANG** (V3 hanya di FocusModal & embed) | — |
| C8 | Klik tile → buka popup | `webrtc.js:attachCamTileEvents` | Selalu | `openCameraPopup(stream)` | **BERBEDA** — V3: klik tile = tap-toggle kontrol; buka modal lewat tombol expand | `components/CameraTile.tsx:62` |
| C9 | Tap-toggle kontrol di layar sentuh + auto-tampil 3 detik saat grid dimuat | `webrtc.js:1404-1410` (`.tile-controls-visible`) | Touch device | Tampilkan/sembunyikan overlay kontrol | **ADA** | `components/CameraTile.tsx` (`vk-touch-toggle`) |
| C10 | Tombol fullscreen per tile | — (V2 tile tidak punya; hanya di popup) | — | — | ➕ Tambahan V3 (diizinkan) | `components/CameraTile.tsx:172` |
| C11 | Poster sebagai background + lazy-load via IntersectionObserver | `webrtc.js:1294,1413` | Selalu | Hemat koneksi WebRTC | **ADA** | `components/CameraTile.tsx:36` |
| C12 | State offline: poster redup + ikon + "Offline"/"Kamera tidak terjangkau" | `webrtc.js:1367` | `status === "offline"` | Tampilan statis | **ADA** | `components/CameraTile.tsx:108` |
| C13 | Klik background kosong → sembunyikan semua overlay tile | `webrtc.js:1183` | Selalu | Hapus class `tile-controls-visible` | **HILANG** | — |

---

## D. Popup Video Kamera (`webrtc.js:1534-1880` — `createPopupModalElement` + `openCameraPopup`)

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| D1 | Header: dot REC + label "REC"/"LOSS", dot status, `CAM_xxx`, nama kamera, teks status ("RTSP ONLINE") | `webrtc.js:1600-1615` (`#popup-rec-dot`, `#popup-cam-id`, `#popup-cam-name`, `#popup-cam-status`) | Selalu; metadata disembunyikan untuk guest (`webrtc.js:2605`) | Label status | **BERBEDA** — V3: dot status + nama + brand + teks "● Online/Offline" di footer; tanpa REC, tanpa CAM_xxx | `components/FocusModal.tsx` |
| D2 | Tombol close (X) kanan atas, muncul saat hover | `webrtc.js:1552` | Selalu | `closeCameraPopup()` | **ADA** (selalu tampil di header) | `components/FocusModal.tsx` |
| D3 | Klik backdrop → tutup | `webrtc.js:1640` | Selalu | `closeCameraPopup()` | **ADA** | `components/FocusModal.tsx` |
| D4 | Tombol Prev (←) / Next (→) navigasi kamera | `webrtc.js:1557-1565` (`#popup-prev-btn`, `#popup-next-btn`) | Muncul bila sequence > 1 kamera; hover | Pindah kamera dalam sequence (wrap-around) | **HILANG** | — |
| D5 | Control bar bawah: Play/Pause | `webrtc.js:1572` (`#popup-play-btn`, title "Play/Pause (Spasi)") | Hover | Play/pause video; ikon berubah | **BERBEDA** — V3 pakai kontrol bawaan `<video controls>` | `components/FocusModal.tsx` |
| D6 | Control bar: Mute/Unmute | `webrtc.js:1575` (`#popup-volume-btn`, title "Mute/Unmute (M)") | Hover | Unmute = buka koneksi WebRTC audio terpisah di background (`popup-audio-only-element`); mute = tutup koneksi (hemat bandwidth) | **HILANG** | — |
| D7 | Badge "● LIVE" | `webrtc.js:1578` | Selalu (sm+) | Label statis | **HILANG** | — |
| D8 | Tombol kualitas LQ/HQ | `webrtc.js:1583` (`#popup-quality-btn`, title "Ganti Kualitas (LQ/HQ)") | Selalu | Ganti seamless sub↔main stream via video temp tersembunyi; default HQ di desktop, LQ di mobile | **HILANG** | — |
| D9 | Tombol kunci orientasi layar (R) | `webrtc.js:1585` (`#popup-orientation-btn`, title "Putar Orientasi Layar (R)") | Selalu | Fullscreen + `screen.orientation.lock("landscape"/"portrait")`; toast bila gagal | **HILANG** | — |
| D10 | Tombol mode teater (T) | `webrtc.js:1588` (`#popup-theater-btn`, title "Mode Teater (T)") | `hidden md:block` (desktop) | Toggle panel `max-w-5xl` ↔ `w-[95vw]` | **HILANG** | — |
| D11 | Tombol fullscreen (F) | `webrtc.js:1591` (`#popup-fullscreen-btn`, title "Layar Penuh (F)") | Selalu | Fullscreen pada wrapper (iOS: `webkitEnterFullscreen`) | **HILANG** (V3 hanya fullscreen per tile, bukan modal) | — |
| D12 | Ikon fullscreen berubah saat masuk/keluar fullscreen | `webrtc.js:1752` (`fullscreenchange`) | Saat fullscreen | Ganti SVG | **HILANG** | — |
| D13 | Ad bar **di bawah video** (selalu terlihat, bukan overlay) | `webrtc.js:1596` (`#popup-ad-overlay`, `.ms-popup-ad-bar`) | Bila `ad.is_active` | Logo + marquee mengikuti AdConfig | **BERBEDA** — V3: overlay lower-third di atas video | `components/AdBanner.tsx` |
| D14 | Ad bar dipindah ke dalam elemen fullscreen agar tetap terlihat | `webrtc.js:1758` | Saat fullscreen popup | Pindah DOM + kembalikan | **HILANG** | — |
| D15 | Touch: tap pada video toggle kontrol, auto-hide 3 detik | `webrtc.js:1772` (`touch-controls-visible`) | Touch device + fullscreen | Toggle class, timer 3 dtk | **HILANG** | — |
| D16 | Tombol "Peta" di footer | `webrtc.js:1619` (`#popup-map-btn`) | Muncul bila kamera punya koordinat | Tutup popup → buka modal peta kamera tsb (`openMapModal`) | **HILANG** | — |
| D17 | Tombol "Tutup" di footer | `webrtc.js:1625` | Selalu | `closeCameraPopup()` | **ADA** (tombol X di header) | `components/FocusModal.tsx` |
| D18 | Keyboard: Esc tutup | `webrtc.js:2761` | Popup terbuka | Tutup | **ADA** | `components/FocusModal.tsx` |
| D19 | Keyboard: F fullscreen, T teater, M mute, Spasi play/pause, ←/→ prev/next | `webrtc.js:1830-1870` | Popup terbuka | Aksi masing-masing tombol | **HILANG** | — |
| D20 | Loading bar (garis biru atas) saat ganti kamera | `webrtc.js:1547` (`#popup-loading-bar`) | Saat transisi | Indikator | **HILANG** | — |
| D21 | Tombol "Snapshot" | V3 menambah (tidak ada di V2) | — | Unduh JPEG frame | ➕ Tambahan V3 (diizinkan) | `components/FocusModal.tsx:114` |
| D22 | State offline: "Gagal Konek ke RTSP: {nama}" + "WHEP WebRTC connection failed" + tombol **"Coba Hubungkan Paksa"** | `webrtc.js:2220` | `status === "offline"` | `forceLoadStream(id)` lalu tutup popup | **HILANG** (V3 hanya teks "Kamera offline") | — |
| D23 | Mode cluster: grid multi-kamera dalam popup ("N KAMERA DI LOKASI INI", "SOME ONLINE"/"ALL OFFLINE", total KBPS, tombol "Lihat Semua Live Feed") | `webrtc.js:2438-2560` | Dibuka dari marker cluster peta | Grid tile per kamera dalam popup | **HILANG** | — |
| D24 | Sub-stream dulu (<100ms) lalu upgrade HD background otomatis | `webrtc.js:2258,2308` | Desktop (≥768px) | Video temp tersembunyi → swap srcObject seamless | **BERBEDA** — V3 langsung main stream | `components/FocusModal.tsx` |
| D25 | Klon instan dari tile grid yang sedang aktif | `webrtc.js:2288` | Popup dibuka dari halaman monitor/custom | `srcObject` disalin (tanpa handshake baru) | **HILANG** | — |

---

## E. Halaman Playback (`frontend/views/playback.php`)

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| E1 | Intro "Playback" — "Putar rekaman tersimpan dan lompat ke jam mana pun" | `playback.php:9-14` | Selalu | Header | **BERBEDA** — V3 ada header sendiri | `app/playback/page.tsx` |
| E2 | Dropdown filter grup `#pb-group-filter` ("All Groups") | `playback.php:27` | Selalu | Filter kartu kamera per grup | **HILANG** | — |
| E3 | Grid picker 2x2 / 3x3 / 4x4 (`data-pb-grid`) | `playback.php:39-43` | Default 3x3 | `setPlaybackGrid(cols)` | **ADA** (mode multi-kamera) | `app/playback/page.tsx:40` |
| E4 | Kartu kamera: poster, badge "ADA REKAMAN" (hijau) / "KOSONG" (abu), nama + grup, ikon play saat hover | `playback.php:230-260` | Selalu | Klik → `openPlaybackModal(cam.id)` | **BERBEDA** — V3: panel playback langsung per kamera terpilih (chip), tanpa badge ADA/KOSONG & poster | `app/playback/page.tsx` |
| E5 | Empty state "Belum Ada Rekaman" | `playback.php:53` (`#playback-empty`) | Bila tak ada kamera berrekaman | Panel statis | **ADA** | `app/playback/page.tsx` |
| E6 | Modal playback: judul nama kamera + grup, tombol close (Esc), klik backdrop tutup | `playback.php:62-80` (`#pb-modal`) | Saat kartu diklik | `openPlaybackModal` / `closePlaybackModal` | **BERBEDA** — V3 tanpa modal; panel inline | `app/playback/page.tsx` |
| E7 | Dropdown tanggal: "YYYY-MM-DD (N segment)" | `playback.php:104` (`#playback-date-select`) | Setelah tanggal dimuat | `loadPlaybackTimeline()`; info "N tanggal tersedia" | **HILANG** (V3: tanggal bersama untuk semua panel, tanpa daftar tanggal ber-segmen) | — |
| E8 | Tombol transport: "← 30s", "Play / Pause", "30s →" | `playback.php:112-114` | Selalu di modal | `pbSeekRelative(±30)`, `pbTogglePlay()` | **HILANG** | — |
| E9 | Jam berjalan `#pb-clock` + label rentang tanggal | `playback.php:117-118` | Saat memutar | Update via `timeupdate` | **HILANG** | — |
| E10 | Timeline: bar hijau per rentang rekaman (tooltip jam), tick per jam, playhead merah, label 00:00–23:59, "Klik timeline untuk melompat ke jam tertentu" | `playback.php:122-134` | Setelah timeline dimuat | Pointer Events: klik/drag scrub (`seekManual`); playhead mengikuti `timeupdate` | **BERBEDA** — V3: bar segmen bisa diklik (tanpa drag scrub, tanpa playhead, tanpa tick jam) | `app/playback/page.tsx:196` |
| E11 | Loading overlay "Memuat rekaman..." (spinner) | `playback.php:87` (`#playback-loading`) | Saat fetch chunk | Tampil/sembunyi | **BERBEDA** — V3 skeleton saat memuat | `app/playback/page.tsx:171` |
| E12 | Pesan "Belum ada rekaman untuk kamera ini" / "Gagal memuat…" | `playback.php:90` (`#pb-no-rec`) | Bila kosong/gagal | Overlay | **ADA** | `app/playback/page.tsx` |
| E13 | Lompat otomatis ke rekaman berisi (lewati potongan kosong/rusak, maks 40 lompatan) | `playback.php` (`seekToEpoch`, `cariTerisi`, `MIN_POTONGAN`, `MAKS_LOMPAT`) | Saat potongan < 1 dtk atau error | Cari via `/next-playable` atau range berikut | **HILANG** | — |
| E14 | Lanjut otomatis ke chunk berikutnya saat video ended (tanpa berhenti di jeda kosong) | `playback.php` (`ended` handler) | Saat chunk selesai | `seekToEpoch(next)` | **HILANG** | — |
| E15 | Tombol unduh potongan (MP4) | V3 menambah | — | `GET /recordings/{id}/file` | ➕ Tambahan V3 (diizinkan) | `app/playback/page.tsx:117` |

---

## F. Halaman Peta (`frontend/views/maps.php`)

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| F1 | Intro "Peta Kamera" + badge hitungan `#map-total-badge` | `maps.php:12-17` | Selalu | Badge = jumlah kamera terpeta | **BERBEDA** — V3 ada header tanpa badge hitungan | `app/maps/page.tsx` |
| F2 | Search "Cari kamera..." `#map-search-input` | `maps.php:30` | Selalu | `filterMapCCTVList()` — filter nama/grup/koordinat | **ADA** | `app/maps/page.tsx:297` |
| F3 | Daftar CCTV sidebar: dikelompokkan per grup (header 📁 + hitungan), dot status + nama + koordinat per item | `maps.php` (`renderSidebarList`) | Selalu | Klik item → `focusCamera()` (sorot + buka popup + tampilkan live feed kamera ±100m) | **BERBEDA** — V3: daftar tanpa grup & tanpa koordinat; klik → fokus marker | `app/maps/page.tsx` |
| F4 | Legenda overlay: "Kamera Aktif" (hijau) / "Kamera Offline" (merah) | `maps.php:46` | Selalu | Overlay statis | **HILANG** | — |
| F5 | Marker: pin 34px berwarna status + ikon kamera; badge merah hitungan bila cluster > 1 | `maps.php` (`plotMarkers`) | Selalu | Cluster otomatis bila jarak piksel ≤ 50 (re-cluster saat zoom) | **BERBEDA** — V3: marker standar tanpa cluster & badge hitungan | `app/maps/page.tsx` |
| F6 | Popup marker: daftar kamera (nama + status) + tombol "👁️ View" per kamera; bila cluster: judul "Cluster: N Kamera" + tombol "Lihat Semua Live Feed" | `maps.php` (`plotMarkers`) | Saat marker diklik | `openCameraPopup(stream, sequence)` | **BERBEDA** — V3: popup hanya nama + brand + status, tanpa tombol aksi | `app/maps/page.tsx:41` |
| F7 | Klik marker kamera tunggal → langsung buka popup video | `maps.php` | Cluster beranggota 1 | `openCameraPopup` | **HILANG** | — |
| F8 | Tile dasar CARTO gelap/terang mengikuti tema | `maps.php` (`initMap`) | Selalu | `CARTO_DARK` / `CARTO_LIGHT` | **ADA** | `app/maps/page.tsx` |
| F9 | Auto-fit bounds ke semua marker (padding 50, maxZoom 15) | `maps.php` (`initMap`, `invalidateMapSize`) | Saat data dimuat / resize | `fitBounds` / `setView` | **ADA** | `app/maps/page.tsx` |
| F10 | State kosong: "TIDAK ADA KAMERA TERPETAKAN" + petunjuk ke Admin Console | `maps.php` (`loadMapData`) | Bila tak ada koordinat valid | Panel statis | **ADA** | `app/maps/page.tsx` |
| F11 | State error: "Gagal memuat data CCTV." + pesan error | `maps.php` (`loadMapData`) | Bila fetch gagal | Panel statis | **ADA** | `app/maps/page.tsx` |
| F12 | Zoom control Leaflet; scroll-wheel zoom dimatikan di mobile (<768px) | `maps.php` (`initMap`) | Selalu | Opsi peta | **BERBEDA** — V3: default Leaflet | `app/maps/page.tsx` |
| F13 | Klik item daftar → highlight + scroll ke item | `maps.php` (`highlightListItem`) | Selalu | Sorot biru + `scrollIntoView` | **HILANG** | — |

---

## G. Halaman Screen / Custom Monitor (`frontend/views/custom-monitor.php`)

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| G1 | Intro "Screen" — "Susun layar pantau sendiri dan simpan grupnya" + tombol **Fullscreen** di header | `custom-monitor.php:9-17` | Selalu | `toggleFullscreen('custom-cctv-grid')` | **BERBEDA** — V3: tombol fullscreen ada di halaman (bukan di intro) | `app/monitors/page.tsx` |
| G2 | Panel "Custom Playlist": dropdown "Tipe Tampilan" — "Kustom (Pilih Manual)" / "Per Grup Kamera" | `custom-monitor.php:41` (`#custom-view-mode`) | Selalu | `toggleCustomViewMode()` — ganti panel | **BERBEDA** — V3: mode grup ada (`GroupSections`); mode kustom = layout manual | `app/monitors/page.tsx:103` |
| G3 | Daftar "Select & Sort Feeds" (checkbox + sortir kamera) | `custom-monitor.php:51` (`#custom-camera-select-list`) | Mode kustom | Pilih & susun urutan | **BERBEDA** — V3: reorder via tombol ↑/↓ di form edit | `app/monitors/page.tsx` |
| G4 | Tombol "Save & Load Playlist" | `custom-monitor.php:56` | Mode kustom | `saveCustomPlaylist()` | **ADA** | `app/monitors/page.tsx` |
| G5 | Panel mode grup: "Pilih Grup Kamera" (daftar grup) | `custom-monitor.php:63` (`#custom-groups-list`) | Mode grup | Tampilkan kamera per grup | **ADA** | `app/monitors/page.tsx:103` |
| G6 | Panel "Screen Groups": input "Nama Grouping Baru" + tombol "Simpan" | `custom-monitor.php:78-81` | Selalu | `saveCurrentAsNewScreen()` | **ADA** | `app/monitors/page.tsx` |
| G7 | "Daftar Grouping" (grup tersimpan) | `custom-monitor.php:86` (`#saved-screens-list`) | Selalu | Muat/hapus grup | **ADA** | `app/monitors/page.tsx` |
| G8 | Filter grup `#custom-group-filter` ("All Groups") | `custom-monitor.php:100` | Selalu | `filterCustomGroupFeeds()` | **HILANG** | — |
| G9 | Grid picker 1x1–4x4 `#cust-grid-btn-*` | `custom-monitor.php:112-117` | Selalu | `changeCustomGridSize(n)` | **ADA** | `app/monitors/page.tsx` |
| G10 | Pagination bar `#custom-cctv-pagination` (« ‹ halaman › » + indikator) | `custom-monitor.php:128-141` | Bila > 1 halaman | `jumpToCustomPage`, `changeCustomPageOffset` | **HILANG** | — |
| G11 | Empty state "Playlist Empty" / "Centang minimal satu kamera di panel kiri…" | `custom-monitor.php:146` | Bila playlist kosong | Panel statis | **ADA** | `app/monitors/page.tsx` |
| G12 | Tombol "Keluar Fullscreen" (mengambang) | `custom-monitor.php:160` (`#exit-web-fullscreen-btn`) | Saat fullscreen | `toggleFullscreen(...)` | **HILANG** | — |

---

## H. Halaman Embed Publik (`frontend/embed.php`)

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| H1 | Loading screen: spinner + "Menghubungkan ke server stream..." | `embed.php:128` (`#loading-screen`) | Saat inisialisasi | Disembunyikan setelah respons API | **BERBEDA** — V3 ada state memuat sendiri | `app/embed/page.tsx` |
| H2 | Error screen: ikon + `#error-title` + `#error-message` | `embed.php:134` (`#error-screen`) | Bila gagal | `showError(title, msg)`; sembunyikan player | **ADA** | `app/embed/page.tsx` |
| H3 | Video element (object-contain, playsinline, muted) | `embed.php:145` (`#video-element`) | Selalu | WHEP via `startWhep()` | **ADA** | `app/embed/page.tsx` |
| H4 | Play overlay: tombol play besar + teks opsional | `embed.php:148` (`#play-overlay`) | Bila `click_to_play=true` | Klik → `startWhep(playUrl)`; listener di-clone agar tak duplikat | **BERBEDA** — V3: tombol putar sederhana | `app/embed/page.tsx` |
| H5 | Label info kamera: dot hijau pulse + "{nama} - Live" | `embed.php:158` (`#camera-info-overlay`) | Bila `data.stream.name` ada | Overlay kiri atas | **HILANG** | — |
| H6 | Tombol "Stop Feed" kanan atas | `embed.php:164` (`#stop-button`) | Setelah mulai memutar | `stopWhep(false)` → tutup PC, tampilkan overlay play | **ADA** (label "Stop") | `app/embed/page.tsx:217` |
| H7 | Keep-alive toast: "Pemutaran akan dihentikan dalam N detik." + tombol **"Lanjutkan Menonton"** | `embed.php:169` (`#keep-alive-toast`) | 15 detik sebelum `embed_timeout_seconds` habis | `extendPlaytime()` — reset timer dari nol | **ADA** (toast + tombol "Perpanjang") | `app/embed/page.tsx:185` |
| H8 | Auto-stop saat `embed_timeout_seconds` tercapai + teks overlay "Waktu pemutaran habis. Klik untuk memutar kembali." | `embed.php` (`playTimeout`, `stopWhep(true)`) | Bila timeout > 0 | Hentikan stream | **ADA** | `app/embed/page.tsx:109` |
| H9 | Banner iklan overlay (logo + marquee, 16 field AdConfig) | `embed.php:184` (`#ad-banner-overlay`, `applyAd`) | Bila `data.ad.is_active` | Posisi mengikuti box_width/text_align | **ADA** | `components/AdBanner.tsx` |
| H10 | Poster statis: `/api/posters/stream_{id}.jpg` | `embed.php` | Bila `data.stream.id` ada | `video.poster = ...` | **HILANG** | — |
| H11 | Param URL: `?key=` (wajib), `?pass=`, `?camera=` | `embed.php` | Saat dibuka | `showError` bila key absen; pilih satu kamera | **ADA** | `app/embed/page.tsx` |
| H12 | Prioritas sub-stream (`webrtc_url_sub || webrtc_url`) | `embed.php` | Selalu | Hemat bandwidth untuk embed | **BERBEDA** — V3 pakai URL dari sesi (main) | `app/embed/page.tsx` |
| H13 | Error koneksi: "Koneksi Gagal" / "Gagal Handshake WHEP" | `embed.php` (`oniceconnectionstatechange`, catch) | Bila ICE gagal / handshake gagal | `showError(...)` | **BERBEDA** — V3 pesan generik | `app/embed/page.tsx` |
| H14 | Tutup koneksi saat tab ditutup (`beforeunload`) | `embed.php` | Selalu | `pc.close()` | **ADA** | `app/embed/page.tsx:127` |

---

## I. Entry Point & Sesi Tamu

| # | Elemen (V2) | Lokasi V2 | Label/Kondisi | Perilaku | Status V3 | File V3 |
|---|-------------|-----------|---------------|----------|-----------|---------|
| I1 | Halaman login: form username + password + tombol "Masuk" | `frontend/login.php` | Selalu | `POST /api/auth/login` → simpan token/role/username → `index.php` | **ADA** | `app/login/page.tsx` |
| I2 | Tombol "Masuk sebagai tamu" (tanpa kode) | `login.php:82` (`loginAsGuest()`) | Selalu | `POST /api/auth/guest` (tanpa body) → sesi tamu | **ADA** (label "Guest login") | `app/login/page.tsx:120` |
| I3 | Error login: "Login gagal. Periksa kembali kredensial." | `login.php:64` (`#login-error`) | Bila gagal | Box merah | **ADA** | `app/login/page.tsx` |
| I4 | Error tamu: "Sesi tamu gagal dibuat. Hubungi administrator." | `login.php:154` | Bila gagal | Box merah | **HILANG** (V3 pakai pesan generik) | — |
| I5 | Tamu: menu Admin disembunyikan (desktop + mobile) | `router.js:596-607` | Role guest | Tambah class `hidden` | **ADA** | `components/AppShell.tsx` |
| I6 | Tamu: badge kode kamera & pill status disembunyikan di tile | `webrtc.js:1339` | Role guest | `showTopLeft = false` | **N/A** (badge tidak ada di V3) | — |
| I7 | Tamu: metadata header popup disembunyikan | `webrtc.js:2605` (`#popup-header-metadata`) | Role guest | Tambah class `hidden` | **N/A** | — |
| I8 | Toggle tema di halaman login | `login.php` (`toggleTheme()`) | Selalu | Toggle `dark` + localStorage | **HILANG** (V3: toggle hanya di dalam aplikasi) | — |

---

## Ringkasan Paritas

| Halaman | Elemen diinventarisasi | ADA | BERBEDA | HILANG | ➕ Tambahan V3 |
|---------|----------------------|-----|---------|--------|----------------|
| A. Navigasi & Shell | 11 | 9 | 0 | 2 (A6 direktori stream, A7 badge hitungan) | 0 |
| B. Halaman Live | 7 | 1 | 2 | 2 (B2 filter grup, B4 pagination) | 2 |
| C. Tile Kamera | 13 | 4 | 2 | 6 (C1 CAM badge, C2 pill status, C4 REC/LOSS, C5 telemetri, C7 iklan tile, C13 klik-bg) | 1 |
| D. Popup Video | 25 | 4 | 4 | 16 | 1 |
| E. Playback | 15 | 3 | 5 | 6 (E2 filter grup, E7 dropdown tanggal, E8 transport ±30s, E9 jam, E13 lompat-otomatis, E14 lanjut-otomatis) | 1 |
| F. Peta | 13 | 5 | 5 | 3 (F4 legenda, F7 klik-marker→popup, F13 highlight item) | 0 |
| G. Screen | 12 | 6 | 3 | 3 (G8 filter grup, G10 pagination, G12 keluar-fullscreen) | 0 |
| H. Embed | 14 | 8 | 4 | 2 (H5 label info kamera, H10 poster) | 0 |
| I. Tamu/Login | 8 | 4 | 0 | 2 (I4 pesan error tamu, I8 toggle tema di login) + 2 N/A | 0 |
| **TOTAL** | **118** | **44** | **25** | **42 (+2 N/A)** | **5** |

### Daftar HILANG prioritas tertinggi (fitur inti operator)
1. **D4** — Navigasi Prev/Next kamera di popup (+ keyboard ←/→).
2. **D6** — Mute/Unmute dengan audio stream terpisah (+ keyboard M).
3. **D8** — Pilihan kualitas LQ/HQ seamless.
4. **D11** — Fullscreen di dalam modal popup (+ keyboard F).
5. **D10** — Mode teater (+ keyboard T).
6. **D5** — Kontrol Play/Pause kustom (+ keyboard Spasi).
7. **D22** — "Coba Hubungkan Paksa" untuk kamera offline di popup.
8. **B2/E2/G8** — Filter grup di Live, Playback, Screen.
9. **B4/G10** — Pagination di Live & Screen.
10. **E8–E10, E13–E14** — Kontrol transport playback (±30s, jam, scrub playhead, lompat & lanjut otomatis).
11. **C1/C2/C4/C5** — Badge CAM_xxx, pill ONLINE/OFFLINE, badge REC/LOSS, telemetri fps/res/codec di tile.
12. **A6/A7** — Direktori stream di sidebar + badge hitungan kamera.
13. **F4–F7** — Legenda peta, cluster marker + badge hitungan, popup marker dengan tombol aksi, klik marker langsung buka video.
14. **H5/H10** — Label info kamera & poster di embed.
15. **D16** — Tombol "Peta" di popup (lompat ke lokasi kamera).
16. **D13/D14** — Ad bar di bawah video (selalu terlihat) + tetap terlihat saat fullscreen.
