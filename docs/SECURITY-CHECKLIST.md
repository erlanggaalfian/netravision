# NetraVision v3.0 — Checklist Keamanan

Disusun dari 48 temuan audit v2.0 (4 kritis, 10 tinggi, 15 sedang, 19 rendah —
`~/workspace/cctv-monitoring/AUDIT_DRAFT.md`). **Wajib lolos semua sebelum rilis.**
Bahasa Indonesia. Setiap item merujuk ID temuan aslinya (K/T/S/R).

## 1. Autentikasi & Sesi

- [ ] Tidak ada akun default / password statis saat instalasi; password awal dibuat acak dan hanya dicetak sekali ke log installer, atau wajib diganti saat login pertama (`must_change_password`) (K1)
- [ ] Access token berumur PENDEK + refresh token rotation; ada endpoint logout/revocation yang benar-benar me-revoke di server (T10)
- [ ] Token TIDAK disimpan di `localStorage` — pakai cookie `HttpOnly; Secure; SameSite=Lax` bila memungkinkan (T10)
- [ ] Endpoint publik (mis. guest login) didokumentasikan eksplisit sebagai by-design, diberi rate limit, dan tidak pernah melewati filter hak akses (S4)
- [ ] Logout selalu menyentuh sesi server (revoke), bukan cuma hapus token di klien; logout state-changing tidak lewat GET polos (T10, R9)

## 2. Secret & Kredensial

- [ ] TIDAK ADA secret/password/kredensial di kode, seed, atau file yang di-commit (K1, T7)
- [ ] Semua secret (JWT_SECRET, password DB, dsb.) hanya via environment/vault; tidak ada fallback hardcoded (K1, T7)
- [ ] `secret_pass` API key di-hash (bcrypt) saat simpan, TIDAK PERNAH dikembalikan di respons API, dan tidak dirender di DOM (K2)
- [ ] Kredensial kamera (RTSP berpassword) tidak disimpan di atribut DOM / argumen `onclick`; simpan di struktur data JS internal berdasar id (S15)
- [ ] Seed data memakai placeholder (`rtsp://USER:PASS@...`), bukan kredensial contoh yang bisa dipakai ulang di produksi (T7)
- [ ] API key pihak ketiga (mis. basemap) dibatasi di dashboard penyedia (HTTP referrer) dan dirotasi berkala; idealnya diproxy via backend (R6)

## 3. Otorisasi (RBAC)

- [ ] Setiap endpoint memverifikasi autentikasi + peran di SISI SERVER — tidak ada guard yang hanya JavaScript/CSS (T1)
- [ ] View/komponen admin tidak dikirim ke browser non-admin (bukan sekadar class `hidden`) (T2)
- [ ] Satu tabel otoritatif untuk hak akses kamera (tidak ada dua tabel paralel yang bisa bertentangan); default peran baru = hak paling rendah (S5, S6)
- [ ] Dokumentasi peran sinkron dengan kode (tidak ada peran siluman seperti `super_admin` yang tak terdokumentasi) (R10)

## 4. API Key & Embed Pihak Ketiga

- [ ] Kredensial API key + password TIDAK dikirim via query string; pakai header (`X-API-Key`) atau body POST (T3)
- [ ] Nilai penuh API key tidak pernah ditulis ke log akses / access log server (hash atau mask sebagian) (T3)
- [ ] Embed publik memakai URL sekali-pakai bertanda tangan bila memungkinkan (T3)

## 5. Validasi Input & Output Encoding

- [ ] Semua data dari server di-escape sebelum masuk `innerHTML`/`onclick`/atribut — tanpa kecuali, di semua modul (K3, S10, S11, R14, R17)
- [ ] Validasi panjang & format URL RTSP di backend (kolom DB diperlebar, mis. TEXT/512, agar URL tidak kepotong diam-diam) (R13)
- [ ] Router/navigasi memvalidasi nama halaman (whitelist + fallback aman, bukan halaman kosong) (R15, R7)
- [ ] Tidak ada `eval`/`exec`, tidak ada LFI/path traversal (include dengan path tetap) (catatan positif — pertahankan)

## 6. Database & Migrasi

- [ ] Alembic adalah SATU-SATUNYA sumber kebenaran skema; tidak ada tabel/kolom yang "lahir diam-diam" dari ORM/migrasi runtime (T8)
- [ ] Semua foreign key + indeks didefinisikan di skema/migrasi (tidak hanya ditambal runtime); migrasi yang gagal BERTERIAK, tidak ditelan diam-diam (T9, S9, S7)
- [ ] Semua kolom waktu memakai timezone yang jelas (standar: simpan UTC, konversi hanya di tampilan) (S8)
- [ ] Kolom `role` memakai SATU representasi yang konsisten di skema, migrasi, dan model (R12)
- [ ] Tidak ada kolom copy-paste tak bermakna di tabel (R11)
- [ ] Session/koneksi DB selalu ditutup (`try/finally` atau dependency) — tidak ada kebocoran pool (T4)
- [ ] Akses ke struktur global antar-thread dilindungi lock / struktur thread-safe (T5)
- [ ] Path config & host/port service diambil dari env var (dengan default aman), bukan hardcode; penulisan file config diserialisasi (T6)

## 7. Dependensi & Build

- [ ] SEMUA dependensi di-pin versinya (tidak ada instalasi "terbaru" yang tidak reproducible) (S1, K4)
- [ ] Tidak ada import mati / dependensi yang dipakai tapi tak terdaftar di requirements (K4, R2)
- [ ] Konfigurasi dev vs prod dipisah (mis. `reload=True` tidak bocor ke produksi) (R3)
- [ ] Tidak memakai API deprecated (mis. `datetime.utcnow()` → `datetime.now(timezone.utc)`) (R4)

## 8. Security Headers, CORS & Transport

- [ ] Security header dasar terpasang (X-Content-Type-Options, Referrer-Policy, dsb.) — di vhost Apache (R8)
- [ ] X-Frame-Options/CSP frame-ancestors: SENGAJA tidak global karena /embed harus bisa di-iframe mitra — proteksi framing diatur per API-key (domain lock) di aplikasi
- [ ] CORS memakai allowlist eksplisit, bukan wildcard penuh (S2)

## 9. Logging, Observability & Audit Trail

- [ ] Tidak ada `except` yang menelan error diam-diam — minimal log level warning dengan konteks (S3)
- [ ] `audit_logs`: semua aksi admin tercatat (siapa, apa, kapan) — tidak bisa dimatikan diam-diam (temuan §3.9 blueprint)
- [ ] Logging terstruktur (JSON) agar bisa dipantau; kegagalan registrasi path MediaMTX selalu terdeteksi (S3)

## 10. WebRTC & Media

- [ ] Pembersihan koneksi lengkap: `track.stop()` + `srcObject = null` saat pindah/navigasi (indikator kamera tidak "nyangkut") (S13)
- [ ] Loop statistik hanya jalan saat halaman monitor aktif; `clearInterval` saat navigasi menjauh (S14)
- [ ] ID stream di-parse dengan benar (tidak salah ambil segmen) (S12)
- [ ] Flag auto-reconnect di-reset setelah retry berhasil (R19)

## 11. Praktik Umum

- [ ] Dead code dihapus, bukan dibiarkan membusuk (R1, R18)
- [ ] Handler global tidak redundan/race (mis. dua handler Escape) (R16)
- [ ] CI (lint + typecheck + test + build) hijau sebelum merge — checklist ini diverifikasi ulang tiap rilis Fase
