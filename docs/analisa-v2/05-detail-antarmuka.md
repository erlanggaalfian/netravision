# 05 — Detail Elemen Antarmuka (V2 → V3)

Analisa READ-ONLY per halaman: seluruh teks, label, hint, badge, tooltip, ikon,
empty-state, format tampilan, validasi, dan pesan — V2 "Mamura Stream" v2.0
(`/tmp/v2-ref`) dibanding V3 NetraVision (`~/workspace/netravision`).

Status: **ADA** = ada di V3 · **HILANG** = tidak ada padanan di V3 ·
**BERBEDA** = ada tapi teks/perilaku/konteks berubah.

> Aturan Mutlak (Zero Deprecation): setiap item HILANG di bawah ini adalah
> pelanggaran aturan — wajib dikembalikan ke V3. Item BERBEDA perlu ditinjau
> satu per satu (sebagian disengaja: rebrand Mamura Stream → NetraVision).

---

## Ringkasan eksekutif

| Bagian | Detail V2 | ADA | HILANG | BERBEDA |
|---|---|---|---|---|
| A. Login + kerangka (shell) | 62 | 22 | 6 | 34 |
| B. Halaman operator (live/playback/maps/monitor) | 102 | 1 | 51 | 50 |
| C. Halaman admin (tab + modal) | 160 | 38 | 47 | 75 |
| D. Embed + iklan + pesan sistem | 67 | 36 | 9 | 22 |
| **TOTAL** | **391** | **97** | **113** | **181** |

Hanya **25%** detail V2 yang bertahan utuh di V3. **113 detail hilang total**
dan **181 berubah** — mayoritas perubahan teks adalah rebrand + penerjemahan
label yang disengaja, tetapi puluhan di antaranya adalah fungsionalitas yang
lenyap diam-diam.

---

## Daftar gap konsolidasi (semua HILANG — wajib dikembalikan)

### A. Login + shell (6)
1. Theme toggle di halaman login (`login.php:38`, `title="Ganti tema"`).
2. Tagline `Portal Monitoring CCTV` di kartu login (`login.php:52`).
3. Pemisah `atau` antara tombol Masuk dan guest (`login.php:76-80`).
4. Jam digital `00:00:00 UTC` di topbar (`header.php:87`).
5. Nomor halaman individual yang bisa diklik (`n-2…n+2`) di pagination (`pagination-bar.php:26`).
6. Judul + deskripsi intro halaman Peta — halaman peta V3 tanpa header teks sama sekali.

### B. Halaman operator (51)
7. **Playback eksternal API-key hilang total** (11 item): halaman `frontend/playback.php`
   (player rekaman satu-URL tanpa login: judul `Rekaman CCTV`, pemilih kamera,
   pemilih tanggal `{YYYY-MM-DD} ({n} segmen)`, kontrol `← 30d`/`Putar`/`Jeda`/`30d →`,
   jam `HH:MM:SS`, penanda timeline `00:00`/`12:00`/`23:59`, footer retensi
   `Rekaman disimpan terbatas sesuai kebijakan retensi.`).
8. **Paginasi hilang di semua halaman operator** (live + custom monitor).
9. Popup kamera: badge `● LIVE`, metadata `REC`/`CAM_###`/nama UPPERCASE,
   status `RTSP ONLINE`, kontrol LQ/HQ, orientasi, teater, prev/next, tombol `Peta`,
   status cluster `SOME ONLINE`/`ALL OFFLINE`.
10. Telemetri tile: `fps 30.0` / `res 1080p` / `codec H264`; badge `REC`/`LOSS`;
    kode kamera `CAM_001`; badge status tile `ONLINE`/`OFFLINE`.
11. Sidebar daftar kamera live (`Live`/`Offline` + badge count).
12. Timeline playback: scrub bebas + playhead + tick per jam + jam berjalan `14.30.05`;
    label tanggal `{YYYY-MM-DD}`; info `{n} tanggal tersedia`; tombol `← 30s`/`30s →`;
    info `{n} rekaman - total {n} menit`; badge tile `ADA REKAMAN`/`KOSONG`.
13. Alert/confirm custom monitor: `Harap masukkan nama grouping terlebih dahulu.`,
    konfirmasi duplikat, `Grouping "{n}" berhasil disimpan!` / `berhasil dimuat!`;
    label `Select & Sort Feeds`, `Daftar Grouping`, filter `All Groups`,
    tombol `Keluar Fullscreen`.
14. Maps: clustering + popup `Cluster: {n} Kamera`, tombol `👁️ View`,
    `Lihat Semua Live Feed`, header grup `📁 {nama_grup}`, filter grup default `All Groups`.
15. Varian overlay tile khusus guest (tanpa badge/nama).

### C. Halaman admin (47)
16. **Modal Edit API Key utuh** (10 item): `Edit API Key Integration`, Nama Klien,
    Judul Kamera Kustom, Domain Whitelisting, Password tambahan, pilih kamera
    (Semua/Kosong + search), hint kamera utama, Urutan Kamera, toggle playback.
17. **Modal Bulk Add utuh** (7 item): `Bulk Add CCTV Config`, checkbox grouping,
    Nama Grup Kamera, koordinat, 3 tipe penamaan, prefix kustom.
18. **Modal Rename Group utuh** (5 item): `Rename Group`, info `{N} anggota ikut pindah`,
    toggle iklan grup.
19. **Modal Camera Location utuh** (5 item): peta Leaflet, tautan Google Maps,
    `Map data © OpenStreetMap contributors`, hint `Scroll to zoom · Drag to pan`.
20. Panduan integrasi: Catatan Keamanan, kotak ringkasan (Kamera/Playback/Domain/Sandi),
    pilihan mode Stream Langsung/Rekaman, pemilih kamera.
21. Modal Camera Access: dropdown pilih akun, search `Cari kamera…`,
    kolom `LIVE`/`REKAMAN`/`BAGIKAN`, empty-state `Pilih akun dahulu`.
22. Camera Sharing: seksi Grup, search `Cari akun…`, kolom `Lihat`/`Rekaman`.
23. Stream modal: field `Camera Group`, `Save to Disk`, preview `Recording Path`.
24. Scanner: field `Codec / Stream Path`, koordinat default.
25. API log: kartu ringkasan (Total Akses/HIT/DENIED/IP Unik), catatan
    `Log diperbarui otomatis setiap 30 detik saat tab ini aktif.`
26. Tab Camera Access: tombol `Add Access`.
27. User modal: field `Grup Pengguna` (+ input grup baru, hint keanggotaan).
28. Select Peran kehilangan opsi **SUPER ADMIN** (akun super_admin tak bisa dibuat dari UI).
29. Modal Ubah Kamera **tidak bisa mengedit URL RTSP**.
30. `aria-label` aksesibilitas di semua tombol pagination (`Halaman pertama` dkk.).

### D. Embed + iklan (9)
31. Pesan error khusus: `Koneksi Gagal` / `Koneksi WebRTC ke media server terputus.`
    dan `Gagal Handshake WHEP` / `Media server tidak merespons koneksi stream.`
32. Poster video `/api/posters/stream_{id}.jpg` di embed.
33. Auto-play saat `click_to_play=false`.
34. Parameter `?pass=` untuk kata sandi kunci API.
35. Auto-hide banner di layar sangat pendek (media query).
36. Banner hover di tile grid (`AdBanner` V3 hanya di embed & FocusModal).
37. Seksi global `Embed Player Settings (External API)` di UI (field
    `embed_timeout_seconds`/`click_to_play` hidup di skema API tapi tanpa kontrol UI
    dan tidak dibaca halaman embed V3).
38. Teks marquee default V2 (`Selamat Datang di Portal Monitoring CCTV. Hubungi Admin
    untuk info lebih lanjut.`) — default V3 kosong.
39. Pemisah pipe `  |  ` antar item marquee popup/tile.

---

## BERBEDA yang paling berdampak (perlu keputusan)

- **B1/B2/B5**: seluruh label diterjemahkan/disederhanakan (Playback→Putar Ulang,
  Screen→Monitor, Logout→Keluar, `Masuk sebagai tamu`→`Guest login`, tab admin
  Camera Streams→Kamera dsb.) — disengaja, tetapi inkonsisten (guest button Inggris).
- **B1**: filter grup live hilang, diganti filter status; grid default 3x3→4 kolom.
- **B2**: timeline berubah paradigma (scrub bebas+playhead → tombol per segmen);
  pemilih tanggal bebas tanpa daftar `{n} segment`; jam `14.30.05`→`14.30`.
- **B4**: search hanya nama (V2: nama/grup/koordinat); koordinat default Jakarta→Indonesia;
  marker tanpa ikon kamera; koordinat tak tampil di sidebar.
- **B5**: `localStorage` per-akun → key global `nv_monitors`; grid default 3x3→2 kolom.
- **C**: tabel admin → daftar kartu/accordion; koordinat 1 field → Latitude/Longitude;
  RTSP modal tambah jadi alur brand-scan; badge hitung tab hilang; `required`
  pada Isi Teks Marquee hilang; placeholder warna `#FFFFFF`→`#1E293B`.
- **C**: arah Camera Access `Per Grup` (default V2) → `Per akun`/`Per kamera`.
- **D**: seluruh teks halaman embed ditulis ulang (tidak ada pesan V2 verbatim);
  toast keep-alive berbasis `expires_at` bukan `embed_timeout_seconds`;
  banner popup overlay-menimpa-video (V2: bar di bawah video); marquee 4→2 span;
  pesan error backend external disembunyikan di balik 2 pesan generik;
  pesan sukses simpan iklan `Konfigurasi iklan berhasil disimpan!`→`Tersimpan`.
- **A**: pesan error login spesifik → generik (`Gagal masuk. Coba lagi.`);
  pesan error guest khusus hilang; indikator pagination tanpa kata `Halaman`;
  `SectionTitle` tanpa ikon/badge pengganti tab-intro-box.

---

## Detail per bagian

Laporan rinci per bagian (tabel lengkap dengan rujukan file:baris V2 dan lokasi V3)
di bawah ini digabungkan dari empat analisa paralel.


---

# Bagian A — Login + Kerangka Aplikasi (shell chrome)

Analisa READ-ONLY. V2 = `/tmp/v2-ref` (Mamura Stream v2.0). V3 = `~/workspace/netravision/apps/web`.
Status: **ADA** (ada di V3, lokasi disebut) / **HILANG** (tidak ada di V3) / **BERBEDA** (ada tapi teks/perilaku berbeda).

> Catatan rebrand: V3 memakai nama baru **NetraVision** menggantikan "Mamura Stream".
> Perbedaan nama aplikasi yang murni akibat rebrand tetap dicatat sebagai BERBEDA.

---

## 1. Halaman Login (`frontend/login.php`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul tab browser | `login.php:6` | `Mamura Stream - Login` | **BERBEDA** | V3: metadata global `title: "NetraVision"` (`app/layout.tsx:15`) — tanpa sufiks "- Login" |
| Redirect bila sudah login | `login.php:23-25` | `localStorage cctv_auth_token` → `index.php` | **ADA** | V3: `app/login/page.tsx:33-36` — `router.replace("/live")` bila `user` sudah ada |
| Tombol theme toggle pojok kanan atas | `login.php:38` | `title="Ganti tema"`, `aria-label="Ganti tema"` | **HILANG** | V3 tidak punya theme toggle di halaman login; toggle hanya ada di AppShell |
| Logo kartu login | `login.php:47-49` | Ikon kamera SVG biru (`--c-blue`) | **BERBEDA** | V3: `LensMark` — kotak membulat biru `#2563eb` + lingkaran lensa putih (`page.tsx:9-18`) |
| Nama aplikasi | `login.php:51` | `Mamura Stream` | **BERBEDA** | V3: `NetraVision` (`page.tsx:82-84`) — rebrand |
| Tagline aplikasi | `login.php:52` | `Portal Monitoring CCTV` | **HILANG** | Kartu login V3 hanya menampilkan nama; deskripsi "Sistem pemantauan CCTV" hanya ada di metadata layout, bukan di kartu |
| Label field username | `login.php:57` | `Nama pengguna` | **ADA** | `page.tsx:91-96` — teks identik |
| Placeholder username | `login.php:59` | `admin` | **BERBEDA** | V3: `nama pengguna` (`page.tsx:101`) |
| Validasi + autocomplete username | `login.php:58` | `required`, `autocomplete="username"` | **ADA** | `page.tsx:99,102` — identik |
| Label field password | `login.php:63` | `Kata sandi` | **ADA** | `page.tsx:105-110` — teks identik |
| Placeholder password | `login.php:65` | `••••••••` | **ADA** | `page.tsx:115` — identik |
| Autocomplete password | `login.php:64` | `autocomplete="current-password"` | **ADA** | `page.tsx:114` — identik |
| Pesan error login | `login.php:68-70,116` | `Login gagal. Periksa kembali kredensial.` | **BERBEDA** | V3: memakai pesan error dari API bila ada, fallback `Gagal masuk. Coba lagi.` (`page.tsx:43-46`) |
| Tombol submit | `login.php:73` | `Masuk` | **ADA** | `page.tsx:115-117` — teks identik; V3 menambah state sibuk `Memeriksa…` saat request |
| Pemisah "atau" | `login.php:76-80` | `atau` (dengan garis di kiri-kanan) | **HILANG** | V3: tombol guest langsung di bawah tombol Masuk tanpa pemisah |
| Tombol guest | `login.php:83-90` | `Masuk sebagai tamu` + ikon user | **BERBEDA** | V3: `Guest login` (Inggris), tanpa ikon (`page.tsx:118-129`) |
| Pesan error guest | `login.php:124` | `Sesi tamu gagal dibuat. Hubungi administrator.` | **BERBEDA** | V3: tidak ada pesan khusus tamu; memakai fallback generik `Gagal masuk. Coba lagi.` (`page.tsx:53-56`) |
| Bahasa HTML | `login.php:2` | `<html lang="id">` | **ADA** | V3: `<html lang="id">` (`app/layout.tsx:28`) |

Catatan tambahan (bukan dari V2): V3 menambah copyright `© 2026 NetraVision` di bawah kartu login (`page.tsx:132-134`); V2 tidak punya copyright di halaman login.

---

## 2. Header / Topbar (`frontend/includes/header.php`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul tab browser | `header.php:13` | `Mamura Stream - CCTV Streaming Portal` | **BERBEDA** | V3: `NetraVision` (metadata layout) |
| Nama brand | `header.php:81` | `Mamura Stream` | **BERBEDA** | V3: `NetraVision` — sidebar desktop (`AppShell.tsx:96-98`) & topbar mobile (`AppShell.tsx:156-158`) |
| Sub-brand | `header.php:82` | `Portal Monitoring CCTV` (hidden di mobile) | **BERBEDA** | V3 mengganti posisi ini dengan indikator status koneksi `Terhubung` / `Menghubungkan…` (`AppShell.tsx:102-104,159-162`) |
| Logo brand | `header.php:75-79` | Ikon kamera SVG putih di kotak | **BERBEDA** | V3: badge huruf `N` (`AppShell.tsx:93-95,153-155`) |
| Jam digital | `header.php:87` | `00:00:00 UTC` (id `digital-clock`) | **HILANG** | V3 tidak menampilkan jam di shell mana pun |
| Tombol theme toggle | `header.php:89` | `title="Toggle Theme"` | **BERBEDA** | V3 `ThemeToggle`: `title`/`aria-label` = `Mode terang`/`Mode gelap` atau `Beralih ke mode terang`/`Beralih ke mode gelap` (`ThemeToggle.tsx:11-12`); teks "Toggle Theme" tidak dipakai |
| Tombol logout | `header.php:99-105` | Ikon + teks `Logout` | **BERBEDA** | V3: teks `Keluar`, tanpa ikon, di sidebar bawah (`AppShell.tsx:134-139`) & topbar mobile (`AppShell.tsx:167-172`) |
| Guard sesi (redirect ke login bila tanpa token) | `header.php:61-65` | `window.location.href = "login.php"` | **ADA** | V3: halaman terproteksi redirect ke `/login` bila tidak ada user (`app/live/page.tsx:77-80`, via `lib/auth`) |
| Atribut bahasa HTML | `header.php:11` | `<html lang="en">` | **BERBEDA** | V2 inkonsisten (login `id`, header `en`); V3 konsisten `lang="id"` — perubahan ke arah benar |

---

## 3. Sidebar Desktop (`frontend/includes/sidebar.php`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Menu 1 | `sidebar.php:30` | `Semua Kamera` (ikon kamera) | **BERBEDA** | V3: `Live` (ikon mata) — `AppShell.tsx:33-37` |
| Menu 2 | `sidebar.php:42` | `Screen` (ikon layout) | **BERBEDA** | V3: `Monitor` (ikon monitor) — `AppShell.tsx:48-52`; label diganti |
| Menu 3 | `sidebar.php:54` | `Peta Kamera` (ikon pin) | **BERBEDA** | V3: `Peta` (ikon pin) — `AppShell.tsx:43-47`; label dipendekkan |
| Menu 3b | `sidebar.php:66` | `Playback` (ikon play-circle) | **BERBEDA** | V3: `Putar Ulang` (ikon segitiga play) — `AppShell.tsx:38-42`; label diterjemahkan |
| Menu 4 (admin) | `sidebar.php:78` | `Admin Console` (ikon gear, `hidden` kecuali admin) | **BERBEDA** | V3: `Admin` (ikon perisai), `adminOnly` via `isAdminRole()` mencakup `super_admin` — `AppShell.tsx:53-58,70` |
| Urutan menu | `sidebar.php:17-79` | monitor → custom → maps → playback → admin | **BERBEDA** | V3: live → playback → maps → monitors → admin (playback naik ke posisi 2, monitor ke posisi 4) |
| Indikator item aktif | `sidebar.php:31` dkk | `nav-btn-indicator` | **ADA** | V3: bar aksen vertikal di item aktif (`AppShell.tsx:125-130`) — perilaku sama, visual beda |
| Set ikon menu | `sidebar.php` (SVG tiap item) | kamera / layout / pin / play-circle / gear | **BERBEDA** | V3 memakai set ikon 20×20 sendiri: mata / play / pin / monitor / perisai |
| Kartu profil: avatar inisial | `sidebar.php:83` | Inisial `U` (default, id `profile-initial`) | **ADA** | V3: inisial huruf pertama username aktual (`AppShell.tsx:143-145`) |
| Kartu profil: nama | `sidebar.php:85` | `Operator` (default, id `profile-name`) | **ADA** | V3: username aktual (`AppShell.tsx:147-149`) |
| Kartu profil: badge peran | `sidebar.php:86` | `Operator` (id `profile-role`) | **ADA** | V3: role aktual, capitalize (`AppShell.tsx:150-152`) |
| Sidebar disembunyikan di mobile | `sidebar.php:7` | Komentar "hidden on mobile — use bottom nav" | **ADA** | V3: sidebar `hidden md:flex`, mobile pakai tab bar bawah (`AppShell.tsx:76,184-208`) |

---

## 4. Footer (`frontend/includes/footer.php`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Teks copyright / footer | `footer.php` (seluruh file) | — (tidak ada; hanya script JS + tag penutup) | **ADA** | Konsisten: V3 juga tidak punya footer global; copyright hanya ada di halaman login (`© 2026 NetraVision`) |

---

## 5. Navigasi Mobile (`frontend/includes/mobile-nav.php`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Item 1 | `mobile-nav.php:19` | `Live` | **ADA** | `AppShell.tsx:35` — teks identik |
| Item 2 | `mobile-nav.php:28` | `Screen` | **BERBEDA** | V3: `Monitor` (`AppShell.tsx:50`) |
| Item 3 | `mobile-nav.php:37` | `Peta` | **ADA** | `AppShell.tsx:45` — teks identik |
| Item 3b | `mobile-nav.php:46` | `Playback` | **BERBEDA** | V3: `Putar Ulang` (`AppShell.tsx:40`) |
| Item 4 (admin) | `mobile-nav.php:55` | `Admin` (`hidden` kecuali admin) | **ADA** | V3: `Admin`, `adminOnly` (`AppShell.tsx:55,70`) — teks identik |
| Aria-label nav | `mobile-nav.php:11` | `Navigasi utama` | **ADA** | `AppShell.tsx:189` (tab bar mobile) & `:110` (nav desktop) — identik |
| Indikator item aktif | `mobile-nav.php:20` dkk | `mob-nav-dot` | **ADA** | V3: bar aksen horizontal di atas item aktif (`AppShell.tsx:201-206`) — perilaku sama |
| Topbar mobile | (header.php dipakai bersama) | Brand + jam + toggle + Logout | **ADA** | V3 punya topbar khusus mobile: brand + status koneksi + theme toggle + `Keluar` (`AppShell.tsx:150-177`) |

---

## 6. Pagination Bar (`frontend/includes/pagination-bar.php`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Tombol halaman pertama | `pagination-bar.php:23` | `«`, `aria-label="Halaman pertama"` | **BERBEDA** | V3 (`app/admin/streams/page.tsx:419-426`): tombol `«` ada tapi **tanpa aria-label** |
| Tombol halaman sebelumnya | `pagination-bar.php:24` | `‹`, `aria-label="Halaman sebelumnya"` | **BERBEDA** | V3 (`:427-434`): tombol `‹` tanpa aria-label |
| Tombol halaman berikutnya | `pagination-bar.php:27` | `›`, `aria-label="Halaman berikutnya"` | **BERBEDA** | V3 (`:442-449`): tombol `›` tanpa aria-label |
| Tombol halaman terakhir | `pagination-bar.php:28` | `»`, `aria-label="Halaman terakhir"` | **BERBEDA** | V3 (`:450-457`): tombol `»` tanpa aria-label |
| Teks indikator halaman | `pagination-bar.php:32` + JS | `Halaman {n} / {total} · {total} kamera` (`webrtc.js:1318`, `core.js:158`, `admin.js:1750`) | **BERBEDA** | V3: `{n} / {total}` saja (`streams/page.tsx:440-442`) — tanpa kata "Halaman" dan tanpa jumlah item |
| Nomor halaman individual | `pagination-bar.php:26` | Deret `n-2 · n-1 · n · n+1 · n+2` | **HILANG** | V3 hanya punya 4 tombol lompat; tidak merender nomor halaman yang bisa diklik |
| Disembunyikan bila 1 halaman | `pagination-bar.php:22` | class `hidden` default | **ADA** | V3: dirender hanya bila `totalPages > 1` (`streams/page.tsx:418`) — perilaku sama |

---

## 7. Tab Intro Box (`frontend/includes/tab-intro-box.php`)

Komponen generik: ikon + judul + badge opsional + deskripsi + slot aksi HTML.

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Komponen intro per tab | `tab-intro-box.php:29-47` | Box: ikon, `<h2>` judul, badge, `<p>` deskripsi, slot aksi | **BERBEDA** | V3: `SectionTitle` (title + desc + action) di `components/ui.tsx` — **tanpa ikon, tanpa badge** |
| Intro: Live | `views/live-monitor.php:13-14` | Judul `Semua Kamera` / desc `Pantau kamera langsung, saring grup, atur tata letak` | **BERBEDA** | V3 `app/live/page.tsx:125-133`: `<h1>Live</h1>` + `{n} kamera · {n} online` (statistik, bukan deskripsi) |
| Intro: Screen | `views/custom-monitor.php:13-14` | Judul `Screen` / desc `Susun layar pantau sendiri dan simpan grupnya` | **BERBEDA** | V3 `app/monitors/page.tsx:602-604`: `<h1>Monitor tersimpan</h1>` tanpa deskripsi |
| Intro: Peta Kamera | `views/maps.php:18-19` | Judul `Peta Kamera` / desc `Lokasi kamera di peta beserta status koneksinya` | **HILANG** | Halaman peta V3 (`app/maps/page.tsx`) tidak punya judul/deskripsi sama sekali — hanya peta |
| Intro: Playback | `views/playback.php:11-12` | Judul `Playback` / desc `Putar rekaman tersimpan dan lompat ke jam mana pun` | **BERBEDA** | V3 `app/playback/page.tsx:363-365`: `<h1>Putar Ulang</h1>` (+ paragraf deskripsi di `:366`) |
| Intro: Admin Console | `views/admin-console.php:16-17` | Judul `Admin Console` / desc `Kelola kamera, akun, dan integrasi sistem` | **BERBEDA** | V3 `app/admin/streams/page.tsx:277-282`: `SectionTitle title="Kamera" desc="Kelola stream CCTV dan koneksinya"` |
| Slot badge & aksi | `tab-intro-box.php:10-12,36-45` | `tabIntroBadge` (+id) dan `tabIntroActionHtml` | **BERBEDA** | V3: slot `action` didukung `SectionTitle`; **slot badge tidak ada padanannya** |

---

## Ringkasan angka

- **Total detail diinventarisasi: 62**
- **ADA: 22**
- **HILANG: 6** — theme toggle di halaman login; tagline di kartu login; pemisah "atau"; jam digital di topbar; nomor halaman individual di pagination; judul+deskripsi intro di halaman Peta
- **BERBEDA: 34** — didominasi rebrand (Mamura Stream → NetraVision), penerjemahan label (Playback → Putar Ulang, Screen → Monitor, Logout → Keluar, Masuk sebagai tamu → Guest login), ikon/logo baru, teks error login generik, aria-label pagination yang hilang, dan penggantian tab-intro-box dengan SectionTitle tanpa ikon/badge

Temuan lintas-bagian: (1) V3 konsisten memakai `lang="id"` (V2 inkonsisten `id`/`en`) — perbaikan; (2) tombol pagination V3 kehilangan semua `aria-label` aksesibilitas; (3) V3 menambah yang tidak ada di V2: state sibuk `Memeriksa…` di tombol login, copyright `© 2026 NetraVision` di login, indikator status koneksi WebSocket `Terhubung`/`Menghubungkan…` di shell.


---

# Analisa Paritas V2 → V3 — Part B: Halaman Operator

Analisa READ-ONLY. Sumber V2: `/tmp/v2-ref` (Mamura Stream v2.0). Pembanding V3: `~/workspace/netravision/apps/web`.
Status paritas: **ADA** = ada di V3 (disebut lokasi) · **HILANG** = tidak ada padanannya di V3 · **BERBEDA** = ada tapi teks/perilaku/konteks berubah.

Format tanggal/waktu V2 (terverifikasi): jam memakai `toLocaleTimeString('id-ID', {hour12:false})` → `14.30.05` (titik dua-digit, **pemisah titik**, zona waktu lokal browser); jam-menit → `14.30`. Tanggal dari API berupa string `YYYY-MM-DD` mentah. Di player eksternal (`frontend/playback.php`), jam diformat manual `duaAngka()` → `HH:MM:SS` dengan **titik dua** (zona lokal).

---

## B1. Live Monitor

V2: `/tmp/v2-ref/frontend/views/live-monitor.php` (+ tile/modal JS di `assets/js/modules/webrtc.js`).
V3: `apps/web/app/live/page.tsx` (+ `components/CameraTile.tsx`, `components/FocusModal.tsx`).

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul halaman | live-monitor.php L13 | `Semua Kamera` | **BERBEDA** | V3 `live/page.tsx`: `Live` |
| Sub-judul/deskripsi | live-monitor.php L14 | `Pantau kamera langsung, saring grup, atur tata letak` | **HILANG** | V3 hanya menampilkan `{n} kamera` + `{n} online` |
| Ikon header (tab-intro-box 'camera') | includes/tab-intro-box.php | Ikon kamera SVG + aksen | **HILANG** | V3 tidak memakai pola tab-intro-box |
| Filter grup (dropdown) | live-monitor.php L29 `#viewer-group-filter` | Opsi default `All Groups` | **HILANG** | V3 tidak punya filter grup; diganti filter status segmented |
| Label `Grid` | live-monitor.php L36 | `Grid` | **BERBEDA** | V3: hanya `aria-label="Tata letak grid"`, teks visible hilang |
| Grid picker 1x1–4x4 | live-monitor.php L38–41 | `1x1` `2x2` `3x3` `4x4`, default `3x3` | **BERBEDA** | V3 `live/page.tsx` GRID_OPTS: label `1×1`–`4×4` (tanda ×), default **4 kolom**, tiap tombol punya `title="Grid {label}"` |
| Empty state | live-monitor.php L62–65 | Judul `No Feeds Available` / `Belum ada kamera untuk akun Anda. Hubungi administrator.` | **BERBEDA** | V3: `Belum ada kamera` / `Tidak ada kamera yang cocok` + hint `Tambahkan kamera lewat halaman Admin…` / `Coba ubah kata kunci atau filter status.` |
| Paginasi (first/prev/next/last) | includes/pagination-bar.php | aria-label `Halaman pertama` / `Halaman sebelumnya` / `Halaman berikutnya` / `Halaman terakhir` | **HILANG** | V3 tidak ada paginasi; semua tile dirender sekaligus |
| Indikator halaman | webrtc.js L1333 | `Halaman {n} / {m} · {total} kamera` | **HILANG** | — |
| Tile: badge kode kamera | webrtc.js L1344 | `CAM_001` (format `CAM_` + id 3 digit) | **HILANG** | V3 tidak menampilkan kode kamera |
| Tile: pill status | webrtc.js L1349–1352 | `ONLINE` (dot emerald) / `OFFLINE` (dot rose) | **BERBEDA** | V3: hanya status dot + nama; teks `Online`/`Offline` hanya ada di filter segmented & footer FocusModal (`● Online`/`● Offline`); badge `LIVE` (dot merah + teks) hanya muncul saat video sedang playing — `CameraTile.tsx` |
| Tile: nama kamera | webrtc.js L1354–1356 | UPPERCASE | **BERBEDA** | V3: case normal |
| Tile: badge REC/LOSS | webrtc.js L1361–1365 | `REC` (online) / `LOSS` (offline) | **HILANG** | — |
| Tile overlay bawah: telemetri | webrtc.js L1237–1255 | Label `fps`/`res`/`codec`, nilai `30.0` / `1080p` / `H264` | **HILANG** | — |
| Tile: tombol expand | webrtc.js L1257–1262 | Teks `Buka`, `title`/`aria-label="Buka Kamera"` | **BERBEDA** | V3: dua tombol ikon tanpa teks — fullscreen (`title="Layar penuh"`, `aria-label="Layar penuh {nama}"`) dan expand (`aria-label="Perbesar {nama}"`) — `CameraTile.tsx` |
| Tile: overlay error stream | webrtc.js L767–783 | `Gagal Konek ke RTSP` / detail `RTSP / WebRTC gagal` / tombol `Coba Hubungkan Paksa` | **BERBEDA** | V3: `Offline` / `Kamera tidak terjangkau`, atau `Gagal memuat` / `Stream tidak dapat diputar`; tanpa tombol retry — `CameraTile.tsx` |
| Sidebar: teks status | webrtc.js L34, L369 | `Live` / `Offline` (+ badge count `0/0`) | **HILANG** | V3 tidak punya sidebar daftar kamera |
| Popup modal: badge LIVE | webrtc.js L1575 | `● LIVE` (hidden di mobile) | **HILANG** | — |
| Popup: metadata bar | webrtc.js L1603–1609 | `REC` + dot merah, `CAM_000`, nama UPPERCASE (`LOADING...` saat muat) | **HILANG** | V3 FocusModal: dot status + nama + subteks `Stream utama, {brand}` / `Stream utama` |
| Popup: status koneksi | webrtc.js L1614, L1892 | `RTSP ONLINE` / `RTSP OFFLINE` | **BERBEDA** | V3: `● Online` / `● Offline` (footer) |
| Popup: status cluster | webrtc.js L2497 | `SOME ONLINE` / `ALL OFFLINE` | **HILANG** | — |
| Popup kontrol: tooltip | webrtc.js L1546–1573 | `Close (Esc)`, `Kamera Sebelumnya (←)`, `Kamera Berikutnya (→)`, `Play/Pause (Spasi)`, `Mute/Unmute (M)`, `Ganti Kualitas (LQ/HQ)` (label `LQ`/`HQ`), `Putar Orientasi Layar (R)`, `Mode Teater (T)`, `Layar Penuh (F)` | **HILANG** | V3: kontrol video bawaan browser + tombol `Snapshot`; tanpa quality/orientation/theater/prev-next |
| Popup footer: tombol `Peta` | webrtc.js L1621 | `Peta` (ikon pin) | **HILANG** | — |
| Popup footer: tombol `Tutup` | webrtc.js L1627 | `Tutup` | **BERBEDA** | V3: tombol X (`aria-label="Tutup"`), klik backdrop, atau Esc; ada hint `Tekan ESC untuk menutup` |
| Overlay kiri-atas disembunyikan untuk guest | webrtc.js L1340 | (role guest → tanpa badge CAM/status/nama) | **HILANG** | V3 tidak punya varian guest untuk overlay tile |
| _(tambahan V3)_ filter status | — | — | — | V3: segmented `Semua`/`Online`/`Offline` + angka count |
| _(tambahan V3)_ pencarian | — | — | — | V3: `Cari kamera…` |
| _(tambahan V3)_ indikator WebSocket | — | — | — | V3: `Real-time` / `Menghubungkan…` (`title="WebSocket terhubung"` / `"Menghubungkan…"`) |
| _(tambahan V3)_ muat ulang & error | — | — | — | V3: tombol `Muat ulang`; error `Gagal memuat kamera` + `Coba lagi` |
| _(tambahan V3)_ FocusModal | — | — | — | V3: tombol `Snapshot`; gagal: `Gagal memutar stream utama` / `Coba tutup dan buka kembali`, `Kamera offline` / `Kamera tidak terjangkau saat ini` |

---

## B2. Playback (dalam aplikasi)

V2: `/tmp/v2-ref/frontend/views/playback.php`.
V3: `apps/web/app/playback/page.tsx`.

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul halaman | views/playback.php L12 | `Playback` | **BERBEDA** | V3: `Putar Ulang` |
| Deskripsi | views/playback.php L13 | `Putar rekaman tersimpan dan lompat ke jam mana pun` | **BERBEDA** | V3: `Pilih kamera dan tanggal, lalu muat linimasa rekaman.` |
| Filter grup | views/playback.php L25 | `All Groups` | **HILANG** | — |
| Grid picker | views/playback.php L39–43 | `2x2` `2x2`→opsi `2x2`/`3x3`/`4x4`, default `3x3` | **BERBEDA** | V3: hanya di mode Multi — `Grid:` + opsi `2×2`/`3×3`/`4×4`, default **2 kolom** |
| Empty state | views/playback.php L56–57 | `Belum Ada Rekaman` / `Belum ada kamera dengan rekaman tersimpan` | **BERBEDA** | V3: `Belum ada kamera.` (single) / `Pilih minimal satu kamera untuk memutar ulang.` (multi) |
| Teks saat memuat daftar | views/playback.php JS L254–256 | `Memuat daftar kamera...` | **BERBEDA** | V3 per-panel: `Menyiapkan linimasa…` / `Memuat…`; tanpa teks setingkat halaman |
| Tile: badge rekaman | views/playback.php L272–275 | `ADA REKAMAN` (emerald) / `KOSONG` (slate) | **HILANG** | V3 tidak menandai kamera mana yang punya rekaman (mode multi hanya menunjukkan dot online) |
| Tile: nama + grup | views/playback.php L280–283 | Nama kamera + `group_name` | **BERBEDA** | V3: hanya nama kamera (tanpa grup) |
| Modal: judul = nama kamera, sub = grup | views/playback.php JS L277–279 | — | **BERBEDA** | V3: panel per kamera berjudul nama saja; tanpa grup |
| Modal: tombol tutup | views/playback.php L76 | `title="Tutup (Esc)"` | **HILANG** | V3 tanpa modal |
| Loading video | views/playback.php L98 | `Memuat rekaman...` | **BERBEDA** | V3: `Memuat video…` (saat video dimuat) |
| Pesan tak ada rekaman (kamera) | views/playback.php L102/L305 | `Belum ada rekaman untuk kamera ini` | **BERBEDA** | V3 (timeline kosong): `Tidak ada rekaman pada tanggal ini` |
| Label `Tanggal` | views/playback.php L110 | `Tanggal` | **ADA** | V3 `playback/page.tsx`: label `Tanggal` di atas `<input type="date">` |
| Pemilih tanggal | views/playback.php L296 | Select berisi `{YYYY-MM-DD} ({n} segment)` | **BERBEDA** | V3: `<input type="date">` bebas (max = hari ini, default hari ini); tanpa daftar tanggal tersedia / jumlah segmen |
| Info jumlah tanggal | views/playback.php L310 | `{n} tanggal tersedia` | **HILANG** | — |
| Tombol transport | views/playback.php L116–118 | `← 30s` (`Mundur 30 detik`), `Play / Pause`, `30s →` (`Maju 30 detik`) | **HILANG** | V3: kontrol bawaan `<video>`; tanpa lompat ±30 detik kustom |
| Jam berjalan | views/playback.php L121/L180 | `--:--:--` → format `14.30.05` (id-ID 24-jam, zona lokal) | **HILANG** | V3 hanya menampilkan jam per segmen `14.30` (HH:MM) |
| Label tanggal di bawah jam | views/playback.php L122 | `{YYYY-MM-DD}` | **HILANG** | — |
| Timeline scrub | views/playback.php L126–132 | Bar rekaman hijau + tick per jam (`14.30`) + playhead merah; batas `00:00` / `23:59`; ketuk/geser (Pointer Events) | **BERBEDA** | V3: tiap segmen adalah **tombol** di bar (tanpa scrub bebas, tanpa playhead, tanpa tick jam); tanpa batas 00:00/23:59 |
| Hint timeline | views/playback.php L131 | `Klik timeline untuk melompat ke jam tertentu` | **BERBEDA** | V3: `Klik salah satu segmen pada linimasa untuk memutar.` |
| Tooltip bar rekaman | views/playback.php L351 | `{14.30.05} - {14.30.05}` | **BERBEDA** | V3: `title="{14.30} – {14.30}[ · ada event]"`, `aria-label="Putar segmen {14.30}"` |
| Info rekaman | views/playback.php L338–339 | `{n} rekaman - total {n} menit` | **BERBEDA** | V3: badge `{n} segmen`; total menit hilang |
| Pesan error | views/playback.php L305/L321/L332/L334/L432/L437 | `Belum ada rekaman untuk kamera ini` / `Belum ada rekaman pada tanggal ini` / `Gagal memuat tanggal rekaman` / `Gagal memuat timeline` / `Tidak ada rekaman berisi setelah titik ini` / `Rekaman pada jam ini kosong atau rusak` | **BERBEDA** | V3: `Gagal memuat linimasa`, `Gagal memuat URL playback`, `Terjadi kesalahan. Coba muat ulang.`, `Linimasa rekaman tersedia mulai Fase 3.` (404) |
| Tombol unduh | — (tidak ada di V2) | — | — | **TAMBAHAN V3**: tombol `Unduh` / `Mengunduh…`; nama file `rekaman-{id}-{ISO}.mp4` |
| _(tambahan V3)_ mode multi | — | — | — | V3: toggle `Multi kamera` / `Multi aktif`, label `Kamera ({n} dipilih)` |
| _(tambahan V3)_ tombol Muat panel | — | — | — | V3: `Muat` / `Memuat…` per panel |
| _(tambahan V3)_ badge Event | — | — | — | V3: badge `Event` pada segmen ber-event (tak ada di V2) |

---

## B3. Playback Eksternal (API key, tanpa login)

V2: `/tmp/v2-ref/frontend/playback.php` (URL `?key=...&camera=...`).
V3: **tidak ada padanannya** — `apps/web/app/embed/page.tsx` hanya memutar **live** via key, bukan rekaman.

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul | frontend/playback.php L17/L74 | `Rekaman CCTV` | **HILANG** | V3 embed = live player, bukan playback |
| Subjudul | frontend/playback.php L75/L146 | `Memuat...` → `Kamera {n} dari {total}` | **HILANG** | — |
| Lencana tanggal | frontend/playback.php L77 | `{YYYY-MM-DD}` | **HILANG** | — |
| Pemilih kamera (>1 kamera) | frontend/playback.php L81/L158 | Label `Kamera`; tombol `{n}. {nama}`; yang aktif di-highlight | **HILANG** | V3 embed hanya pesan fallback `Kamera ?camera={n} tidak tersedia untuk kunci ini — menampilkan semua kamera.` |
| Pemilih tanggal | frontend/playback.php L136 | `{YYYY-MM-DD} ({n} segmen)` | **HILANG** | — |
| Kontrol | frontend/playback.php L95 | `← 30d` (`Mundur 30 detik`), `Putar`/`Jeda`, `30d →` (`Maju 30 detik`) | **HILANG** | — |
| Jam + info segmen | frontend/playback.php L99–100/L132–135 | `--:--:--` → `HH:MM:SS` (titik dua, zona lokal); `{n} segmen` | **HILANG** | — |
| Penanda timeline | frontend/playback.php L103–105 | `00:00` `12:00` `23:59`; ketuk/geser | **HILANG** | — |
| Loading | frontend/playback.php L85 | `Memuat video...` | **HILANG** | V3 embed: `Memuat…` (sesi live) |
| Error: tak ada rekaman | frontend/playback.php L88–89 | `Tidak ada rekaman` + `Belum ada rekaman untuk kamera ini.` / `Tidak ada segmen pada tanggal ini.` / `Video tidak dapat diputar di peramban ini.` | **HILANG** | — |
| Error: akses | frontend/playback.php L126–127/L153 | `Akses ditolak` / `Parameter key wajib disertakan.`; `Tidak dapat memuat` + pesan | **BERBEDA** | V3 embed: `Parameter ?key= tidak …` (halaman live) |
| Footer retensi | frontend/playback.php L108 | `Rekaman disimpan terbatas sesuai kebijakan retensi.` | **HILANG** | — |

---

## B4. Maps

V2: `/tmp/v2-ref/frontend/views/maps.php`.
V3: `apps/web/app/maps/page.tsx`.

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul halaman | maps.php L20 | `Peta Kamera` | **HILANG** | V3 tanpa judul halaman |
| Deskripsi | maps.php L21 | `Lokasi kamera di peta beserta status koneksinya` | **HILANG** | — |
| Badge jumlah | maps.php L22–23/L283 `#map-total-badge` | Angka = jumlah kamera **terpetakan** | **BERBEDA** | V3: badge angka per seksi — `Di peta` dan `Belum dipetakan` |
| Search | maps.php L37 `#map-search-input` | Placeholder `Cari kamera...` (filter nama/grup/koordinat) | **BERBEDA** | V3: `Cari CCTV…` (filter nama saja) |
| Loading sidebar | maps.php L48 | `Loading...` (+ spinner) | **BERBEDA** | V3: overlay `Memuat peta…` |
| Legenda | maps.php L54–56 | `Kamera Aktif` (dot emerald) / `Kamera Offline` (dot rose) | **BERBEDA** | V3: `Online` / `Offline` (dot ok-400/bad-400) |
| Item sidebar | maps.php L436–442 | Dot (emerald pulse/rose) + nama + **koordinat** (`select-all`, truncate) | **BERBEDA** | V3: dot + nama + ikon pin (klik → `flyTo` zoom 15); koordinat tidak ditampilkan |
| Header grup | maps.php L429–432 | `📁 {nama_grup}` + badge jumlah | **HILANG** | V3 mengelompokkan jadi seksi `Belum dipetakan` / `Di peta`, bukan per grup kamera |
| Search tanpa hasil | maps.php L416–419 | `Kamera tidak ditemukan` | **BERBEDA** | V3: `Tidak ada yang cocok.` |
| Kosong (tak ada terpetakan) | maps.php L290–293 | `TIDAK ADA KAMERA TERPETAKAN` / `Gunakan menu Admin Console untuk menambahkan koordinat GPS pada kamera Anda.` | **BERBEDA** | V3: `Belum ada kamera yang dipetakan.` (seksi Di peta) / `Semua kamera sudah punya posisi.` (seksi Belum dipetakan) |
| Error muat | maps.php L296–300 | `Gagal memuat data CCTV.` + pesan error | **BERBEDA** | V3: error inline generik (pesan API) |
| Marker | maps.php L356–377 | Pin 34px `#10b981`/`#ef4444`, border putih 3px, **ikon kamera SVG**, badge jumlah cluster (lingkaran merah) | **BERBEDA** | V3: dot 20px `#34d399`/`#f87171`; tanpa ikon kamera, tanpa cluster |
| Clustering | maps.php L309–355 | Cluster otomatis ≤50px; popup `Cluster: {n} Kamera` | **HILANG** | V3 tidak ada clustering |
| Popup header | maps.php L387–391 | `Cluster: {n} Kamera` / `Lokasi Kamera` | **HILANG** | V3 popup: nama + brand + status saja |
| Popup baris kamera | maps.php L370–386 | Nama + status `ONLINE`/`OFFLINE` (uppercase, emerald-700/rose-600) + tombol `👁️ View` | **BERBEDA** | V3: `● Online` / `● Offline` + tombol `Lihat live` (buka FocusModal) |
| Popup: lihat semua live | maps.php L395–400 | `Lihat Semua Live Feed` | **HILANG** | — |
| Koordinat default | maps.php L289 | Jakarta `-6.208763, 106.845599` bila kosong | **BERBEDA** | V3: `[-2.5, 118]` zoom 5 (Indonesia) |
| Zoom awal/ikuti batas | maps.php L196–211 | `fitBounds` padding 50, maxZoom 15; 1 kamera → zoom 14 | **BERBEDA** | V3: `fitBounds(...).pad(0.25)` sekali; klik item → `flyTo` zoom 15 |
| _(tambahan V3)_ drag marker admin | — | — | — | V3: `Seret marker untuk memindahkan posisi kamera`; gagal: `Gagal menyimpan posisi {nama}: …` |
| _(tambahan V3)_ tombol Tengah peta | — | — | — | V3 (admin, seksi Belum dipetakan): `Tengah peta` + hint `Geser peta ke lokasi kamera, lalu tekan "Tengah peta".` |
| _(tambahan V3)_ `title` marker | — | — | — | V3: `title` = nama kamera (tooltip bawaan browser) |

---

## B5. Custom Monitor → Monitors

V2: `/tmp/v2-ref/frontend/views/custom-monitor.php` (+ `assets/js/modules/admin.js`).
V3: `apps/web/app/monitors/page.tsx`.

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul halaman | custom-monitor.php L14 | `Screen` | **BERBEDA** | V3: `Monitor tersimpan` |
| Deskripsi | custom-monitor.php L15 | `Susun layar pantau sendiri dan simpan grupnya` | **BERBEDA** | V3 (empty): `Buat tata letak kisi kamera favoritmu — tersimpan di perangkat ini.` |
| Tombol Fullscreen (header) | custom-monitor.php L18–24 | `Fullscreen` (ikon expand) | **BERBEDA** | V3: tombol `Penuh` (`title`/`aria-label="Layar penuh"`) hanya di tampilan layout terbuka |
| Tombol keluar fullscreen | custom-monitor.php L143–148 | `aria-label="Keluar fullscreen"`, teks `Keluar Fullscreen` | **HILANG** | V3 memakai fullscreen API bawaan browser tanpa tombol keluar kustom |
| Panel `Custom Playlist` | custom-monitor.php L28–29 | `Custom Playlist` / `Pilih dan susun kamera aktif untuk layar monitoring personal` | **HILANG** | V3: form `Monitor baru` / `Ubah monitor` |
| Label `Tipe Tampilan` | custom-monitor.php L34/L43–44 | Opsi `Kustom (Pilih Manual)` / `Per Grup Kamera` | **BERBEDA** | V3: toggle `Grup` di tampilan layout (mode grup = grup admin); tanpa pemilih mode di sidebar |
| Label `Select & Sort Feeds` | custom-monitor.php L55 | `Select & Sort Feeds` | **HILANG** | V3: `Pilih kamera ({n})` + hint `Urutan bisa digeser` |
| Tombol `Save & Load Playlist` | custom-monitor.php L60–62 | `Save & Load Playlist` (uppercase, tracking-wider) | **HILANG** | V3: tombol `Simpan` (disabled bila nama kosong / tanpa kamera) + `Batal` |
| Label `Pilih Grup Kamera` | custom-monitor.php L67 | `Pilih Grup Kamera` | **HILANG** | — |
| Panel `Screen Groups` | custom-monitor.php L75–76 | `Screen Groups` / `Simpan dan muat susunan kamera Anda` | **BERBEDA** | V3: daftar layout berupa kartu accordion + MiniPreview |
| Label `Nama Grouping Baru` | custom-monitor.php L80–83 | Placeholder `e.g., Lobby & Parkir`; tombol `Simpan` | **BERBEDA** | V3: label `Nama monitor`, placeholder `cth. Lantai 1`, tombol `Simpan` di form |
| Label `Daftar Grouping` | custom-monitor.php L87 | `Daftar Grouping` | **HILANG** | — |
| Baris grouping tersimpan | admin.js L2049–2051 | `{nama}` / `{n} Kamera · Grid {n}x{n}`; hapus `title="Hapus Grouping"` | **BERBEDA** | V3: ringkasan `{n} kamera · {n} online · {n} kolom` + MiniPreview; aksi `Buka`/`Ubah`/`Hapus` muncul setelah expand |
| Validasi: nama kosong | admin.js L1987 | Alert `Harap masukkan nama grouping terlebih dahulu.` | **HILANG** | V3: validasi inline — tombol `Simpan` disabled |
| Konfirmasi: nama duplikat | admin.js L2006 | `Grouping dengan nama "{n}" sudah ada. Apakah Anda ingin menimpanya?` | **HILANG** | V3 selalu membuat layout baru (id randomUUID) |
| Alert: simpan sukses | admin.js L2014 | `Grouping "{n}" berhasil disimpan!` | **HILANG** | V3: tanpa notifikasi; langsung kembali ke daftar |
| Alert: muat sukses | admin.js L2076 | `Grouping "{n}" berhasil dimuat!` | **HILANG** | V3: langsung membuka layout |
| Konfirmasi: hapus | admin.js L2079 | `Apakah Anda yakin ingin menghapus grouping "{n}"?` | **BERBEDA** | V3: `Hapus monitor "{n}"?` (window.confirm) |
| Daftar kosong | admin.js L2033 | `Belum ada grouping disimpan.` | **BERBEDA** | V3: `Belum ada monitor tersimpan` + tombol `Buat monitor pertama` |
| Empty state grid | custom-monitor.php L131–133 | `Playlist Empty` / `Centang minimal satu kamera di panel kiri untuk mulai monitoring.` | **BERBEDA** | V3: `Tidak ada kamera yang cocok — mungkin kamera sudah dihapus.` |
| Filter grup grid | custom-monitor.php L104 | `All Groups` | **HILANG** | — |
| Grid picker | custom-monitor.php L111–116 | `1x1`–`4x4`, default `3x3` | **BERBEDA** | V3: `Jumlah kolom` tombol angka 1–4, default **2** |
| Paginasi custom | pagination-bar.php (id `custom-*`) | aria-label `Halaman pertama` dkk. | **HILANG** | — |
| Penyimpanan | admin.js L1670/L2003 | localStorage per-akun (`cctv_custom_playlist`, `cctv_custom_screens`, …) | **BERBEDA** | V3: localStorage key `nv_monitors` (tidak per-akun) |
| _(tambahan V3)_ tombol Baru | — | — | — | V3: `Baru` (+ ikon plus) |
| _(tambahan V3)_ tampilan layout | — | — | — | V3: tombol kembali (`aria-label="Kembali ke daftar monitor"`), sub `{n} kamera · {n} kolom[ · mode grup]` |
| _(tambahan V3)_ mode grup | — | — | — | V3: `Memuat grup…`; error + `Mode grup membutuhkan akses admin.`; seksi `Tanpa grup`; kosong `Tidak ada grup kamera untuk layout ini.`; tiap seksi `{n} kamera` |
| _(tambahan V3)_ reorder | — | — | — | V3: tombol `Geser {nama} ke atas/bawah` (aria-label), disabled di ujung |
| _(tambahan V3)_ form kosong | — | — | — | V3: `Belum ada kamera.` |

---

## Ringkasan hitungan

| Halaman | Detail diinventarisasi | ADA | HILANG | BERBEDA |
|---|---|---|---|---|
| B1 Live Monitor | 29 (25 V2 + 4 tambahan V3) | 0 | 15 | 10 |
| B2 Playback (dalam aplikasi) | 28 (23 V2 + 5 tambahan V3) | 1 | 7 | 15 |
| B3 Playback eksternal (API key) | 12 (12 V2) | 0 | 11 | 1 |
| B4 Maps | 22 (18 V2 + 4 tambahan V3) | 0 | 6 | 12 |
| B5 Custom Monitor → Monitors | 29 (24 V2 + 5 tambahan V3) | 0 | 12 | 12 |
| **Total** | **120** (102 V2 + 18 tambahan V3) | **1** | **51** | **50** |

(tambahan V3 = fitur baru yang tidak ada di V2, tidak dihitung sebagai HILANG/BERBEDA; 1+51+50 = 102 detail V2)

**Temuan terbesar:**
1. **Playback eksternal API-key hilang total** — V2 `frontend/playback.php` (player rekaman satu-URL tanpa login: pilih tanggal, ±30 dtk, timeline, info segmen) tidak punya padanan di V3; `embed/page.tsx` hanya live.
2. **Paginasi hilang di semua halaman operator** — V3 me-render semua tile sekaligus.
3. **Popup kamera V2 (metadata REC/CAM_###/RTSP ONLINE, kontrol LQ/HQ, orientasi, teater, tombol Peta, prev/next)** diganti FocusModal minimalis (nama + Snapshot + ● Online).
4. **Telemetri tile** (`fps 30.0 / res 1080p / codec H264`) dan badge `REC`/`LOSS`/`CAM_###` hilang; V3 hanya dot status + nama + badge `LIVE` saat playing.
5. **Timeline playback** berubah paradigma: V2 scrub bebas + playhead + tick per jam + jam berjalan `14.30.05`; V3 tombol per segmen + jam `14.30` + **tombol Unduh** (fitur baru).
6. **Alert/confirm kustom monitor** (`Harap masukkan nama grouping…`, duplikat, sukses simpan/muat) hilang — V3 pakai validasi inline (tombol disabled); hanya konfirmasi hapus yang tersisa (`Hapus monitor "{n}"?`).
7. **Maps**: clustering + popup multi-kamera (`Cluster: {n} Kamera`, `👁️ View`, `Lihat Semua Live Feed`) hilang; V3 menambah drag-marker admin + `Tengah peta` (fitur baru).
8. **Satu-satunya ADA murni**: label `Tanggal` di halaman playback.


---

# Analisa Paritas V2 → V3 — PART C: Halaman Admin

Analisa READ-ONLY. Sumber V2: `/tmp/v2-ref/frontend/views/admin-console.php` (1008 baris), `/tmp/v2-ref/frontend/views/modals.php` (897 baris). Pembanding V3: `~/workspace/netravision/apps/web/app/admin/*`.

**Catatan metodologi:**
- Tidak ada satu pun `confirm()` / teks konfirmasi di kedua file V2 — semua dialog konfirmasi (hapus stream/user/key/log) di-render dari file JS di luar cakupan. Kolom "Status V3" untuk konfirmasi memakai teks `ConfirmModal` V3 sebagai referensi silang saja.
- V2 **tidak memiliki** tab/halaman: Grup tersendiri, Drive/Penyimpanan, dan Dasbor admin. Grup di V2 dikelola lewat modal user (field Grup Pengguna), modal Rename Group, dan tab Camera Access. Ketiga halaman V3 (Dasbor, Grup, Drive, Penyimpanan) adalah fitur baru — dirangkum di bagian "Fitur baru di V3", bukan dihitung sebagai item paritas.
- Status: **ADA** (ada di V3, lokasi disebut) / **HILANG** (tidak ada di V3) / **BERBEDA** (ada tapi berbeda, dijelaskan).

---

## 1. Navigasi tab + intro (admin-console.php L13–115)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 1 | Judul + deskripsi intro | admin-console.php L17–24 | "Admin Console" / "Kelola kamera, akun, dan integrasi sistem" | BERBEDA | V3 tak punya intro box; nav berupa underline tabs di `app/admin/layout.tsx`: Dasbor, Kamera, Pengguna, Grup, API Key, Iklan, Drive, Penyimpanan, Scanner, Akses |
| 2 | Tab Camera Streams + badge hitung | L31–43 | "Camera Streams" + badge `admin-subtab-streams-badge` | BERBEDA | V3 label "Kamera", tanpa badge hitung |
| 3 | Tab Console Users + badge | L46–58 | "Console Users" + badge | BERBEDA | V3 "Pengguna", tanpa badge |
| 4 | Tab Camera Access + badge | L61–73 | "Camera Access" + badge | BERBEDA | V3 "Akses", tanpa badge |
| 5 | Tab Camera Scanner | L76–86 | "Camera Scanner" | BERBEDA | V3 "Scanner" |
| 6 | Tab Ad Space Config | L89–99 | "Ad Space Config" | BERBEDA | V3 "Iklan" |
| 7 | Tab API Integration + badge | L102–114 | "API Integration" + badge | BERBEDA | V3 "API Key", tanpa badge |

## 2. TAB Camera Streams (admin-console.php L117–275)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 8 | Judul + deskripsi section | L121–124 | "Camera Streams" / "Kelola kamera terdaftar, alamat RTSP, dan status koneksi" | BERBEDA | V3 `app/admin/streams/page.tsx`: "Kamera" / "Kelola stream CCTV dan koneksinya" |
| 9 | Placeholder search | L136–140 | "Search camera name or RTSP..." | BERBEDA | V3 field "Cari kamera", placeholder "Nama kamera…"; tidak menyebut RTSP |
| 10 | Filter grup | L146–150 | "All Groups" | ADA | V3: field "Grup", opsi "Semua grup" (`streams/page.tsx`) |
| 11 | Filter status | L164–169 | "All Statuses" / "Connected (Online)" / "Disconnected (Offline)" | ADA | V3: "Semua status" / "Online" / "Offline" |
| 12 | Tombol clear filter | L183–186 | "✕ Clear" | ADA | V3 "Bersihkan", sama-sama hanya tampil saat filter aktif |
| 13 | Tombol bulk set koordinat | L189–194 | "Set Coords (N)" | ADA | V3 "Set koordinat (N)" |
| 14 | Tombol bulk hapus | L197–202 | "Delete Selected (N)" | ADA | V3 "Hapus terpilih (N)" |
| 15 | Tombol tambah kamera | L205–210 | "Add Camera" | ADA | V3 "+ Tambah Kamera" |
| 16 | Badge status filter aktif | L215–220 | teks status filter (diisi JS) | BERBEDA | V3 menampilkan badge "{N} dari {M}" |
| 17 | Header tabel | L229–241 | No / Camera Name / Group / Coordinates / RTSP Endpoint / Status / Record / Actions | BERBEDA | V3 bukan tabel: daftar baris dengan badge nama, Online/Offline, brand, mode penyimpanan ("Lokal"/"Google Drive"/"Keduanya"), "Rekaman: Aktif/Mati"; aksi Bagikan/Ubah/Hapus. Kolom Group, Coordinates, RTSP Endpoint tidak tampil sebagai kolom |
| 18 | Teks loading | L245–254 | "Loading camera directory..." | BERBEDA | V3 spinner tanpa teks |
| 19 | Pagination | L260–274 | pagination bar (First/Prev/daftar halaman/Next/Last via pagination-bar.php) | BERBEDA | V3 tombol « ‹ `{cur} / {total}` › » + label "Pilih semua di halaman ini" |

## 3. TAB Console Users (admin-console.php L277–301)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 20 | Judul + deskripsi | L282–285 | "Console Users" / "Kelola akun pengguna, peran, dan grupnya" | BERBEDA | V3 `app/admin/users/page.tsx`: "Pengguna" / "Kelola akun dan hak akses kamera" |
| 21 | Tombol tambah user | L287–293 | "Add User" | ADA | V3 "+ Tambah Pengguna" |
| 22 | Header tabel | L297–305 | No / Username / Role / Iklan / Actions | BERBEDA | V3 daftar baris: username, badge peran, badge "Iklan: Ya/Tidak", "Dibuat oleh: {nama}/—", aksi "Akses Kamera"/"Ubah"/"Hapus" (aksi "Akses Kamera" tidak ada di V2) |
| 23 | Teks loading | L306–315 | "Loading user accounts..." | BERBEDA | V3 spinner; empty-state V3: "Belum ada pengguna." |

## 4. TAB Camera Access (admin-console.php L304–358)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 24 | Judul + deskripsi | L307–310 | "Camera Access" / "Atur kamera mana yang dapat dilihat tiap grup dan akun" | BERBEDA | V3 `app/admin/access/page.tsx`: "Akses Kamera" / "Atur kamera mana yang dapat dilihat tiap akun" |
| 25 | Tombol tambah akses | L312–317 | "Add Access" | HILANG | V3 tak ada tombol tambah akses global; akses diatur via tombol "Kelola" per baris |
| 26 | Toggle arah | L318–326 | "Per Grup" (default aktif) / "Per Kamera" | BERBEDA | V3 segmented "Per akun" (default) / "Per kamera"; arah "Per Grup" hilang |
| 27 | Placeholder search | L330–334 | "Cari…" | ADA | V3 placeholder "Cari…" |
| 28 | Header tabel | L341–344 | No / Account / Role / Cameras / Actions | BERBEDA | V3 mode akun: Akun/Peran/Aksi (tanpa kolom jumlah kamera); mode kamera: Kamera/Status/"Akun berakses"/Aksi |
| 29 | Teks loading | L345–353 | "Memuat…" | BERBEDA | V3 spinner |

## 5. TAB Camera Scanner (admin-console.php L360–464)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 30 | Judul + deskripsi | L363–366 | "Camera Scanner" / "Parameter scan jaringan lokal untuk kamera RTSP" | BERBEDA | V3 `app/admin/scanner/page.tsx`: "Camera Scanner" / "Pindai subnet jaringan lokal untuk menemukan kamera (maks 256 host)" |
| 31 | Field IP Subnet | L370–374 | Label "IP Subnet Range (CIDR)", required, default `192.168.1.0/24`; hint "Contoh: 192.168.1.0/24, 10.0.0.0/24" | BERBEDA | V3 label "IP Subnet (CIDR)", hint "cth: 192.168.1.0/24", placeholder "192.168.1.0/24" |
| 32 | Field port | L377–381 | Label "Target Port (RTSP)", required, default `554`, min 1 max 65535 | BERBEDA | V3 label "Port RTSP"; batasan min/max tidak terlihat di UI |
| 33 | Field username | L384–388 | Label "Default Username", required, default `admin` | ADA | V3 label "Username", default "admin" |
| 34 | Field password | L391–395 | Label "Default Password", required, default `admin`, type=text | BERBEDA | V3 label "Password", type=password, default kosong |
| 35 | Field codec | L398–403 | Label "Codec / Stream Path", required, default `H.264`; hint "Suffix URL RTSP (e.g. H.264, stream1)" | HILANG | V3 mengganti dengan select "Merek" (13 brand: Otomatis, Hikvision, Dahua/Amcrest, Uniview, Hanwha/Samsung, Axis, TP-Link Vigi, Reolink, Ezviz, Foscam, Milesight, Panasonic) |
| 36 | Field koordinat default | L406–412 | Label "Default Coordinates (lat, lon)", placeholder "-6.2095, 106.8456" | HILANG | V3 tak ada di scanner; koordinat diisi di modal tambah/ubah kamera |
| 37 | Tombol scan | L416–421 | "Scan Network" | ADA | V3 "Scan Network" / "Memindai…" |
| 38 | Progress bar | L424–433 | "Scanner Idle" / "0%" + bar | BERBEDA | V3 "Memindai {subnet}…" + bar animasi tanpa persen |
| 39 | Judul hasil | L439–443 | "Discovered Camera Feeds" / "Kamera yang terdeteksi dari hasil scan jaringan" | BERBEDA | V3 "Kamera ditemukan (N)" |
| 40 | Tombol tambah terpilih | L444–447 | "+ Add Selected (N)" | ADA | V3 "+ Tambah terpilih (N)" / "Menambah…" |
| 41 | Header tabel hasil | L452–459 | IP Address / Port / Credentials / RTSP Target URL / Actions | BERBEDA | V3: IP / Port / Merek / URL Stream; kolom Credentials dan Actions per-baris hilang |

---

## 6. TAB Ad Space Config (admin-console.php L466–700)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 42 | Judul + deskripsi | L469–472 | "Ad Space Config" / "Atur gambar dan teks berjalan pada popup guest" | ADA | V3 `app/admin/ads/page.tsx` sama persis |
| 43 | Judul preview | L478–481 | "Live Preview (Pratinjau Langsung)" + badge "Widescreen Monitor (16:9)" | ADA | V3 sama persis |
| 44 | Label kamera preview | L486–490 | "📹 LOBBY UTAMA - LIVE" | BERBEDA | V3 "LOBBY UTAMA - LIVE" (tanpa emoji 📹) |
| 45 | Indikator REC | L493–496 | "● REC" | ADA | V3 sama |
| 46 | Teks marquee default | L505–508 | "Teks Iklan Anda" | ADA | V3 sama |
| 47 | Toggle status iklan | L523–533 | "Status Penayangan Iklan" / "Tampilkan space iklan ini di video stream guest" | ADA | V3 sama persis |
| 48 | Judul seksi 1 | L538–540 | "1. Tata Letak & Latar" | ADA | V3 sama |
| 49 | Lebar wadah | L544–550 | "Lebar Wadah Iklan (10% - 100%)", range min 10 max 100 default 100 | ADA | V3 sama |
| 50 | Posisi aliran konten | L554–561 | "Posisi Aliran Konten": "Rata Kiri"/"Rata Tengah"/"Rata Kanan" | ADA | V3 sama |
| 51 | Warna latar | L565–571 | "Warna Latar Belakang", color + text placeholder "#1E293B" | ADA | V3 sama |
| 52 | Transparansi latar | L575–581 | "Transparansi Latar (0% - 100%)" | ADA | V3 sama |
| 53 | Judul seksi 2 | L586–588 | "2. Logo Sponsor & Media" | ADA | V3 sama |
| 54 | Upload gambar sponsor | L592–610 | "Gambar Sponsor (Kiri Iklan)" / "Tidak ada gambar" / "Pilih Berkas" / placeholder "Atau tempel URL gambar..." | ADA | V3 sama (+ status "Mengunggah…") |
| 55 | Transparansi logo | L614–620 | "Transparansi Logo (0% - 100%)" | ADA | V3 sama |
| 56 | Tinggi logo | L624–630 | "Tinggi Ukuran Logo (10px - 60px)", range min 10 max 60 default 20 | ADA | V3 sama |
| 57 | Judul seksi 3 | L635–637 | "3. Teks Bergulir (Marquee)" | ADA | V3 sama |
| 58 | Isi teks marquee | L641–644 | "Isi Teks Marquee", required, placeholder "Ketik kalimat informasi iklan..." | BERBEDA | V3 label + placeholder sama, tapi atribut required tidak ada di kode |
| 59 | Warna teks | L649–655 | "Warna Teks", color + text placeholder "#FFFFFF" | BERBEDA | V3 komponen ColorRow memakai placeholder "#1E293B" untuk kedua warna |
| 60 | Jenis font | L658–667 | "Jenis Font": Monospace / Sans-Serif / Serif / Cursive / Arial / Courier | ADA | V3 opsi sama persis |
| 61 | Ukuran font | L673–680 | "Ukuran Font", range min 8 max 24 default 10 | ADA | V3 sama |
| 62 | Kecepatan | L683–690 | "Kecepatan", range min 1 max 10 default 5 | ADA | V3 sama |
| 63 | Transparansi teks | L694–700 | "Transparansi Teks (0% - 100%)" | ADA | V3 sama |
| 64 | Tombol simpan | L676–680 | "Simpan Konfigurasi Iklan" | ADA | V3 sama (+ status "Menyimpan…"/"Tersimpan") |

## 7. TAB API Integration (admin-console.php L818–1005)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 65 | Judul embed settings | L823–828 | "Embed Player Settings (External API)" / "Batas waktu putar dan mode klik untuk pemutar eksternal" | BERBEDA | V3 `app/admin/keys/page.tsx`: "Pengaturan Embed Player" / "Berlaku untuk semua pemutar embed pihak ketiga" |
| 66 | Toggle click-to-play | L833–841 | "Click to Play" / "Wajib klik tombol Play untuk mulai memutar video" (default checked) | ADA | V3 "Klik untuk memutar" / "Pengunjung menekan tombol putar sebelum stream dimulai" (default true) |
| 67 | Field batas waktu | L845–860 | "Batas Waktu Pemutaran (Detik)", placeholder "Default: 300 (5 menit)", type number min 10 max 86400 value 300, deskripsi dinamis "5.0 Menit"/"Nonaktif"/"X Jam"/"X Detik" | BERBEDA | V3 "Batas waktu pemutaran (detik)", hint "Pemutaran berhenti otomatis setelah durasi ini"; tanpa min/max, tanpa placeholder, tanpa deskripsi dinamis |
| 68 | Tombol simpan embed | L862–866 | "Simpan Pengaturan Embed" | BERBEDA | V3 "Simpan" / "Menyimpan…" / "Tersimpan" |
| 69 | Judul daftar key | L873–878 | "API Keys & Active Integrations" / "Kunci akses eksternal yang aktif di sistem" | BERBEDA | V3 "API Key" / "Kunci embed untuk pihak ketiga — key penuh hanya tampil sekali saat dibuat" |
| 70 | Tombol generate | L879–881 | "+ Generate API Key Baru" | BERBEDA | V3 "+ Buat Key" + tombol baru "Panduan Integrasi" |
| 71 | Header tabel key | L887–894 | Client / Camera / Security / API Key & Embed URL / Actions | BERBEDA | V3 daftar kartu: nama, badge Aktif/Nonaktif, "{N} kamera", domain lock, "Tanpa playback", "Nama kustom: …", "Terakhir dipakai: …"/"belum pernah"; aksi "Aktifkan/Nonaktifkan" + "Hapus" saja — tidak ada tombol Ubah maupun Panduan per baris |
| 72 | Teks loading key | L896–904 | "Memuat daftar API key..." | BERBEDA | V3 spinner |
| 73 | Judul access log | L916–921 | "API Access Log" / "Jejak server dan domain yang memakai kunci API" | BERBEDA | V3 "Log akses" tanpa deskripsi |
| 74 | Filter log | L923–930 | "Semua Kunci" / "Semua Status" / "HIT saja" / "DENIED saja" | BERBEDA | V3 "Filter key"/"Semua key"; "Filter status"/"Semua status"/"Berhasil"/"Ditolak" |
| 75 | Tombol refresh | L931–936 | "Refresh" (title="Refresh log") | BERBEDA | V3 "Muat ulang" |
| 76 | Tombol hapus log | L937–942 | "Hapus Log" (title="Hapus semua log") | ADA | V3 "Hapus semua log" + dialog konfirmasi "Hapus semua log" / "Hapus seluruh catatan akses API? Tindakan ini tidak bisa dibatalkan." |
| 77 | Kartu ringkasan log | L946–963 | "Total Akses" / "HIT" / "DENIED" / "IP Unik" | HILANG | V3 tidak punya kartu ringkasan; ada ringkasan berbeda "Akses embed per API key" di halaman Dasbor |
| 78 | Header tabel log | L969–978 | Time / Client / Camera / Source IP / Referer / Domain / Status / Details | BERBEDA | V3: Waktu / Key / Kamera / Aksi / IP; kolom Referer/Domain dan Details hilang |
| 79 | Tombol muat lebih | L989–993 | "Muat 100 Log Lebih" | BERBEDA | V3 "Muat lebih banyak" (30/halaman) |
| 80 | Catatan auto-refresh | L997 | "Log diperbarui otomatis setiap 30 detik saat tab ini aktif." | HILANG | V3 muat manual via "Muat ulang" |
| 81 | Teks loading log | L980–987 | "Memuat log akses..." | BERBEDA | V3 spinner |

---

## 8. MODAL stream-modal — Add/Edit CCTV Stream (modals.php L6–137)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 82 | Judul + deskripsi modal | L9–11 | "Add CCTV Stream URL" / "Alamat RTSP, grup, dan koordinat kamera" | BERBEDA | V3 tambah: "Tambah Kamera" (tanpa deskripsi); ubah: "Ubah Kamera" (`streams/page.tsx` AddStreamModal/EditStreamModal) |
| 83 | Field nama kamera | L19–23 | "Camera Name / ID", required, placeholder "e.g., Office Back Entrance" | BERBEDA | V3 "Nama kamera", placeholder "cth: Gerbang Depan" |
| 84 | Field grup kamera | L27–36 | "Camera Group", required, datalist grup existing, placeholder "e.g., Kantor" | HILANG | V3 tak ada field grup per kamera; pengelompokan via halaman Grup → "Kelola Kamera" (camera-grants) |
| 85 | Field koordinat | L38–42 | "Coordinates (lat, lon)", placeholder "-6.2095, 106.8456" | BERBEDA | V3 dua field terpisah: "Latitude" placeholder "-6.2" + "Longitude" placeholder "106.8" |
| 86 | Field RTSP | L45–51 | "RTSP Target URL (Raw Source)", required, placeholder "rtsp://username:password@ip_address:554/path"; hint "RTSP credential links will remain securely hidden from user role profiles." | BERBEDA | V3 tambah memakai alur segmented "Brand + kredensial" (scan 13 brand → pilih kandidat) atau "URL RTSP langsung" (placeholder "rtsp://admin:pass@192.168.1.100:554/..."); modal Ubah V3 **tidak bisa** mengedit URL RTSP; hint keamanan hilang |
| 87 | Toggle Active Feed | L59–74 | "Active Feed" / "Camera will be visible to users" (default checked) | BERBEDA | V3 hanya di modal Ubah: checkbox "Kamera aktif"; di modal Tambah tidak ada |
| 88 | Toggle Recording | L78–93 | "Recording" / "Simpan rekaman ke disk" | ADA | V3 checkbox "Simpan rekaman ke disk" (di Tambah & Ubah) |
| 89 | Pilihan disk | L99–104 | "Save to Disk", opsi "/ (Root)" + info disk | HILANG | V3 mengganti dengan "Mode penyimpanan rekaman": Lokal / Google Drive / Keduanya |
| 90 | Preview recording path | L106–110 | "Recording Path", preview "{disk}/recordings/{group}/{nama_kamera}/"; hint "Otomatis dari grup dan nama kamera" | HILANG | V3 tak ada |
| 91 | Field retensi | L112–116 | "Retention (days)", type number min 1 max 365 value 7; hint "Auto-delete recording lebih lama dari ini" | BERBEDA | V3 "Retensi (hari)", hint "1–365"; batasan min/max tidak eksplisit di input |
| 92 | Tombol footer | L119–129 | "Cancel" / "Save Configuration" | BERBEDA | V3: Modal (X); Tambah: tombol "Scan"/"Memindai…" lalu pilih kandidat; Ubah: "Simpan"/"Menyimpan…" |

## 9. MODAL user-modal — Add/Edit User (modals.php L142–240)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 93 | Judul + deskripsi | L146–149 | "Add User Account" / "Akun, peran, dan grup pengelolanya" | BERBEDA | V3 `users/page.tsx` UserFormModal: "Tambah Pengguna" / "Ubah Pengguna" (tanpa deskripsi) |
| 94 | Field username | L153–158 | "Username", required, placeholder "e.g., operator_123" | BERBEDA | V3 "Nama pengguna", tanpa placeholder |
| 95 | Field password | L160–166 | "Password", required, placeholder "••••••••"; help saat edit: "Leave empty to keep current password." | BERBEDA | V3 "Kata sandi" / saat ubah "Kata sandi baru (kosongkan bila tidak diubah)"; hint saat tambah: "Minimal 8 karakter" |
| 96 | Field role | L169–194 | "Account Role": "USER (Penonton Kamera)" / "GUEST (Akses Terbatas)" / "ADMIN (Pengelola Bawahan)" / "SUPER ADMIN (Kuasa Penuh)" | BERBEDA | V3 "Peran": "Pengguna" / "Admin" / "Tamu" — **opsi Super Admin tidak ada** di select |
| 97 | Field grup pengguna | L201–227 | "Grup Pengguna" (khusus super_admin; admin terkunci di grupnya), opsi "Belum masuk grup", input "Nama grup baru" maxlength 60 placeholder "Nama grup baru"; hint "Akun segrup saling terjangkau. Kosongkan bila akun ini belum masuk grup mana pun." | HILANG | V3 UserFormModal tak punya field grup sama sekali |
| 98 | Toggle iklan | L228–237 | "Tampilkan Iklan" / hint "Berlaku utk semua akun tanpa grup" (wrap hidden by default) | BERBEDA | V3 "Tampilkan Iklan" / "Banner iklan tampil untuk akun ini" (selalu tampil) |
| 99 | Tombol footer | L238–250 | "Cancel" / "Save User Account" | BERBEDA | V3: "Simpan" / "Menyimpan…" (tutup via X) |

## 10. MODAL grup-nama-modal — Rename Group (modals.php L246–292)

Seluruh modal **HILANG** di V3 (halaman Grup V3 hanya punya "+ Tambah Grup" dan "Kelola Kamera"; tidak ada rename/hapus grup maupun toggle iklan grup).

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 100 | Judul + deskripsi | L250–253 | "Rename Group" / "Seluruh anggota grup ikut berpindah sekaligus" | HILANG | — |
| 101 | Field nama grup | L257–261 | "Nama Grup", required, maxlength 60 | HILANG | — |
| 102 | Keterangan anggota | L262–264 | "{nama lama} · {N} anggota ikut pindah" | HILANG | — |
| 103 | Toggle iklan grup | L266–275 | "Tampilkan Iklan" / "Berlaku utk seluruh anggota grup" | HILANG | — |
| 104 | Tombol footer | L276–289 | "Cancel" / "Save Group Name" | HILANG | — |

## 11. MODAL permissions-modal — CCTV Access Mapping (modals.php L297–331)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 105 | Judul + deskripsi | L301–305 | "CCTV Access Mapping" / "Kamera yang boleh dilihat akun ini" | BERBEDA | V3 `users/page.tsx` AccessModal: "Akses kamera — {username}"; ada "Pilih semua"/"Bersihkan", hitung "{n} dari {m} dipilih", empty-state "Belum ada kamera." |
| 106 | Tombol footer | L318–329 | "Cancel" / "Save Permissions" | ADA | V3 "Batal" / "Simpan" |

## 12. MODAL berbagi-modal — Camera Sharing (modals.php L336–385)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 107 | Judul modal | L340–343 | "Camera Sharing" | BERBEDA | V3 `components/ShareModal.tsx`: "Bagikan — {nama}"; deskripsi "Pilih akun yang boleh melihat kamera ini." |
| 108 | Seksi grup | L350–355 | Label "Grup" + hint "Grup memegang kamera lewat Admin pemiliknya; ubah di baris grup." | HILANG | V3 tak ada seksi grup |
| 109 | Pencarian akun | L358–367 | Label "Akun" + badge hitung + placeholder "Cari akun…" | HILANG | V3 tak ada kolom pencarian |
| 110 | Kolom Lihat/Rekaman | L362–365 | Header kolom "Lihat" / "Rekaman" per akun | HILANG | V3 satu checkbox per akun (tanpa pemisah live vs rekaman) |
| 111 | Tombol footer | L375–383 | "Batal" / "Simpan" | ADA | V3 "Batal" / "Simpan"/"Menyimpan…" |

## 13. MODAL akses-modal — Camera Access (modals.php L387–448)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 112 | Judul modal | L391–394 | "Camera Access" | BERBEDA | V3 `access/page.tsx`: "Akses kamera — {username}" (per akun) / "Akses — {nama}" (per kamera) |
| 113 | Pilih akun | L401–418 | "Akun", opsi "Pilih akun" | HILANG | V3 konteks dari baris yang diklik ("Kelola"), tak ada dropdown pilih akun |
| 114 | Cari kamera | L428–430 | Placeholder "Cari kamera…" | HILANG | V3 hanya search global "Cari…" di halaman |
| 115 | Kolom LIVE/REKAMAN/BAGIKAN | L434–441 | Header "LIVE" / "REKAMAN" / "BAGIKAN" (tersembunyi) | HILANG | V3 satu checkbox per baris; hak tamu diatur terpisah via "Tamu (semua sesi guest)" di modal per-kamera |
| 116 | Empty state | L443–445 | "Pilih akun dahulu" | HILANG | — |
| 117 | Tombol footer | L448–460 | "Cancel" / "Simpan Akses" | ADA | V3 "Batal" / "Simpan"/"Menyimpan…" |

## 14. MODAL map-modal — Camera Location (modals.php L453–491)

Seluruh modal **HILANG** di V3 (tidak ada referensi Leaflet/peta di `app/admin/`).

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 118 | Judul + deskripsi | L462–468 | "Camera Location" / "Titik kamera dan tautan ke peta luar" | HILANG | — |
| 119 | Tautan Google Maps | L471–477 | "Google Maps" | HILANG | — |
| 120 | Teks tanpa koordinat | L469 | "No coordinates" | HILANG | — |
| 121 | Atribusi peta | L487 | "Map data © OpenStreetMap contributors" | HILANG | — |
| 122 | Hint interaksi | L488 | "Scroll to zoom · Drag to pan" | HILANG | — |

---

## 15. MODAL bulk-add-modal — Bulk Add CCTV Config (modals.php L496–562)

Seluruh modal **HILANG** di V3 (scanner V3 langsung menambah kamera terpilih dengan nama default "Kamera {host}").

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 123 | Judul + deskripsi | L500–503 | "Bulk Add CCTV Config" / "Tambah banyak kamera sekaligus dari daftar" | HILANG | — |
| 124 | Checkbox grouping | L508–512 | "Kelompokkan ke dalam Grup" (default checked) | HILANG | — |
| 125 | Field nama grup | L516–520 | "Nama Grup Kamera", default "Scanned", placeholder "e.g., Scanned atau Kantor" | HILANG | — |
| 126 | Field koordinat | L524–529 | "Koordinat Kamera (lat, lon)", placeholder "-6.2095, 106.8456 (opsional)" | HILANG | — |
| 127 | Tipe penamaan | L533–541 | "Tipe Penamaan CCTV": "Penamaan Asli (contoh: Kamera 192.168.36.242)" / "Nama Kustom + IP (contoh: Lobi - 192.168.36.242)" / "Nama Kustom + Nomor Urut (contoh: Lobi 1, Lobi 2, ...)" | HILANG | — |
| 128 | Prefix kustom | L545–550 | "Nama Kustom (Prefix)", placeholder "e.g., Lobi Depan" | HILANG | — |
| 129 | Tombol footer | L552–560 | "Cancel" / "Tambahkan Kamera" | HILANG | — |

## 16. MODAL bulk-coords-modal — Bulk Edit Coordinates (modals.php L567–598)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 130 | Judul + deskripsi | L571–574 | "Bulk Edit Coordinates" / "Ubah koordinat banyak kamera sekaligus" | BERBEDA | V3 `streams/page.tsx` BulkCoordsModal: "Set koordinat ({N} kamera)" |
| 131 | Field koordinat | L579–585 | "Koordinat Kamera Baru (lat, lon)", required, placeholder "e.g., -6.2095, 106.8456"; hint "Koordinat ini akan diterapkan ke {N} kamera terpilih secara bersamaan." | BERBEDA | V3 dua field: "Latitude" hint "-90 s/d 90" placeholder "-6.2" + "Longitude" hint "-180 s/d 180" placeholder "106.8", dengan validasi rentang angka |
| 132 | Tombol footer | L587–596 | "Cancel" / "Simpan Koordinat" | BERBEDA | V3 "Terapkan ke semua terpilih" / "Menyimpan…" |

## 17. MODAL api-setup-modal — API Integration Guide (modals.php L603–701)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 133 | Judul + deskripsi | L607–611 | "API Integration Guide" / "Cara memasang stream di server lain" | BERBEDA | V3 `keys/page.tsx` IntegrationGuideModal: "Panduan Integrasi API" (tanpa deskripsi) |
| 134 | Catatan keamanan | L617–620 | "Catatan Keamanan:" + teks dinamis | HILANG | — |
| 135 | Kotak ringkasan | L623–640 | "Kamera" / "Playback" / "Domain" / "Sandi" | HILANG | — |
| 136 | Pilihan mode | L645–659 | "Mode", hint "Semua contoh di bawah mengikuti mode ini"; tombol "Stream Langsung" / "Rekaman (Playback)" | HILANG | V3 tak ada mode stream/playback di panduan |
| 137 | Pemilih kamera | L662–669 | "Pilih Kamera" / "Dipanggil dengan &camera=NOMOR" | HILANG | — |
| 138 | Metode 1 | L673–679 | "Metode 1: Pemutar Embed (Iframe HTML)" / "Gunakan kode HTML berikut untuk menyematkan pemutar video langsung di halaman web Anda." / "Salin Code" | BERBEDA | V3 "Metode 1 — Kode iframe" / "Tempel di halaman web/HTML Anda." / "Salin" |
| 139 | Metode 2 | L682–688 | "Metode 2: REST API Endpoint (JSON)" / "Gunakan HTTP GET request untuk mengambil detail stream format JSON (termasuk WebRTC / WHEP URL untuk player kustom)." / "Salin URL" | BERBEDA | V3 "Metode 2 — URL REST API" / "Ambil daftar kamera & URL stream sebagai JSON." / "Salin" |
| 140 | Metode 3 | L691–697 | "Metode 3: URL Pemutar Langsung" / "Link direct untuk membuka halaman pemutar mandiri." / "Salin URL" | BERBEDA | V3 "Metode 3 — URL pemutar langsung" / "Tautan langsung ke halaman pemutar embed." / "Salin" |
| 141 | Tombol tutup | L699–704 | "Close" | BERBEDA | V3 tutup via X |

## 18. MODAL api-key-edit-modal — Edit API Key (modals.php L704–800)

Seluruh modal **HILANG** di V3 — tidak ada tombol/fitur Ubah API key (`keys/page.tsx` hanya punya Aktifkan/Nonaktifkan + Hapus).

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 142 | Judul + deskripsi | L708–711 | "Edit API Key Integration" / "Nama klien, kamera, dan batasan domainnya" | HILANG | — |
| 143 | Field nama klien | L717–720 | "Nama Klien / Server Penerima", required, placeholder "Contoh: Server A, Website Dinas" | HILANG | — |
| 144 | Field judul kustom | L723–726 | "Judul Kamera Kustom (Opsional)", placeholder "Contoh: Kamera Depan, Pos Jaga (Untuk menyamarkan nama asli)" | HILANG | — |
| 145 | Field domain | L731–734 | "Batasi Domain Asal (Whitelisting)", placeholder "Contoh: domain.com (Kosongkan jika ingin PUBLIC)" | HILANG | — |
| 146 | Field password | L735–738 | "Password Keamanan Tambahan", placeholder "Kosongkan untuk tidak mengubah password" | HILANG | — |
| 147 | Pilih kamera | L744–762 | "Kamera (boleh lebih dari satu)", "0 dipilih", tombol "Semua"/"Kosong", placeholder "Cari kamera...", teks "Memuat kamera..." | HILANG | — |
| 148 | Hint kamera utama | L763 | "Kamera pertama yang dicentang menjadi kamera utama (dipakai bila URL tanpa parameter camera)." | HILANG | — |
| 149 | Urutan kamera | L767–774 | "Urutan Kamera", "Nomor 1 = kamera utama"; hint "Klien memanggil `&camera=1`, `&camera=2`, dan seterusnya sesuai nomor di atas. Nomor 1 juga dipakai bila URL tanpa parameter camera." | HILANG | — |
| 150 | Toggle playback | L775–790 | "Sertakan playback jika ada" / "Klien boleh melihat rekaman kamera di atas" | HILANG | — |
| 151 | Tombol footer | L792–800 | "Cancel" / "Simpan Perubahan" | HILANG | — |

## 19. MODAL api-key-generate-modal — Generate API Key (modals.php L803–897)

| # | Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|--------|-----------|---------|-----------|---------|
| 152 | Judul + deskripsi | L807–810 | "Generate New API Key" / "Buat kunci baru untuk pemutar di server lain" | BERBEDA | V3 `keys/page.tsx` KeyFormModal: "Buat API Key" (tanpa deskripsi) |
| 153 | Field nama klien | L815–818 | "Nama Klien / Server Penerima", required, placeholder "Contoh: Server A, Website Dinas" | BERBEDA | V3 "Nama key", placeholder "cth: Website mitra" |
| 154 | Field judul kustom | L819–822 | "Judul Kamera Kustom (Opsional)", placeholder "Contoh: Kamera Depan, Pos Jaga (Untuk menyamarkan nama asli)" | BERBEDA | V3 "Judul kamera kustom (opsional)", hint "Untuk menyamarkan nama asli, cth: Kamera Depan, Pos Jaga", placeholder "Kosongkan untuk memakai nama asli" |
| 155 | Field domain | L828–832 | "Batasi Domain Asal (Whitelisting Referrer)", placeholder "Contoh: klien.com (Kosongkan jika ingin PUBLIC)"; hint "Jika diisi, iframe hanya bisa diputar dari domain tersebut." | BERBEDA | V3 "Kunci domain (opsional)", hint "cth: mitra.or.id" (tanpa penjelasan whitelist) |
| 156 | Field password | L833–837 | "Password Keamanan Tambahan (Opsional)", placeholder "Masukkan password tambahan (Kosongkan jika tanpa password)"; hint "Jika diisi, pemanggil wajib menambahkan parameter &pass=... pada url." | BERBEDA | V3 "Kata sandi embed (opsional)" (tanpa hint `&pass=`) |
| 157 | Pilih kamera | L843–861 | "Pilih Kamera (boleh lebih dari satu)", "0 dipilih", tombol "Semua"/"Kosong", placeholder "Cari kamera...", teks "Memuat kamera..."; hint kamera utama (sama seperti #148) | BERBEDA | V3 "Kamera yang boleh diakses (N)"; tanpa tombol Semua/Kosong, tanpa search, tanpa teks loading |
| 158 | Urutan kamera | L866–873 | "Urutan Kamera", "Nomor 1 = kamera utama" + hint `&camera=N` | ADA | V3 "Urutan kamera" dengan tombol naik/turun ↑/↓ (tanpa hint `&camera=N`) |
| 159 | Toggle playback | L874–889 | "Sertakan playback jika ada" / "Klien boleh melihat rekaman kamera di atas" | BERBEDA | V3 "Sertakan playback" / "Key ini boleh membuka rekaman, bukan hanya live" |
| 160 | Tombol footer | L891–900 | "Cancel" / "Generate API Key" | BERBEDA | V3 tanpa Cancel eksplisit; "Buat Key" / "Membuat…" |

---

## 20. Fitur BARU di V3 (tidak ada padanannya di file V2 — bukan item paritas)

- **Dasbor admin** (`app/admin/page.tsx`): strip status Kamera/Pengguna/API key/Akses embed, kartu "Penyimpanan rekaman", "Akses embed per API key" dengan empty-state "Belum ada akses embed tercatat."
- **Halaman Grup** (`app/admin/groups/page.tsx`): "Grup Wilayah" / "Kelompokkan kamera per area dan atur cakupannya"; "+ Tambah Grup" (modal "Nama grup" placeholder "cth: Gedung A", "Deskripsi (opsional)"); "Kelola Kamera" (modal "Kamera grup — {nama}").
- **Halaman Drive** (`app/admin/drive/page.tsx`): "Penyimpanan Google Drive" / "Kelola akun Google Drive untuk unggahan rekaman kamera"; "+ Tambah akun" (modal "Tambah Akun Google Drive", field "Nama akun" placeholder "cth: Akun A — Gerbang", tombol "Buat & hubungkan"); badge "Terhubung"/"Bermasalah"/"Menunggu", "Default", "{N} kamera"; aksi "Jadikan default"/"Hubungkan ulang"/"Hapus"; notice "Akun Google Drive berhasil terhubung."
- **Halaman Penyimpanan** (`app/admin/storage/page.tsx`): "Penyimpanan Google Drive" + panduan rclone (folder-link mode).
- **Modal Tambah Kamera**: segmented "Brand + kredensial"/"URL RTSP langsung", select 13 brand, "Host / IP", "Port RTSP", "Channel", hint Ezviz "Ezviz: password biasanya berupa device verification code (6 karakter di stiker perangkat).", tombol "Scan", "Kandidat ditemukan — pilih satu untuk disimpan:", error "Tidak ada kandidat ditemukan."
- **Modal Ubah Kamera**: seksi "Kamera"/"Penyimpanan rekaman", checkbox "Kamera aktif", "Mode penyimpanan rekaman" (Lokal/Google Drive/Keduanya), "Akun Google Drive" hint "Kamera ini mengunggah rekaman ke akun ini" + opsi "Ikuti bawaan (default)".
- **Halaman Pengguna**: badge "Dibuat oleh: {nama}", tombol "Akses Kamera" per baris, modal "Akses kamera — {username}" ("{n} dari {m} dipilih", "Pilih semua"/"Bersihkan").
- **Halaman Akses**: modal per-kamera memuat "Tamu (semua sesi guest)".
- **Halaman Key**: modal "API key dibuat" — "Salin key ini sekarang — tidak akan ditampilkan lagi." + tombol "Selesai"/"Panduan Integrasi"; badge "Tanpa playback", "Terakhir dipakai: {waktu}/belum pernah".
- **Scanner**: teks idle "Isi subnet lalu tekan "Scan Network" untuk mulai memindai.", empty "Tidak ada kamera yang merespons di subnet ini.", sukses "{N} kamera berhasil ditambahkan. Lihat di tab Kamera."
- **Streams**: badge hitung "{N} dari {M}", "Terakhir terlihat: {waktu}", "Pilih semua di halaman ini", "Batalkan pilihan", empty-state "Tidak ada kamera yang cocok dengan filter." / "Belum ada kamera. Tambahkan yang pertama."

---

## Ringkasan

| Kategori | Jumlah |
|----------|--------|
| Detail diinventarisasi | **160** |
| ADA | **38** |
| BERBEDA | **75** |
| HILANG | **47** |

**HILANG terbesar per area:** Edit API Key modal utuh (10), Bulk Add modal utuh (7), Rename Group modal utuh (5), map-modal Camera Location utuh (5), panduan integrasi: catatan keamanan + ringkasan + mode + pemilih kamera (4), modal Camera Access: pilih akun + cari kamera + kolom LIVE/REKAMAN + empty "Pilih akun dahulu" (4), Camera Sharing: seksi grup + cari akun + kolom Lihat/Rekaman (3), stream modal: field Camera Group + Save to Disk + preview Recording Path (3), scanner: field Codec + koordinat default (2), API log: kartu ringkasan + catatan auto-refresh 30 detik (2), tab Camera Access: tombol Add Access (1), user modal: field Grup Pengguna (1).

**BERBEDA paling berdampak:** (a) select Peran di modal user V3 **kehilangan opsi SUPER ADMIN**; (b) modal Ubah Kamera V3 **tidak bisa mengedit URL RTSP**; (c) tab Camera Access berubah dari "Per Grup" (default) menjadi "Per akun"/"Per kamera" — konsep grup-sebagai-otorisasi hilang; (d) seluruh label tab/nav diterjemahkan & disederhanakan (Camera Streams→Kamera, dsb.) tanpa badge hitung; (e) tabel-tabel admin V2 menjadi daftar kartu/baris + accordion di mobile; (f) tidak ada teks `confirm()` di file V2 — konfirmasi V2 hidup di JS, jadi perbandingan teks konfirmasi persis tidak dimungkinkan dari cakupan ini (teks ConfirmModal V3 dicatat di bagian 7 no. 76).


---

# Part D — Embed, Iklan & Pesan Sistem (V2 vs V3)

Analisa read-only. V2 = `/tmp/v2-ref` ("Mamura Stream" v2.0). V3 = `~/workspace/netravision` (apps/web + apps/api).
Status paritas: **ADA** (sebut lokasi V3) / **HILANG** / **BERBEDA**.

---

## A. Halaman embed (`/tmp/v2-ref/frontend/embed.php` vs `apps/web/app/embed/page.tsx`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul tab browser | embed.php:7 | "Mamura Stream - Embedded CCTV Feed" | BERBEDA | V3 tidak menetapkan title per-halaman; header menampilkan logo "N" + teks "NetraVision" dan pill "Siaran publik", footer "NetraVision · Siaran publik pihak ketiga" |
| Teks loading | embed.php:119 | "Menghubungkan ke server stream..." | BERBEDA | V3: placeholder skeleton `aspect-video animate-pulse` tanpa teks (fallback Suspense: "Memuat…") |
| Layar error default | embed.php:128-130 | Judul "Akses Ditolak" / pesan "Kunci API tidak valid atau tidak memiliki akses ke kamera ini." | BERBEDA | V3 phase "error": judul "Tautan embed tidak valid", pesan "Parameter `?key=` tidak ditemukan atau tidak dikenal." |
| Error key kosong | embed.php:241 | "Parameter API Key (key) wajib disertakan untuk mengakses stream." | BERBEDA | V3 (tanpa key): phase "error" → pesan di atas; tidak ada teks "Parameter API Key (key) wajib disertakan…" |
| Error fetch/stream | embed.php:306 | "Gagal Memutar CCTV" (+ err.message) | BERBEDA | V3: pesan error inline di player + tombol "Coba lagi"; tidak ada judul "Gagal Memutar CCTV" |
| Error ICE failed | embed.php:355 | Judul "Koneksi Gagal" / "Koneksi WebRTC ke media server terputus." | HILANG | V3: hanya pesan generik "Gagal memutar stream." — tidak ada teks khusus koneksi terputus |
| Error handshake WHEP | embed.php:369 | Judul "Gagal Handshake WHEP" / "Media server tidak merespons koneksi stream." | HILANG | V3: hanya "Gagal memutar stream." |
| Tombol Play (click-to-play) | embed.php:133-141 | Tombol lingkaran biru; label di bawahnya hidden default | BERBEDA | V3: lingkaran accent + label "Klik untuk memutar" (atau "Menyiapkan sesi…" / "Kamera offline") |
| Teks setelah timeout habis | embed.php:295 | "Waktu pemutaran habis. Klik untuk memutar kembali." | BERBEDA | V3: "Sesi berakhir — tekan Perpanjang untuk lanjut." |
| Label info kamera | embed.php:144-147 | Dot hijau + "{nama} - Live" di overlay kiri-atas video | BERBEDA | V3: nama kamera di bar bawah player (tanpa sufiks "- Live", tanpa overlay kiri-atas) |
| Tombol Stop | embed.php:150-154 | "Stop Feed" (overlay kanan-atas video) | BERBEDA | V3: tombol "Stop" di bar bawah player (hanya saat playing) |
| Toast keep-alive | embed.php:156-166 | "Pemutaran akan dihentikan dalam {N} detik." + tombol "Lanjutkan Menonton" (posisi bawah-tengah) | BERBEDA | V3: toast kiri-atas "Sesi berakhir dalam m:ss" + tombol "Perpanjang"; dipicu saat sisa < 90 detik berdasarkan `expires_at` sesi |
| Batas waktu pemutaran | embed.php:190,332-338 | `embedTimeoutSeconds` (default 300s), toast mulai 15 detik sebelum habis, auto-stop, hitung mundur detik | BERBEDA | V3: tidak membaca `embed_timeout_seconds` di halaman embed; sesi berakhir dari `expires_at` server (session model), countdown m:ss |
| Poster video statis | embed.php:284-286 | `video.poster = /api/posters/stream_{id}.jpg` | HILANG | V3: tidak menetapkan poster di embed |
| Mode auto-play (click_to_play=false) | embed.php:321-331 | Langsung putar otomatis, sembunyikan overlay play | HILANG | V3: selalu klik-untuk-mutar ("Klik untuk memutar"); flag `click_to_play` tidak dibaca di halaman embed |
| Parameter `?pass=` | embed.php:235 | Mendukung `pass` untuk kata sandi kunci API | HILANG | V3 embed tidak meneruskan/mendukung `?pass=` |
| Parameter `?camera=` | embed.php:237, main.py:5047-5052 | Server memvalidasi: "Nomor kamera tidak sah. Kunci ini punya {n} kamera (camera=1..{n})" | BERBEDA | V3: `?camera=` memfilter daftar lokal; bila tidak cocok muncul notice "Kamera ?camera={x} tidak tersedia untuk kunci ini — menampilkan semua kamera." |
| Pesan error backend external | main.py:5002,5011,5043,5052,5057 | 403 "Kunci API tidak valid atau tidak aktif"; 403 "Kata sandi akses salah atau tidak disertakan"; 403 "Akses ditolak: Domain asal tidak diizinkan"; 403 "Nomor kamera tidak sah…"; 404 "Kamera tidak ditemukan" | BERBEDA | V3: halaman hanya membedakan 404 → "Kunci API tidak dikenal."; error lain → "Tautan embed tidak valid" (pesan API detail tidak ditampilkan) |

## B. Banner iklan di embed

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Posisi banner | embed.php:170-186, global.css:1162 | `absolute bottom-10px left-10 right-10`, z-30, overlay lower-third di dalam player | ADA | `components/AdBanner.tsx`: `absolute inset-x-0 bottom-0 z-20` di dalam `relative aspect-video`; margin 10px hilang (menempel tepi) |
| Isi banner | embed.php:171-181 | `<img alt="Sponsor">` (tinggi 20px) + marquee teks berjalan | ADA | `AdBanner.tsx`: sama — img logo + marquee |
| Kapan tampil | embed.php:276-278, main.py:5060-5086 | Hanya bila respons `data.ad` ada — server hanya mengirim `ad` bila `is_active` | ADA | `app/embed/page.tsx`: `{ad?.is_active && <AdBanner config={ad} />}` |
| Sumber data embed | embed.php:276 | `ad` dari respons `/api/external/stream` (server absolutkan image_url relatif) | BERBEDA | V3: GET publik `/ad-config`; "backend menonaktifkan bila tak diizinkan (show_ads)" |
| Rumus durasi marquee | embed.php:425 | `duration = max(10, (11 - speed) * 18)` detik | ADA | `AdBanner.tsx`: rumus identik |
| Jumlah span marquee | embed.php:430-441 | 4 span diulang agar tersambung tanpa jeda | BERBEDA | `AdBanner.tsx`: 2 span + `pr-16` |
| Auto-hide layar sangat pendek | global.css:3423-3427 | Media query: sembunyikan banner pada HP mendatar berlayar sangat pendek | HILANG | V3 tidak punya aturan auto-hide khusus |

## C. Banner iklan popup guest & grid tile (V2 `assets/js/modules/webrtc.js` vs V3 `components/FocusModal.tsx`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Banner popup di bawah video | webrtc.js:1592-1596, 2642-2677 | Bar `#popup-ad-overlay` di bawah video, "always visible (not hover-only), follows Ad Manager settings" | BERBEDA | V3 `FocusModal.tsx:159`: `{ad?.is_active && <AdBanner config={ad} />}` — overlay menempel bawah video (absolute), bukan bar di bawah video |
| Pemisah item marquee popup/tile | webrtc.js:1198, 2658 | Setiap item disambung dengan `  |  ` (pipe) | HILANG | V3: tidak ada pemisah pipe; jarak via `pr-16` |
| Batas ukuran font popup/tile | webrtc.js:1200, 2648 | `Math.min(10, font_size)`, default 9px | BERBEDA | V3 `AdBanner.tsx`: clamp 8–24px |
| Banner hover di tile grid | webrtc.js:1192-1243 | Ad bar bawah tile, `opacity-0 group-hover:opacity-100` (muncul saat hover) | HILANG | V3: `AdBanner` hanya dipakai di embed & FocusModal; grid tile tidak punya banner iklan |
| Fetch config iklan global | router.js:562-574 | Fetch `/ad-config` dengan Bearer token saat DOMContentLoaded; gating show_ads di backend | ADA | V3: `FocusModal.tsx:29` GET `/ad-config`; `app/embed/page.tsx` GET publik `/ad-config`; gating show_ads tetap di backend |

## D. Halaman admin "Ad Space Config" (`admin-console.php` subtab ads vs `apps/web/app/admin/ads/page.tsx`)

| Detail | Lokasi V2 | Teks V2 | Status V3 | Catatan |
|---|---|---|---|---|
| Judul halaman | admin-console.php (tab `ads`) | subtab admin "Iklan"/Ad Config | ADA | V3 `app/admin/ads/page.tsx`: title "Ad Space Config", desc "Atur gambar dan teks berjalan pada popup guest" |
| Preview langsung | admin-console.php:506-515 | Mock player + banner preview, placeholder "Teks Iklan Anda" | ADA | V3: komponen `AdPreview` (mock frame + label kamera kiri-atas + banner); placeholder teks sesuai `marquee_text` aktual |
| Status Penayangan Iklan / sub "Tampilkan space iklan ini di video stream guest" | admin-console.php:522-523 | teks persis | ADA | V3 `page.tsx:355` + deskripsi identik |
| "Lebar Wadah Iklan (10% - 100%)" | admin-console.php:540 | slider 10–100, default 100% | ADA | V3 `page.tsx:368` — sama |
| "Posisi Aliran Konten" (Rata Kiri / Rata Tengah / Rata Kanan) | admin-console.php:551-557 | select | ADA | V3 `page.tsx:375` — sama |
| "Warna Latar Belakang" | admin-console.php:561 | color picker + hex text | ADA | V3 `page.tsx:386` — sama |
| "Transparansi Latar (0% - 100%)" | admin-console.php:569 | slider, default 100% | ADA | V3 `page.tsx:391` — sama |
| "Gambar Sponsor (Kiri Iklan)" + "Pilih Berkas" + "Atau tempel URL gambar..." + "Tidak ada gambar" | admin-console.php:584-607 | persis | ADA | V3 `page.tsx:450-457` — semua teks ada |
| "Transparansi Logo (0% - 100%)" | admin-console.php:611 | slider, default 100% | ADA | V3 `page.tsx:457` — sama |
| "Tinggi Ukuran Logo (10px - 60px)" | admin-console.php:619 | slider 10–60, default 20px | ADA | V3 `page.tsx:465` — sama |
| "Isi Teks Marquee" / placeholder "Ketik kalimat informasi iklan..." | admin-console.php:625-628 | persis | ADA | V3 `page.tsx:481-486` — sama |
| "Warna Teks" | admin-console.php:633 | color picker | ADA | V3 `page.tsx:491` — sama |
| "Jenis Font" (Monospace, Sans-Serif, Serif, Cursive, Arial, Courier) | admin-console.php:641-649 | 6 opsi | ADA | V3 `page.tsx:495-505` — 6 opsi identik |
| "Ukuran Font" | admin-console.php:656 | slider 8–24, default 10px | ADA | V3 `page.tsx:511` — sama |
| "Kecepatan" | admin-console.php:663 | slider 1–10, default 5 | ADA | V3 `page.tsx:519` — sama |
| "Transparansi Teks (0% - 100%)" | admin-console.php:671 | slider, default 100% | ADA | V3 `page.tsx:528` — sama |
| Tombol simpan | admin-console.php:687 | "Simpan Konfigurasi Iklan" | ADA | V3 `page.tsx:540` — teks sama ("Menyimpan…" saat busy) |
| Pesan sukses simpan | admin.js:3089 | `showApiSuccessBanner("Konfigurasi iklan berhasil disimpan!")` | BERBEDA | V3: teks "Tersimpan" dengan ikon centang di bawah tombol |
| Pesan gagal simpan | admin.js:3092 | `showApiErrorBanner("Gagal menyimpan konfigurasi iklan: {err}")` | BERBEDA | V3: ErrorBox generik "Gagal menyimpan" + detail ApiError |
| Pesan error upload | main.py:4721-4726 | 400 "Format berkas tidak didukung (jpg/jpeg/png/gif/webp)"; 400 "Berkas kosong atau terlalu besar (maks 5MB)" | ADA | V3: error diteruskan dari API ke ErrorBox (backend `admin_ads.py` tetap memvalidasi; pesan ditampilkan apa adanya) |
| Seksi "Embed Player Settings (External API)": "Click to Play" ("Wajib klik tombol Play untuk mulai memutar video") + "Batas Waktu Pemutaran (Detik)" (number, default 300, min 10 max 86400, deskripsi dinamis "Nonaktif / X Menit / X Jam") | admin-console.php:835-875 | persis | HILANG | V3: `embed_timeout_seconds` & `click_to_play` ada di skema API (`apps/api/app/routers/admin_ads.py:44-45`), `lib/types.ts:56-57`, dan default state `ads/page.tsx:33-34`, tetapi TIDAK ada kontrol UI di halaman ads; pengaturan per-kunci ada di `app/admin/keys/page.tsx:479-496` |

## E. 16 field `AdConfig` (skema backend + default)

Sumber V2: `AdConfigModel` main.py:915-930, `AdConfigSchema` main.py:1671-1688, seed main.py:1584-1597.

| # | Field | Default V2 | Status V3 | Catatan |
|---|---|---|---|---|
| 1 | `image_url` | `""` | ADA | sama |
| 2 | `marquee_text` | `""` (skema); seed: **"Selamat Datang di Portal Monitoring CCTV. Hubungi Admin untuk info lebih lanjut."** (main.py:1589 & 4654) | BERBEDA | V3 `admin_ads.py:31`: default `marquee_text = ""` — teks sapaan default V2 tidak dibawa |
| 3 | `bg_color` | `"#1e293b"` | ADA | sama |
| 4 | `text_color` | `"#ffffff"` | ADA | sama |
| 5 | `scroll_speed` | `5` | ADA | sama |
| 6 | `font_size` | `10` | ADA | sama |
| 7 | `font_family` | `"monospace"` | ADA | sama |
| 8 | `image_opacity` | `1.0` | ADA | sama |
| 9 | `bg_opacity` | `1.0` | ADA | sama |
| 10 | `text_opacity` | `1.0` | ADA | sama |
| 11 | `is_active` | `True` | ADA | sama |
| 12 | `box_width` | `100` | ADA | sama |
| 13 | `text_align` | `"left"` | ADA | sama |
| 14 | `image_height` | `20` | ADA | sama |
| 15 | `embed_timeout_seconds` | `300` | BERBEDA | Ada di API/skema/types V3; tidak ada kontrol di UI halaman ads V3 (dan tidak dibaca halaman embed V3) |
| 16 | `click_to_play` | `True` | BERBEDA | Sama seperti di atas |

---

## Ringkasan angka

- **Total detail diinventarisasi: 67**
- **ADA: 36** (posisi & isi banner embed, 13/16 field + seluruh label admin, tombol simpan, upload, gating show_ads, fetch config global, dll.)
- **BERBEDA: 22** (semua teks halaman embed ditulis ulang, toast keep-alive, marquee 4→2 span tanpa pemisah pipe, popup banner overlay-vs-bar, cap font, pesan sukses/gagal simpan, default `marquee_text`, 2 field tanpa kontrol UI)
- **HILANG: 9** (error khusus ICE-failed & WHEP-handshake, poster video embed, auto-play saat click_to_play=false, `?pass=`, auto-hide banner di layar sangat pendek, banner hover tile grid, seksi "Embed Player Settings (External API)" global di UI)

### Temuan utama untuk parent
1. **Kontrak fungsional iklan utuh**: 13/16 field, label admin, rumus durasi marquee, gating `is_active`/show_ads — semua ada. Gap terbesar: `embed_timeout_seconds` & `click_to_play` hanya hidup di skema API, mati di UI halaman ads dan tidak dibaca halaman embed V3 (embed V3 memakai model sesi `expires_at`).
2. **Banner popup V3 menimpa video** (overlay bawah video), sedangkan V2 adalah bar di bawah video yang selalu terlihat; banner hover di grid tile V2 tidak ada padanannya di V3.
3. **Teks UI embed V3 ditulis ulang** (tidak ada satu pun pesan error/teks V2 yang dipertahankan verbatim kecuali nama "Stop"); pesan error backend external disembunyikan di balik dua pesan generik.
4. Teks marquee default V2 ("Selamat Datang di Portal Monitoring CCTV. Hubungi Admin untuk info lebih lanjut.") tidak dibawa ke V3 (default kosong).
