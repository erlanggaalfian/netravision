# Analisa Konsol Admin — V2 → V3 (Zero Deprecation Checklist)

> **Sumber V2:** `/tmp/v2-ref` (Mamura Stream v2.0) — `frontend/views/admin-console.php` (1008 baris), `frontend/views/modals.php` (897 baris), `frontend/assets/js/modules/admin.js` (3144 baris), `frontend/assets/js/modules/core.js` (1170 baris, bagian API key & log).
> **Pembanding V3:** `~/workspace/netravision/apps/web/app/admin/` (9 halaman: dasbor, streams, users, groups, keys, ads, drive, storage, scanner, access).
> **Tanggal analisa:** 2026-11-02. Sifat: READ-ONLY, tidak ada kode yang diubah.
> **Aturan mutlak:** setiap elemen V2 wajib ada di V3 (boleh ditambah, dilarang dikurang).

**Legenda status paritas:** ✅ ADA (ada & setara di V3) · ⚠️ BERBEDA (ada tapi perilaku/bentuk berubah) · ❌ HILANG (tidak ada di V3)

---

## 1. Struktur Tab Konsol Admin

V2 (`admin-console.php:28-111`) punya **6 tab** berupa tombol `.admin-tab-box` dengan ikon SVG:

| # | Tab V2 | Badge hitungan | File V3 | Status |
|---|--------|----------------|---------|--------|
| 1 | Camera Streams | ya (`admin-subtab-streams-badge`) | `app/admin/streams/page.tsx` | ✅ ADA |
| 2 | Console Users | ya (`admin-subtab-users-badge`) | `app/admin/users/page.tsx` | ✅ ADA |
| 3 | Camera Access | ya (`admin-subtab-access-badge`) | `app/admin/access/page.tsx` | ✅ ADA |
| 4 | Camera Scanner | tidak | `app/admin/scanner/page.tsx` | ✅ ADA |
| 5 | Ad Space Config | tidak | `app/admin/ads/page.tsx` | ✅ ADA |
| 6 | API Integration | ya (`admin-subtab-api-badge`) | `app/admin/keys/page.tsx` | ✅ ADA |

**Catatan:** V3 menambah tab baru (diperbolehkan): Dasbor, Grup (kamera), Drive (OAuth), Penyimpanan (folder-link). Badge hitungan di tab V2 (streams/users/access/api) — di V3 tab berupa link navigasi tanpa badge angka → ⚠️ BERBEDA (minor, kosmetik).

**Tab "Penyimpanan/Drive":** TIDAK ADA di V2 `/tmp/v2-ref` (grep `penyimpanan`/`google drive` di `admin-console.php` = nol hasil). Fitur Drive di V2 ini memang tidak ada; yang ada hanya field "Save to Disk" di modal kamera (lihat §3). Tab Drive/Penyimpanan di V3 adalah **penambahan baru**, bukan paritas.

---

## 2. TAB 1 — Camera Streams (`admin-console.php:113-259`)

Judul: "Camera Streams" · Deskripsi: "Kelola kamera terdaftar, alamat RTSP, dan status koneksi".

### 2.1 Toolbar filter (`admin-console.php:125-196`)

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Search input `#stream-search-input` | placeholder "Search camera name or RTSP...", filter nama ATAU rtsp_url ATAU group_name (`admin.js:384-390`) | `streams/page.tsx:294` "Cari kamera" | ✅ ADA |
| Group filter `#stream-group-filter` | dropdown "All Groups" + daftar grup dinamis | `streams/page.tsx:304` "Grup" | ✅ ADA |
| Status filter `#stream-status-filter` | "All Statuses" / "Connected (Online)" / "Disconnected (Offline)" | `streams/page.tsx:320` "Status" | ✅ ADA |
| Tombol "✕ Clear" `#stream-filter-clear` | muncul hanya saat filter aktif (`clearStreamFilter()`) | `streams/page.tsx:340` "Bersihkan" | ✅ ADA |
| Badge status filter `#stream-filter-status` | teks "N camera(s) match..." saat filter aktif | `streams/page.tsx:336` "{n} dari {m}" | ✅ ADA |
| Tombol "Set Coords (n)" `#set-selected-streams-coords-btn` | bulk set koordinat, muncul bila ada yg dicentang | `streams/page.tsx` bulk "Set koordinat" | ✅ ADA |
| Tombol "Delete Selected (n)" `#delete-selected-streams-btn` | bulk hapus | `streams/page.tsx:366` "Hapus terpilih (n)" | ✅ ADA |
| Tombol "Add Camera" | `openCreateStreamModal()` | `streams/page.tsx` "+ Tambah Kamera" | ✅ ADA |

### 2.2 Tabel `#admin-streams-table` — kolom (`admin-console.php:199-230`, render `admin.js:330-368`)

| Kolom V2 | Detail render | File V3 | Status |
|----------|---------------|---------|--------|
| Checkbox + select-all `#admin-streams-select-all` | **disabled bila kamera milik Super Admin** (`milikSendiri`, `admin.js:332-334`, tooltip "Dipasang Super Admin — tidak dapat dihapus dari sini") | V3 punya select-all | ⚠️ BERBEDA — aturan disabled utk kamera super_admin belum tentu ada di V3 |
| No | nomor urut | ✅ | ✅ ADA |
| Camera Name | nama + `data-grup` | ✅ | ✅ ADA |
| Group | badge biru, truncate | ✅ | ✅ ADA |
| Coordinates | truncate, title tooltip | ✅ | ✅ ADA |
| RTSP Endpoint | **disensor bila bukan milik sendiri** (tampil "••••" / "Dipasang Super Admin", `admin.js:340`) | V3: masking via `mask_rtsp_url()` di `admin_streams.py` | ✅ ADA |
| Status | dua badge: ACTIVE/DISABLED + CONNECTED/DISCONNECTED | V3 badge Online/Offline | ✅ ADA |
| Record | badge "REC" merah bila `record_enabled`, "—" bila tidak | `streams/page.tsx:113` badge "Rekaman: Aktif/Mati" | ✅ ADA |
| Actions | lihat di bawah | — | — |

### 2.3 Aksi per baris (`admin.js:359-367`)

| Aksi V2 | Detail | File V3 | Status |
|---------|--------|---------|--------|
| View | `window.viewAdminStream(id)` — pratinjau stream | `streams/page.tsx` | ❌ HILANG |
| ☷ Map | `openMapModal(id)` — peta lokasi; **disabled bila tak ada koordinat** | `streams/page.tsx` | ❌ HILANG |
| Edit | `openEditStreamModal(id)` — hanya bila milik sendiri | `streams/page.tsx:125` "Ubah" | ✅ ADA |
| Delete | `deleteStream(id)` + konfirmasi — hanya bila milik sendiri | `streams/page.tsx:128` "Hapus" | ✅ ADA |
| (tambahan V3) | — | "Bagikan" (`ShareModal`) | ➕ BARU (diperbolehkan) |

### 2.4 Pagination (`admin-console.php:245-258`, `admin.js:262-275`)

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Page size | `ADMIN_STREAMS_PAGE_SIZE = 15` (`core.js:15`) | `PAGE_SIZE = 12` (`streams/page.tsx:230`) | ⚠️ BERBEDA (15 → 12) |
| Kontrol | First/Prev/numbered/Next/Last + indikator halaman (`pagination-bar.php`) | V3 punya navigasi halaman | ✅ ADA |

---

## 3. Modal Kamera — `#stream-modal` (`modals.php:4-120`)

Judul: "Add CCTV Stream URL" / "Alamat RTSP, grup, dan koordinat kamera". Submit → `handleStreamSubmit(event)`.

| Field V2 | Tipe & aturan | File V3 | Status |
|----------|---------------|---------|--------|
| `modal-stream-id` | hidden (mode edit) | ✅ | ✅ ADA |
| Camera Name / ID `#modal-stream-name` | text, **required**, placeholder "e.g., Office Back Entrance" | `streams/page.tsx:697` "Nama kamera" | ✅ ADA |
| Camera Group `#modal-stream-group` | text + `<datalist id="existing-groups-list">`, **required**, placeholder "e.g., Kantor" | V3 pakai Select grup | ⚠️ BERBEDA (datalist ketik-bebas → dropdown; ketik grup baru tak bisa) |
| Coordinates `#modal-stream-coordinates` | text, placeholder "-6.2095, 106.8456" | `streams/page.tsx:813/821` Latitude + Longitude terpisah | ⚠️ BERBEDA (satu field teks → dua field angka; format input berubah) |
| RTSP Target URL `#modal-stream-rtsp` | text, **required**, placeholder "rtsp://username:password@ip_address:554/path", hint "RTSP credential links will remain securely hidden from user role profiles." | `streams/page.tsx:731` + Brand/Host/Username/Password/Port/Channel (`:741-777`) | ✅ ADA (V3 malah lebih rinci) |
| Active Feed `#modal-stream-active` | toggle, default **checked** ("Camera will be visible to users") | ✅ | ✅ ADA |
| Recording `#modal-stream-record` | toggle → membuka `#recording-options` ("Simpan rekaman ke disk") | `streams/page.tsx:803` "Simpan rekaman ke disk" | ✅ ADA |
| Save to Disk `#modal-stream-disk` | select, opsi default "/ (Root)" + daftar disk dinamis (`disk-info` hint) | — | ❌ HILANG (V3 hanya `storage_mode`; tidak ada pilihan disk) |
| Recording Path preview `#record-path-preview` | teks `{disk}/recordings/{group}/{nama_kamera}/` + "Otomatis dari grup dan nama kamera" | — | ❌ HILANG |
| Retention `#modal-stream-retention` | number **min 1 max 365**, default 7, hint "Auto-delete recording lebih lama dari ini" | `streams/page.tsx:806` "Retensi (hari)" 1–365 | ✅ ADA |
| Cancel | `closeStreamModal()` | ✅ | ✅ ADA |
| Save Configuration | submit | ✅ | ✅ ADA |

---

## 4. TAB 2 — Console Users (`admin-console.php:261-306`)

Judul: "Console Users" · Deskripsi: "Kelola akun pengguna, peran, dan grupnya". Tombol "Add User" → `openCreateUserModal()`.

### 4.1 Tabel users (`admin.js:880-960`) — struktur KHUSUS: baris grup + baris anggota

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|----------|--------|
| Baris grup (collapsible) | badge "grup" + nama, tombol expand "N anggota", klik baris = bentang/tutup (`bentangGrupPengguna`) | `users/page.tsx` | ❌ HILANG (V3 tak punya konsep grup pengguna sama sekali) |
| Aksi baris grup: Edit | `bukaGantiNamaGrup` → modal Rename Group | — | ❌ HILANG |
| Kolom No / Username / Role / Iklan / Actions | — | V3: Username, Role, Iklan, Dibuat oleh, Aksi | ✅ ADA (kolom Iklan = `show_ads`) |
| Badge "iklan on/off" per baris | `lencanaIklan()` — per grup (semua anggota) atau per akun lepas | `users/page.tsx:130` "Iklan: Ya/Tidak" | ✅ ADA |
| "Dibuat oleh: X" | di baris akun (`dibuat_oleh`) | `users/page.tsx:134` | ✅ ADA |
| Aksi per akun: Edit / Delete | `openEditUserModal(id)`, `deleteUser(id)` | ✅ | ✅ ADA |

### 4.2 Modal User — `#user-modal` (`modals.php:122-220`)

| Field V2 | Tipe & aturan | File V3 | Status |
|----------|---------------|---------|--------|
| Username `#modal-user-username` | text, required, "e.g., operator_123" | ✅ | ✅ ADA |
| Password `#modal-user-password` | password, **required saat tambah**, opsional saat edit ("Leave empty to keep current password.") | V3? | ⚠️ PERLU CEK — V2 membedakan required tambah vs opsional edit |
| Account Role `#modal-user-role` | select **4 opsi**: USER (Penonton Kamera) / GUEST (Akses Terbatas) / ADMIN (Pengelola Bawahan) / SUPER ADMIN (Kuasa Penuh) | `users/page.tsx:288` Select | ⚠️ PERLU CEK — pastikan 4 opsi ada di V3 |
| Grup Pengguna `#modal-user-grup` | select, **hanya tampil utk super_admin** ("Belum masuk grup" + daftar); admin biasa terkunci di grupnya | — | ❌ HILANG (tak ada grup pengguna di V3) |
| Nama grup baru `#modal-user-grup-baru` | text, maxlength 60, "Nama grup baru" | — | ❌ HILANG |
| Tampilkan Iklan `#modal-user-iklan` | toggle, hidden, utk akun tanpa grup ("Berlaku utk semua akun tanpa grup") | `users/page.tsx:297` "Tampilkan Iklan" | ✅ ADA |
| Cancel / Save User Account | — | ✅ | ✅ ADA |

### 4.3 Modal Rename Group — `#grup-nama-modal` (`modals.php:224-271`)

| Field V2 | Detail | File V3 | Status |
|----------|--------|---------|--------|
| Nama Grup `#grup-nama-baru` | text, required, maxlength 60 | — | ❌ HILANG |
| Info | "X · N anggota ikut pindah" (`grup-nama-lama`, `grup-nama-jumlah`) | — | ❌ HILANG |
| Tampilkan Iklan `#grup-nama-iklan` | toggle, "Berlaku utk seluruh anggota grup" → `PUT /api/admin/groups/{nama}/ads` | — | ❌ HILANG |
| Cancel / Save Group Name | — | — | ❌ HILANG |

---

## 5. TAB 3 — Camera Access (`admin-console.php:308-361`, `admin.js:2217-2660`)

Judul: "Camera Access" · Deskripsi: "Atur kamera mana yang dapat dilihat tiap grup dan akun".

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Tombol "Add Access" | `window.bukaAksesKamera()` → modal akses per akun | `access/page.tsx` "Kelola" per baris | ⚠️ BERBEDA (tidak ada tombol tambah akses global) |
| Toggle "Per Grup" / "Per Kamera" `#akses-arah-akun`, `#akses-arah-kamera` | `gantiArahAkses('grup'/'kamera')` — **arah default: Per Grup** | V3: "Per akun" / "Per kamera" | ⚠️ BERBEDA (V2 berbasis GRUP PENGGUNA; V3 berbasis akun — konsep grup pengguna tak ada di V3) |
| Search `#akses-cari` | placeholder "Cari…", `renderIkhtisarAkses()` | `access/page.tsx:108` "Cari…" | ✅ ADA |
| Tabel: No / Account / Role / Cameras / Actions | kolom dinamis (`akses-kol-1`, `akses-kol-2`) | V3: tabel akun → Kelola; tabel kamera → Kelola | ✅ ADA (setara) |
| Aksi "ATUR" per baris grup | `bukaAksesGrup(grup)` | — | ❌ HILANG (grup pengguna) |
| Aksi "Atur" per baris akun | `bukaAksesKamera(user_id)` → `#akses-modal` | `access/page.tsx:144` "Kelola" | ✅ ADA |
| Aksi "ATUR" per baris kamera (mode Per Kamera) | `bukaBerbagiKamera(stream_id)` → `#berbagi-modal` | `access/page.tsx:194` "Kelola" + baris Tamu | ✅ ADA |

### 5.1 Modal `#akses-modal` — Camera Access per akun (`modals.php:388-471`)

| Field V2 | Detail | File V3 | Status |
|----------|--------|---------|--------|
| Akun `#akses-modal-akun` | select "Pilih akun" → `muatKameraAkses()` | V3: pilih user di tabel | ✅ ADA (setara) |
| Mode tetap `#akses-modal-akun-tetap` | nama akun read-only (dropdown disembunyikan tapi nilainya dipakai) | — | ❌ HILANG (detail implementasi; fungsi terwakili) |
| Cari kamera `#akses-modal-cari` | "Cari kamera…" → `saringKameraAkses()` | V3? | ⚠️ PERLU CEK |
| Daftar kamera | checkbox per kamera + kolom **LIVE / REKAMAN / BAGIKAN** (`akses-kol-a/b/c`) | V3 modal Kelola: checkbox kamera | ⚠️ BERBEDA — V2 punya 3 kolom izin (live, rekaman, bagikan); V3 hanya on/off akses |
| Badge hitung `#akses-modal-hitung` | jumlah kamera dipilih | — | ❌ HILANG |
| Cancel / Simpan Akses | `simpanAksesKamera()` | ✅ | ✅ ADA |

### 5.2 Modal `#berbagi-modal` — Camera Sharing per kamera (`modals.php:330-386`, `admin.js:2451-2614`)

| Field V2 | Detail | File V3 | Status |
|----------|--------|---------|--------|
| Bagian Grup (read-only) `#berbagi-grup-bagian` | daftar grup pemegang kamera + hint "Grup memegang kamera lewat Admin pemiliknya; ubah di baris grup." | — | ❌ HILANG (grup pengguna) |
| Cari akun `#berbagi-cari` | "Cari akun…" → `saringBerbagi()` | V3 ShareModal? | ⚠️ PERLU CEK |
| Daftar akun | per akun: toggle **Lihat** + toggle **Rekaman** (`ubahBerbagi(user_id, 'view'/'playback')`) | V3 `ShareModal.tsx` | ⚠️ PERLU CEK — V2 pisah izin lihat vs rekaman per akun |
| Badge hitung `#berbagi-hitung` | jumlah akun berakses | — | ❌ HILANG |
| Batal / Simpan | `simpanBerbagiKamera()` | ✅ | ✅ ADA |

### 5.3 Modal `#permissions-modal` — CCTV Access Mapping (`modals.php:275-310`)

| Field V2 | Detail | File V3 | Status |
|----------|--------|---------|--------|
| Judul dinamis `#permissions-modal-title` | "CCTV Access Mapping" / "Kamera yang boleh dilihat akun ini" | — | ⚠️ fungsi digabung ke modal Kelola V3 |
| Daftar kamera checkbox `#permissions-camera-list` | `saveUserPermissions()` | ✅ | ✅ ADA (setara) |
| Cancel / Save Permissions | — | ✅ | ✅ ADA |

---

## 6. TAB 4 — Camera Scanner (`admin-console.php:363-463`)

Judul: "Camera Scanner" · Deskripsi: "Parameter scan jaringan lokal untuk kamera RTSP".

### 6.1 Form `#scanner-form` → `handleStartScan(event)` → `POST /api/admin/scan`

| Field V2 | Tipe & aturan | File V3 | Status |
|----------|---------------|---------|--------|
| IP Subnet Range (CIDR) `#scan-ip-range` | text, **required**, default "192.168.1.0/24", hint "Contoh: 192.168.1.0/24, 10.0.0.0/24" | `scanner/page.tsx:142` | ✅ ADA |
| Target Port (RTSP) `#scan-port` | number, **required**, min 1 max 65535, default 554 | `scanner/page.tsx:150` | ✅ ADA |
| Default Username `#scan-username` | text, required, default "admin" | `scanner/page.tsx:170` | ✅ ADA |
| Default Password `#scan-password` | text, required, default "admin" | `scanner/page.tsx:177` | ✅ ADA |
| Codec / Stream Path `#scan-codec` | text, required, default "H.264", hint "Suffix URL RTSP (e.g. H.264, stream1)" | — | ❌ HILANG |
| Default Coordinates `#scan-coordinates` | text, placeholder "-6.2095, 106.8456" | — | ❌ HILANG |
| Tombol "Scan Network" `#start-scan-btn` | submit full-width | `scanner/page.tsx:187` | ✅ ADA |
| Progress bar | `#scan-progress-label` ("Scanner Idle"), `#scan-progress-percent`, `#scan-progress-bar` | V3: "Memindai…" | ⚠️ BERBEDA (V3 tanpa persen progres) |

### 6.2 Tabel hasil `#scan-results-card` — "Discovered Camera Feeds"

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Kolom: checkbox select-all `#scan-select-all` | `toggleSelectAllScanned` | ✅ | ✅ ADA |
| Kolom IP Address / Port / Credentials / RTSP Target URL / Actions | — | V3: IP / Port / Merek / URL Stream | ⚠️ BERBEDA (V3 tambah kolom Merek, tak ada kolom Credentials & kolom Actions) |
| Tombol "+ Add Selected (n)" `#add-selected-cams-btn` | `addSelectedScannedCameras()` → **buka `#bulk-add-modal`** | V3: "+ Tambah terpilih (n)" langsung tambah | ⚠️ BERBEDA (tanpa modal bulk-add) |
| Aksi per baris hasil scan | (tambah satu per satu) | — | ❌ HILANG (kolom Actions tak ada di V3) |

### 6.3 Modal `#bulk-add-modal` — Bulk Add CCTV Config (`modals.php:527-600`)

| Field V2 | Detail | File V3 | Status |
|----------|--------|---------|--------|
| Kelompokkan ke dalam Grup `#bulk-enable-grouping` | checkbox, default checked → toggle input grup | — | ❌ HILANG |
| Nama Grup Kamera `#bulk-stream-group` | text, required, default "Scanned", + datalist | — | ❌ HILANG |
| Koordinat `#bulk-stream-coordinates` | text, opsional | — | ❌ HILANG |
| Tipe Penamaan `#bulk-naming-mode` | select 3 opsi: "Penamaan Asli (contoh: Kamera 192.168.36.242)" / "Nama Kustom + IP (contoh: Lobi - 192.168.36.242)" / "Nama Kustom + Nomor Urut (contoh: Lobi 1, Lobi 2, ...)" | — | ❌ HILANG |
| Nama Kustom (Prefix) `#bulk-naming-prefix` | text, muncul bila mode prefix, "e.g., Lobi Depan" | — | ❌ HILANG |
| Cancel / Tambahkan Kamera | `handleBulkAddSubmit(event)` | — | ❌ HILANG |

### 6.4 Modal `#bulk-coords-modal` — Bulk Edit Coordinates (`modals.php:604-637`)

| Field V2 | Detail | File V3 | Status |
|----------|--------|---------|--------|
| Koordinat Baru `#bulk-cctv-coordinates` | text, **required**, "e.g., -6.2095, 106.8456" | V3: "Set koordinat" massal dgn Latitude+Longitude | ✅ ADA (setara) |
| Info target `#bulk-coords-target-count` | "diterapkan ke N kamera terpilih" | — | ❌ HILANG (teks hitungan) |
| Cancel / Simpan Koordinat | `handleBulkCoordsSubmit(event)` | ✅ | ✅ ADA |

---

## 7. TAB 5 — Ad Space Config (`admin-console.php:465-660`)

Judul: "Ad Space Config" · Deskripsi: "Atur gambar dan teks berjalan pada popup guest". Submit → `window.handleSaveAdConfig(event)`.

### 7.1 Live Preview (`admin-console.php:472-509`)

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Mock monitor 16:9 gelap | label "Live Preview (Pratinjau Langsung)" + badge "Widescreen Monitor (16:9)" | `ads/page.tsx:94` | ✅ ADA |
| Chip kamera "📹 LOBBY UTAMA - LIVE" + dot hijau pulse | — | `ads/page.tsx:103` "LOBBY UTAMA - LIVE" | ✅ ADA |
| Indikator "● REC" merah ping | — | `ads/page.tsx:108` | ✅ ADA |
| Jam mock `#preview-mock-time` | **berjalan real-time** (`setInterval` 1 detik) | `ads/page.tsx:113` (statis?) | ⚠️ PERLU CEK — jam berjalan vs statis |
| Banner overlay `#ad-preview-banner` | lower-third, update **real-time** tiap input (`updateAdPreview`) | V3 preview reaktif | ✅ ADA |

### 7.2 Semua 16 pengaturan (skema `AdConfigSchema`, backend `main.py:1671`)

| # | Field V2 | Kontrol & batas | File V3 | Status |
|---|----------|-----------------|---------|--------|
| 1 | Status Penayangan Iklan `#ad-active` | toggle ("Tampilkan space iklan ini di video stream guest") | `ads/page.tsx:355` | ✅ ADA |
| 2 | Lebar Wadah Iklan `#ad-box-width` | range **10–100** (%), default 100 | ✅ | ✅ ADA |
| 3 | Posisi Aliran Konten `#ad-text-align` | select: Rata Kiri / Rata Tengah / Rata Kanan | ✅ | ✅ ADA |
| 4 | Warna Latar Belakang `#ad-bg-color` + `#ad-bg-color-text` | color picker + text hex (sinkron 2 arah) | ✅ | ✅ ADA |
| 5 | Transparansi Latar `#ad-bg-opacity` | range **0–100** %, default 100 | ✅ | ✅ ADA |
| 6 | Gambar Sponsor `#ad-image-file` + `#ad-image-url` | file picker (accept image/*) + **atau** tempel URL; preview `#ad-image-preview` / placeholder "Tidak ada gambar" | ✅ | ✅ ADA |
| 7 | Transparansi Logo `#ad-image-opacity` | range **0–100** %, default 100 | `ads/page.tsx:457` | ✅ ADA |
| 8 | Tinggi Ukuran Logo `#ad-image-size` | range **10–60** px, default 20 | `ads/page.tsx:465` | ✅ ADA |
| 9 | Isi Teks Marquee `#ad-marquee-text` | textarea, **required**, "Ketik kalimat informasi iklan..." | ✅ | ✅ ADA |
| 10 | Warna Teks `#ad-text-color` + `#ad-text-color-text` | color picker + text hex | ✅ | ✅ ADA |
| 11 | Jenis Font `#ad-font-family` | select **6 opsi**: Monospace / Sans-Serif / Serif / Cursive / Arial / Courier | ✅? | ⚠️ PERLU CEK — 6 opsi font di V3 |
| 12 | Ukuran Font `#ad-font-size` | range **8–24** px, default 10 | ✅ | ✅ ADA |
| 13 | Kecepatan `#ad-scroll-speed` | range **1–10**, default 5 | ✅ | ✅ ADA |
| 14 | Transparansi Teks `#ad-text-opacity` | range **0–100** %, default 100 | ✅ | ✅ ADA |
| 15 | `embed_timeout_seconds` | **tidak di tab ini** — di Embed Player Settings (lihat §8.1) | V3: di Pengaturan Embed Player | ✅ ADA |
| 16 | `click_to_play` | **tidak di tab ini** — di Embed Player Settings | V3: di Pengaturan Embed Player | ✅ ADA |
| — | Tombol "Simpan Konfigurasi Iklan" | submit full-width | ✅ | ✅ ADA |

---

## 8. TAB 6 — API Integration (`admin-console.php:662-1003`)

### 8.1 Embed Player Settings (`admin-console.php:664-712`) → `window.handleSaveEmbedConfig(event)`

| Field V2 | Kontrol & batas | File V3 | Status |
|----------|-----------------|---------|--------|
| Click to Play `#embed-click-to-play` | toggle, default **checked** ("Wajib klik tombol Play untuk mulai memutar video") | `keys/page.tsx:457` "Pengaturan Embed Player" | ✅ ADA |
| Batas Waktu Pemutaran `#embed-timeout-seconds` | number **min 10 max 86400**, default 300, placeholder "Default: 300 (5 menit)", **label deskriptif live** ("5.0 Menit" / "X Jam" / "Nonaktif") | V3: input detik | ⚠️ BERBEDA — V3 tanpa label konversi live (menit/jam/nonaktif) |
| Tombol "Simpan Pengaturan Embed" | submit | ✅ | ✅ ADA |

### 8.2 Tabel API Keys (`admin-console.php:714-755`, render `core.js:411-560`)

Kolom: **Client / Camera | Security | API Key & Embed URL | Actions**.

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Kolom Client/Camera | nama klien bold; `[Kustom] custom_camera_name`; chips kamera (utama = highlight biru, tooltip "Kamera utama (dipakai bila URL tanpa parameter camera)" / "Akses via ?camera=N") | V3: kartu per key (nama, badge Aktif, "N kamera", domain, "Tanpa playback", "Nama kustom") | ⚠️ BERBEDA (tabel → kartu; chips kamera per key tak ada di V3) |
| Kolom Security | badge domain (🔑 DOMAIN / 🌐 PUBLIC); badge password (🔒 PASSWORD / 🔓 NO PASSWORD); badge "📷 N KAMERA"; badge ▶ PLAYBACK / LIVE SAJA | V3: badge domain + "Tanpa playback" | ⚠️ BERBEDA (badge password & hitungan kamera tak ada) |
| Kolom API Key & Embed URL | kode key (select-all) + **tombol salin**; tombol **"Cara Set"** (`openApiSetupModal`) | V3: "Salin key ini sekarang — tidak akan ditampilkan lagi." (hanya saat create) | ⚠️ BERBEDA — V2 key selalu tampil + bisa disalin ulang; V3 hanya sekali saat buat |
| Kolom Actions | **Test Player** (link embed.php?key=...&pass=..., tab baru) | — | ❌ HILANG |
| | **Edit** (`openApiKeyEditModal`) | — | ❌ HILANG (V3 hanya Aktifkan/Nonaktifkan + Hapus) |
| | **Revoke** (`handleRevokeApiKey`) + konfirmasi | V3: "Hapus" | ✅ ADA (setara) |
| Tombol "+ Generate API Key Baru" | `openApiKeyGenerateModal()` | V3: "+ API key" (KeyFormModal) | ✅ ADA |

### 8.3 Modal Generate/Edit API Key (`modals.php:700-897`)

| Field V2 | Tipe & aturan | File V3 | Status |
|----------|---------------|---------|--------|
| Nama Klien `#api-client-name` | text, required, "Contoh: Server A, Website Dinas" | `keys/page.tsx` KeyFormModal | ✅ ADA |
| Judul Kamera Kustom `#api-custom-camera-name` | text opsional, "Untuk menyamarkan nama asli" | `keys/page.tsx:636` | ✅ ADA |
| Batasi Domain `#api-allowed-domain` | text opsional, "Kosongkan jika ingin PUBLIC", hint "iframe hanya bisa diputar dari domain tersebut" | `keys/page.tsx:663` "Kunci domain (opsional)" | ✅ ADA |
| Password `#api-secret-pass` | text opsional, hint "pemanggil wajib menambahkan parameter &pass=... pada url" | `keys/page.tsx:600` | ✅ ADA |
| Pilih Kamera | checklist + **search** (`api-cam-search`) + tombol **Semua/Kosong** + hitungan "N dipilih" | V3: checklist kamera | ⚠️ PERLU CEK — tombol Semua/Kosong & search di V3 |
| Urutan Kamera `#api-order-wrap` | daftar urutan (naik/turun), hint "Klien memanggil &camera=1, &camera=2... Nomor 1 = kamera utama" | `keys/page.tsx:603` `ordered` | ✅ ADA |
| Sertakan playback `#api-include-playback` | toggle ("Klien boleh melihat rekaman kamera di atas") | `keys/page.tsx:602` | ✅ ADA |
| Hint kamera utama | "Kamera pertama yang dicentang menjadi kamera utama (dipakai bila URL tanpa parameter camera)." | — | ❌ HILANG (teks penjelasan) |
| Generate/Edit/Cancel | `handleGenerateApiKey` / `handleUpdateApiKey` | ✅ | ✅ ADA |

### 8.4 Modal API Integration Guide — `#api-setup-modal` (`modals.php:639-700`)

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Security notice `#api-setup-security-notice` | peringatan domain/password per key | — | ❌ HILANG |
| Ringkasan 4 stat | Kamera / Playback / Domain / Sandi (`api-setup-stat-cam` dkk) | — | ❌ HILANG |
| Mode Stream Langsung / Rekaman | `setApiSetupMode('stream'/'playback')` — semua contoh URL mengikuti mode | — | ❌ HILANG |
| Pilih Kamera (tabs) | `&camera=NOMOR` per kamera | — | ❌ HILANG |
| Metode 1: iframe + "Salin Code" | kode `<iframe>` 640x360 | V3: "Metode 1 — Kode iframe" + Salin | ✅ ADA |
| Metode 2: REST API JSON + "Salin URL" | `GET /api/external/stream?key=` | V3: "Metode 2 — URL REST API" | ✅ ADA |
| Metode 3: URL Pemutar Langsung + "Salin URL" | embed.php direct | V3: "Metode 3 — URL pemutar langsung" | ✅ ADA |
| Tombol Close | — | ✅ | ✅ ADA |
| **Konteks per-key** | V3 modal generik (key ditempel manual); V2 dibuka per key ("Cara Set") dgn key terisi | `keys/page.tsx:552` | ⚠️ BERBEDA |

### 8.5 API Access Log (`admin-console.php:758-1001`)

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Filter key `#api-log-filter-key` | "Semua Kunci" + daftar key (`loadApiAccessLogs()`) | `keys/page.tsx:275` "Filter key" | ✅ ADA |
| Filter status `#api-log-filter-status` | "Semua Status" / "HIT saja" / "DENIED saja" | `keys/page.tsx:285` "Filter status" | ✅ ADA |
| Tombol Refresh | `loadApiAccessLogs()` | `keys/page.tsx:261` "Muat ulang" | ✅ ADA |
| Tombol Hapus Log | `clearApiAccessLogs()` | `keys/page.tsx:268` "Hapus semua log" | ✅ ADA |
| Kartu statistik | **Total Akses / HIT / DENIED / IP Unik** (`log-stat-total/hits/denied/ips`) | — | ❌ HILANG (4 kartu statistik) |
| Kolom tabel | Time / Client / Camera / Source IP / Referer / Domain / Status / Details | V3: Waktu + kolom lain | ⚠️ PERLU CEK kolom persis V3 |
| Tombol "Muat 100 Log Lebih" `#api-log-load-more` | `loadMoreApiAccessLogs()` (offset) | `keys/page.tsx:356` "Muat lebih banyak" | ✅ ADA |
| Label hitungan `#api-log-count-label` | "Menampilkan N dari M" | — | ❌ HILANG |
| Auto-refresh 30 detik | "Log diperbarui otomatis setiap 30 detik saat tab ini aktif." | — | ❌ HILANG |

---

## 9. Modal Peta — `#map-modal` (`modals.php:474-525`)

| Elemen V2 | Detail | File V3 | Status |
|-----------|--------|---------|--------|
| Judul "Camera Location" + grup + koordinat | `#map-modal-title/group/coords` | — | ❌ HILANG (tak ada modal peta per kamera di V3) |
| Peta Leaflet 400px `#camera-leaflet-map` | OpenStreetMap, scroll zoom / drag pan | V3 punya halaman maps | ⚠️ BERBEDA (halaman ≠ modal per kamera) |
| Tombol "Google Maps" `#map-gmaps-link` | link eksternal bila ada koordinat | — | ❌ HILANG |
| Footer atribusi OSM | — | — | ❌ HILANG |

---

## 10. Ringkasan Paritas (Zero Deprecation Checklist)

### 10.1 Rekapitulasi hitungan

| Kategori | Elemen V2 diinventarisasi | ✅ ADA | ⚠️ BERBEDA / PERLU CEK | ❌ HILANG |
|----------|---------------------------|--------|------------------------|-----------|
| Struktur tab | 6 tab + 4 badge | 6 | 1 (badge angka tab) | 0 |
| Tab Streams (toolbar+filter+bulk) | 8 | 8 | 0 | 0 |
| Tabel streams (9 kolom + 4 aksi + pagination) | 14 | 11 | 2 (page-size, disabled super_admin) | 2 (View, Map) |
| Modal kamera (11 field + 2 tombol) | 13 | 10 | 2 (grup datalist, koordinat) | 2 (Save to Disk, path preview) |
| Tab Users (tabel grup + 5 kolom + 2 aksi) | 8 | 5 | 0 | 3 (baris grup, edit grup, —) |
| Modal user (8 field) | 8 | 4 | 2 (password required/edit, 4 opsi role) | 2 (grup pengguna, nama grup baru) |
| Modal rename group (4) | 4 | 0 | 0 | 4 |
| Tab Access (7) | 7 | 4 | 2 (Add Access, arah grup) | 1 (aksi grup) |
| Modal akses/berbagi/permissions (3 modal, 14 field) | 14 | 7 | 4 | 3 |
| Tab Scanner (7 field + progres) | 8 | 5 | 1 (progres %) | 2 (codec, koordinat default) |
| Tabel hasil scan (6) | 6 | 3 | 2 | 1 (aksi per baris) |
| Modal bulk-add (6) | 6 | 0 | 0 | 6 |
| Modal bulk-coords (3) | 3 | 2 | 0 | 1 (teks hitungan) |
| Tab Iklan (preview 5 + 16 field) | 21 | 18 | 2 (jam mock, 6 font) | 0 |
| Embed settings (3) | 3 | 2 | 1 (label live) | 0 |
| Tabel API key (4 kolom + 3 aksi + tombol) | 8 | 3 | 3 | 2 (Test Player, Edit key) |
| Modal key generate/edit (9) | 9 | 7 | 1 | 1 (hint kamera utama) |
| Modal panduan integrasi (8) | 8 | 4 | 1 | 3 (notice, stat, mode+kamera) |
| Log akses (9) | 9 | 5 | 1 (kolom) | 3 (stat, hitungan, auto-refresh) |
| Modal peta (4) | 4 | 0 | 1 | 3 |
| **TOTAL** | **≈ 175** | **≈ 104** | **≈ 24** | **≈ 47** |

### 10.2 Daftar ❌ HILANG prioritas (wajib dipulihkan per aturan Zero Deprecation)

**Kritis (fitur inti):**
1. Baris grup pengguna (collapsible) + modal Rename Group + toggle iklan per grup — *arsitektur grup pengguna V2 tidak ada di V3*
2. Modal Bulk Add CCTV Config (6 field: grouping, nama grup, koordinat, 3 mode penamaan, prefix)
3. Edit API Key (V3 hanya buat + hapus)
4. Test Player per API key
5. Kolom "Save to Disk" + preview recording path di modal kamera
6. Aksi View & Map per baris kamera (+ modal peta per kamera dgn link Google Maps)
7. Field Codec/Stream Path & Default Coordinates di form Scanner
8. Kolom Aksi per baris hasil scan

**Sedang:**
9. Kartu statistik log (Total/HIT/DENIED/IP Unik) + label hitungan + auto-refresh 30 dtk
10. Security notice + ringkasan stat + mode stream/playback + pilih kamera di Panduan Integrasi
11. Kolom izin LIVE/REKAMAN/BAGIKAN di modal akses (V3 hanya on/off)
12. Toggle Lihat/Rekaman per akun di modal sharing + badge hitungan
13. Badge angka di tab navigasi admin

**Ringan (kosmetik/teks):**
14. Jam mock berjalan di preview iklan, label konversi live di timeout embed, hint kamera utama, teks hitungan bulk-coords, badge password/kamera di tabel key, key tampil permanen + salin ulang

### 10.3 Catatan struktural

- **Grup pengguna V2** (`users.admin_group`, grup collapsible, rename grup, iklan per grup, akses per grup) adalah konsep yang **tidak ada padanannya** di V3 — ini sumber HILANG terbesar (±15 elemen). Bila dipulihkan, butuh model `user_groups` + migrasi.
- **Tab Drive/Penyimpanan V3** adalah penambahan baru (tidak ada di V2 `/tmp/v2-ref`) — tidak melanggar aturan.
- Elemen bertanda ⚠️ PERLU CEK membutuhkan verifikasi langsung di browser/demo sebelum dinyatakan final.
