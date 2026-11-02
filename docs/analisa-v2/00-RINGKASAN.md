# Ringkasan Analisa Mendalam V2 → V3 (Zero Deprecation)

Tanggal: 2026-11-02. Sumber V2: https://github.com/erlanggaalfian/cctv-monitoring.git (commit 62458bb).
Laporan detail: `01-halaman-operator.md`, `02-konsol-admin.md`, `03-alur-interaksi.md`,
`04-fungsional-backend.md`, `05-detail-antarmuka.md`.

## Angka keseluruhan

| Laporan | Diinventarisasi | ADA | BERBEDA | HILANG |
|---|---|---|---|---|
| 01 Halaman operator | 118 elemen | 44 | 25 | 42 |
| 02 Konsol admin | 175 elemen | 104 | 24 | 47 |
| 03 Alur & interaksi | 105 alur | 22 | 47 | 36 |
| 04 Fungsional backend | 52 endpoint | 28 | 18 | 18 |
| 05 Detail antarmuka | 391 detail | 97 | 181 | 113 |

(Catatan: 05 mengulang 01/02 pada level detail — angka tidak dijumlah mentah.)

## Yang HILANG — prioritas kritis

**Operator:**
- Navigasi Prev/Next kamera di popup + keyboard shortcut (Esc/F/T/M/Spasi/←/→)
- Kontrol Play/Pause kustom, mute/unmute, pilihan kualitas LQ/HQ, mode teater, fullscreen modal
- "Coba Hubungkan Paksa" untuk kamera offline; auto-reconnect WebRTC (retry 4×)
- Transport playback lengkap (±30 detik, scrub timeline + playhead, jam presisi detik, lompat & lanjut otomatis antar-segmen)
- Badge CAM_001, pill ONLINE/OFFLINE, badge REC/LOSS, telemetri tile (fps/res/codec)
- Direktori stream di sidebar; cluster marker peta + popup aksi + klik→langsung-live
- Filter grup + pagination di Live/Playback/Monitor/Screen
- Toast global showToast (feedback sukses hilang total)
- Playback eksternal via API key (embed V3 hanya live)

**Admin:**
- Modal Bulk Add CCTV Config, modal Edit API Key, Test Player per key
- Modal Rename Group; arsitektur grup pengguna V2 (toggle iklan per grup, akses per grup)
- Aksi View & Map per baris kamera (+ modal peta + link Google Maps)
- Save to Disk + preview recording path di modal kamera
- Field Codec/Stream Path & Default Coordinates di Scanner
- Kartu statistik log (Total/HIT/DENIED/IP Unik) + auto-refresh 30 detik
- Select Peran tanpa opsi SUPER ADMIN; modal Ubah Kamera tak bisa edit URL RTSP
- Izin granular Berbagi (Lihat/Rekaman/Bagikan per akun)

**Backend:**
- GET / landing HTML; preview scan via MediaMTX (V3 masih TODO)
- restart/persist/resync/cleanup path MediaMTX
- cleanup_blank_posters + request_poster_capture on-demand
- boleh_bagi/can_reshare, boleh_kelola_izin, tolak_guest_baru
- Penegakan boleh_ubah di PUT/DELETE streams; filter boleh_tonton di GET streams (admin non-super)
- record_path/record_disk per kamera; auto-prune access log; pelacakan gagal-login progresif
- Toggle iklan per grup user (path ada, implementasi mati)

## Yang BERBEDA (perlu keputusan, bukan bug)

- Paginasi: limit 9 (V2) → 20/12 (V3); beberapa halaman V3 tanpa paginasi sama sekali
- Guest: baris DB (V2) → ephemeral (V3) — grant individual tamu via role-access
- API key: plaintext (V2) → hash SHA-256 tampil-sekali (V3, disengaja demi keamanan)
- Koordinat: string (V2) → float lat/long (V3)
- Polling 15 detik (V2) → WebSocket (V3, peningkatan)
- confirm() (V2) → ConfirmModal (V3, peningkatan)

## Keputusan yang diminta dari user

1. Perbaiki SEMUA yang hilang (gelombang besar, beberapa putaran)?
2. Atau prioritaskan dulu yang kritis (daftar di atas)?
3. Item BERBEDA yang disengaja (hash API key, WebSocket, ConfirmModal) — tetap seperti V3?
