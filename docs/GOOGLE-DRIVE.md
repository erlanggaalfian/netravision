# Google Drive untuk Rekaman — Panduan Setup

Modul **opsional** (default nonaktif). Bila diaktifkan, segmen rekaman
diunggah ke Google Drive milikmu dengan struktur folder:

```
NetraVision/
  <nama-kamera>/
    2026-11-02_10-00-00-000000.mp4
    ...
```

Alur tetap: **segmen selalu ditulis lokal dulu** (buffer), lalu worker
async mengunggah ke Drive (resumable + retry 3x). Playback segmen Drive
di-proxy lewat backend — pemutar tidak peduli segmennya di lokal/Drive.

## 1. Buat OAuth Client di Google Cloud Console

1. Buka https://console.cloud.google.com/ → pilih/buat project.
2. **APIs & Services → Library** → aktifkan **Google Drive API**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External**, isi nama aplikasi + email.
   - Tambahkan scope: `https://www.googleapis.com/auth/drive.file`
     (hanya file yang dibuat aplikasi ini — paling aman).
   - Tambahkan **Test users**: akun Google milikmu (selama app berstatus Testing).
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Desktop app**, beri nama mis. "NetraVision Uploader".
   - Download JSON → simpan sebagai `data/drive/credentials.json` di server.
     File ini **rahasia** — jangan di-commit (sudah di .gitignore via `data/`).

## 2. Otorisasi pertama (buat token.json)

Di server (atau mesin mana pun dengan akses), jalankan sekali:

```bash
pip install google-api-python-client google-auth-oauthlib
python - <<'EOF'
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file(
    "data/drive/credentials.json",
    ["https://www.googleapis.com/auth/drive.file"],
)
creds = flow.run_local_server(port=0)
open("data/drive/token.json", "w").write(creds.to_json())
print("OK — token.json tersimpan")
EOF
```

Browser akan meminta login + persetujuan akses Drive. `token.json`
berisi refresh token (berlaku lama, auto-refresh oleh aplikasi).

## 3. Aktifkan di NetraVision

```bash
# deploy/.env
DRIVE_ENABLED=true
```

Lalu `deploy/update.sh`. Worker akan:
- membuat folder `NetraVision/<nama-kamera>/` otomatis,
- mengunggah segmen baru (melewati yang sudah ada),
- menghapus file Drive lebih tua dari `DRIVE_RETENTION_DAYS` (default 30).

## 4. Per kamera

Di Admin → Kamera → Edit: `storage_mode` = `local` | `drive` | `both`.
`drive`/`both` + `DRIVE_ENABLED=false` = tetap lokal saja (aman).

## Batasan jujur

- Butuh bandwidth upload server yang cukup (segmen 1 jam ≈ ratusan MB).
- Kuota: Google Drive API punya batas harian; untuk puluhan kamera,
  pertimbangkan `drive` hanya untuk kamera penting, sisanya `local`.
- Scope `drive.file` hanya melihat file buatan aplikasi ini — file lain
  di Drive-mu tidak tersentuh.
