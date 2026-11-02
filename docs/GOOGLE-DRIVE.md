# Google Drive untuk Rekaman — Panduan Setup

Modul **opsional** (default nonaktif). Bila diaktifkan, segmen rekaman
diunggah ke Google Drive dengan struktur folder:

```
NetraVision/
  <nama-kamera>/
    2026-11-02_10-00-00-000000.mp4
    ...
```

Alur tetap: **segmen selalu ditulis lokal dulu** (buffer), lalu worker
async mengunggah ke Drive (resumable + retry 3x). Playback segmen Drive
di-proxy lewat backend — pemutar tidak peduli segmennya di lokal/Drive.

**Multi-akun (v3.0):** tiap kamera bisa menunjuk akun Google berbeda.
Kamera A → akun A, kamera B → akun B. Kamera tanpa akun eksplisit memakai
**akun default**. Akun dikelola di Admin → Drive (tambah, re-auth, hapus)
— tidak perlu lagi copy-paste `token.json` manual.

## 1. Buat OAuth Client di Google Cloud Console

1. Buka https://console.cloud.google.com/ → pilih/buat project.
2. **APIs & Services → Library** → aktifkan **Google Drive API**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External**, isi nama aplikasi + email.
   - Tambahkan scope: `https://www.googleapis.com/auth/drive.file`
     (hanya file yang dibuat aplikasi ini — paling aman).
   - Tambahkan **Test users**: akun-akun Google yang akan dipakai
     (selama app berstatus Testing).
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**, beri nama mis. "NetraVision Uploader".
   - **Authorized redirect URIs**: tambahkan
     `https://netra.mamura.net.id/api/admin/drive-accounts/oauth/callback`
     (satu URI untuk semua akun — ganti domain sesuai `PUBLIC_BASE_URL`).
   - Download JSON → simpan sebagai `data/drive/credentials.json` di server.
     File ini **rahasia** — jangan di-commit (sudah di .gitignore via `data/`).

## 2. Tambah akun Drive (via Admin UI)

1. Buka Admin → Drive → **Tambah akun**, isi nama mis. "Akun Gudang".
2. Klik link otorisasi yang muncul → login dengan akun Google yang diinginkan
   → setujui akses Drive.
3. Browser kembali ke Admin → Drive dengan status **connected**.
4. Ulangi untuk akun kedua/ketiga (login dengan akun Google yang berbeda).

Token OAuth tiap akun disimpan **terenkripsi (Fernet)** di database —
lihat §5 soal `DRIVE_TOKEN_KEY`.

## 3. Pilih akun per kamera

Di Admin → Kamera → Edit: `drive_account_id` = akun yang diinginkan
(kosong = akun default). Atau via API:

```bash
PUT /api/admin/streams/12  {"drive_account_id": "<uuid-akun>"}
PUT /api/admin/streams/12  {"drive_account_id": null}   # kembali ke default
```

Atur satu akun sebagai default di Admin → Drive → **Jadikan default**.

## 4. Aktifkan di NetraVision

```bash
# deploy/.env
DRIVE_ENABLED=true
DRIVE_TOKEN_KEY=<hasil-generate-di-§5>
```

Lalu `deploy/update.sh`. Worker akan (per akun, paralel):
- membuat folder `<root>/<nama-kamera>/` otomatis
  (atau memakai `root_folder_id` bila diisi manual per akun),
- mengunggah segmen baru (melewati yang sudah ada),
- menghapus file Drive lebih tua dari `DRIVE_RETENTION_DAYS` (default 30).

Di Admin → Kamera → Edit: `storage_mode` = `local` | `drive` | `both`.
`drive`/`both` + `DRIVE_ENABLED=false` = tetap lokal saja (aman).

## 5. DRIVE_TOKEN_KEY — generate & rotasi

Generate sekali (simpan baik-baik, seperti password):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Masukkan ke `deploy/.env` sebagai `DRIVE_TOKEN_KEY`. **Jangan di-commit.**

Rotasi key (bila bocor): akun-akun yang ada harus **re-auth**
(Admin → Drive → Re-auth per akun) setelah key baru dipasang, karena
token lama tak bisa didekripsi dengan key baru. Selama belum re-auth,
kamera-kamera akun itu otomatis nonaktif Drive-nya (tetap rekam lokal).

## 6. Migrasi dari instalasi satu-akun lama

Instalasi lama (`data/drive/token.json`) **tetap jalan tanpa perubahan**
— token file dipakai sebagai fallback selama belum ada akun terhubung
di database. Untuk pindah ke manajemen multi-akun: tambah akun via
Admin UI (login ulang dengan akun Google yang sama), lalu hapus/abaikan
`token.json` lama.

## Batasan jujur

- Butuh bandwidth upload server yang cukup (segmen 1 jam ≈ ratusan MB).
- Kuota: Google Drive API punya batas harian; untuk puluhan kamera,
  pertimbangkan `drive` hanya untuk kamera penting, sisanya `local`.
- Scope `drive.file` hanya melihat file buatan aplikasi ini — file lain
  di Drive-mu tidak tersentuh.
- Rate limit uploader bersifat per-proses (seperti modul auth).
