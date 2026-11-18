# NetraVision v3.0 — Versi Image & Dependensi yang Di-pin

Satu sumber kebenaran untuk versi yang dipakai deployment. Bila menaikkan
versi, ubah di sini DAN di file yang dirujuk, lalu uji dengan
`deploy/update.sh` di staging sebelum produksi.

> Terakhir diverifikasi: 2026-11-18 (tag dicek ada di Docker Hub).

## Image Docker (deploy/docker-compose.yml, apps/api/Dockerfile, apps/web/Dockerfile)

| Komponen | Tag yang di-pin | File |
|---|---|---|
| MediaMTX (ffmpeg) | `bluenviron/mediamtx:1.21.4-ffmpeg` | `deploy/docker-compose.yml:147` |
| PostgreSQL | `postgres:18.1-alpine` | `deploy/docker-compose.yml:19` |
| Redis | `redis:7.4.12-alpine` | `deploy/docker-compose.yml:38` |
| Python (API) | `python:3.13.18-slim` | `apps/api/Dockerfile:1` |
| Node (web build) | `node:20.19.6-alpine` | `deploy/update.sh`, `apps/web/Dockerfile` |
| Alpine (fallback chown) | `alpine:3.21` | `deploy/fix-volume-perms.sh` |

Aturan: **jangan pakai `latest`** untuk komponen yang memegang data /
streaming. Naikkan versi dengan sengaja (PR + smoke test), bukan diam-diam
saat `docker compose pull`.

## Paket sistem di image API (apps/api/Dockerfile)

`ffmpeg` dan `rclone` diinstal via `apt-get` dari snapshot Debian
`python:3.13-slim` (trixie) **tanpa pin versi eksplisit** — sengaja:
`apt-get install ffmpeg=7.*` bukan spesifikasi versi apt yang valid dan
pin eksplisit akan memecahkan build saat snapshot Debian bergeser.
Bila reproduktibilitas penuh dibutuhkan, pin digest image
`python:3.13.18-slim@sha256:...` (digest mengunci snapshot apt).

## Catatan lain

- `WEBRTC_ADDITIONAL_HOST` (tunggal) adalah nama variabel yang benar di
  `deploy/.env`. `README.md:551` menulis `WEBRTC_ADDITIONAL_HOSTS`
  (jamak) — salah ketik di README, di luar cakupan perbaikan ini
  (README tidak diedit); pakai nama tunggal.
- Gate CI: belum ada tag rilis. `deploy/update.sh` mendukung `UPDATE_REF`
  (mis. `UPDATE_REF=v3.1.0`) untuk checkout tag yang sudah lolos CI;
  sampai tag rilis dibuat, update masih menarik branch saat ini.
- `pgdata` di-mount ke `/var/lib/postgresql` (bukan `/var/lib/postgresql/data`)
  dengan sengaja — instalasi lama menyimpan data di `<volume>/data`.
  Jangan ubah tanpa migrasi data.
