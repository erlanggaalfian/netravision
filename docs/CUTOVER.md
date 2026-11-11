# NetraVision v3.0 - Runbook Cutover

Panduan langkah-demi-langkah memindahkan produksi dari v2.0 ("Mamura Stream")
ke v3.0 di server yang sama. **Eksekusi dilakukan di server, sebagai root.**

Aturan keras yang dijaga sepanjang proses:

- Port 80/443 **tetap milik Apache** - tidak ada container yang bind ke sana.
- Database v2.0 (MariaDB) **tidak pernah ditulis** oleh proses migrasi (hanya dibaca).
- Setiap fase punya kriteria **LANJUT** vs **ROLLBACK** yang eksplisit di bawah.

> **Downtime**: dibutuhkan *maintenance window* singkat (±5-15 menit) pada
> Fase F saat vhost dialihkan. Di luar itu v2.0 tetap melayani normal.

Estimasi total: 1-2 jam untuk instalasi + migrasi pertama kali
(tergantung ukuran database dan arsip rekaman).

---

## Fase A - Backup (v2.0 tetap jalan)

- [ ] Dump database v2.0 (MariaDB):
  ```bash
  mkdir -p /backup
  mysqldump -u <v2_user> -p <v2_db> > /backup/netravision-v2-$(date +%Y%m%d).sql
  ls -lh /backup/netravision-v2-*.sql   # pastikan file tidak kosong
  ```
- [ ] Backup arsip rekaman v2.0 (bila di disk yang sama - jangan dipindah, cukup catat):
  ```bash
  du -sh <direktori-rekaman-v2>   # catat ukurannya di sini: ______ GB
  ```
- [ ] Backup vhost Apache aktif untuk netra.mamura.net.id:
  ```bash
  cp /etc/apache2/sites-available/netra.mamura.net.id.conf \
     /etc/apache2/sites-available/netra.mamura.net.id.conf.bak.v2
  ```
- [ ] Catat versi v2.0 yang berjalan: `cd ~/cctv-monitoring && git rev-parse --short HEAD` → `______`

**LANJUT bila**: dump SQL ada dan tidak kosong; file `.bak.v2` ada.
**ROLLBACK**: belum ada yang diubah - cukup ulangi backup yang gagal.

---

## Fase B - Preflight

- [ ] Clone/pull repo v3.0 di server (atau salin dari workstation):
  ```bash
  git clone https://github.com/erlanggaalfian/netravision.git /opt/netravision
  cd /opt/netravision
  ```
- [ ] Pastikan Apache berjalan (preflight menuntut 80/443 di-listen Apache;
  server baru yang apache2-nya terinstal tapi belum jalan akan gagal):
  ```bash
  sudo systemctl enable --now apache2
  ```
- [ ] Jalankan preflight:
  ```bash
  python3 scripts/preflight.py
  ```
- [ ] Semua cek berstatus OK. Catatan: konflik UDP 8189 kini GAGAL
  (bukan peringatan) - bila mediamtx v2.0 masih jalan, hentikan dulu
  (`sudo systemctl stop mediamtx`) atau biarkan install.sh menghentikannya
  di Fase C; preflight memastikan port benar-benar bebas sebelum `compose up`.

**LANJUT bila**: exit code 0, tidak ada `[ GAGAL ]`.
**ROLLBACK**: belum ada yang diubah - perbaiki item yang gagal, ulangi.

---

## Fase C - Install

- [ ] Jalankan (butuh root; estimasi 10-30 menit - dominan download image Docker):
  ```bash
  sudo ./deploy/install.sh
  ```
  Skrip ini: pastikan Apache jalan → preflight ulang → siapkan `.env`
  (termasuk generate `DRIVE_TOKEN_KEY` bila kosong) → hentikan mediamtx
  v2.0 (melepas UDP 8189) → `compose up` → tunggu Postgres →
  migrasi Alembic → siapkan file vhost v3.0 (BELUM diaktifkan) →
  health check.
  v2.0 TETAP melayani selama Fase C: pergantian vhost baru terjadi di
  Fase F (maintenance window).
- [ ] (Opsional tapi disarankan) buat admin awal:
  ```bash
  sudo NV_ADMIN_USER=admin NV_ADMIN_PASS='<rahasia-kuat>' ./deploy/install.sh
  ```
  Tanpa env tersebut, langkah seed dilewati dengan pesan (bisa dibuat belakangan
  via API atau dengan menjalankan ulang install.sh - idempoten).

**LANJUT bila**: di akhir ada `GET /api/health -> OK`.
**ROLLBACK bila**: health check gagal setelah 3x percobaan → `sudo ./deploy/rollback.sh`,
lalu investigasi log (`docker compose logs api`).

---

## Fase D - Migrasi data v2.0 → v3.0

- [ ] Dry-run dulu (tidak menulis apa pun):
  ```bash
  cd /opt/netravision
  V2_DB_HOST=127.0.0.1 V2_DB_USER=<v2_user> V2_DB_PASSWORD='<...>' V2_DB_NAME=<v2_db> \
  DATABASE_URL="postgresql://netravision:<pass>@127.0.0.1:5432/netravision" \
      python3 deploy/migrate-v2.py --dry-run
  ```
  (Ambil password Postgres dari `deploy/.env` → `POSTGRES_PASSWORD`.)
- [ ] Review angka per tabel (users, streams, hak akses, api_keys, ...). Wajar bila
  `0` untuk tabel yang memang kosong di v2.0.
- [ ] Eksekusi:
  ```bash
  ... python3 deploy/migrate-v2.py --apply
  ```
- [ ] Verifikasi cepat: jumlah baris `users` dan `cctv_streams` v3 ≈ v2.
- [ ] Salin file rekaman v2.0 ke volume recordings v3 (migrasi DB saja
  TIDAK memindahkan file - tanpa langkah ini rekaman lama tidak bisa
  diputar di v3.0):
  ```bash
  # Cari mountpoint host volume recordings v3:
  docker volume inspect netravision_recordings --format '{{.Mountpoint}}'
  # Salin + verifikasi (rsync bila ada, fallback cp; tiap file dicek ukurannya):
  V2_RECORDINGS_DIR=<direktori-rekaman-v2> \
  V3_RECORDINGS_DIR=<mountpoint-di-atas> \
      python3 deploy/migrate-v2.py --apply --copy-recordings-only
  ```
  Lanjutkan HANYA bila keluar `salin rekaman OK`. Bila ada file
  hilang/berbeda, JANGAN hapus arsip v2.0 - ulangi penyalinan sampai OK,
  dan catat hasilnya di sini: ______ file, ______ byte, status ______.

**LANJUT bila**: angka dry-run masuk akal, `--apply` selesai tanpa error,
dan penyalinan rekaman terverifikasi OK.
**ROLLBACK bila**: apply gagal di tengah → JANGAN lanjut. `--apply --force`
HANYA melewati cek tabel tujuan non-kosong dan mengandalkan ON CONFLICT
skip untuk baris duplikat - ia TIDAK mengosongkan/menghapus data parsial
dari apply yang gagal di tengah. Untuk benar-benar mengosongkan database
v3 sebelum mengulang, drop lalu buat ulang databasenya (atau TRUNCATE
tabel-tabel v3), baru `--apply` lagi. Database v2.0 tetap utuh; bila
ragu, `sudo ./deploy/rollback.sh`.

---

## Fase E - Seed admin + smoke test

- [ ] Bila belum di Fase C, buat admin sekarang:
  ```bash
  cd /opt/netravision
  sudo docker compose -f deploy/docker-compose.yml run --rm \
      -v "$PWD/deploy/seed_admin.py:/seed_admin.py:ro" \
      -e PYTHONPATH=/srv/api -e NV_ADMIN_USER=admin -e NV_ADMIN_PASS='<rahasia-kuat>' \
      api python /seed_admin.py
  ```
- [ ] Smoke test:
  ```bash
  python3 scripts/smoke_test.py --base-url http://127.0.0.1:8100 \
      --username admin --password '<rahasia-kuat>'
  ```
- [ ] Semua cek PASS (WS boleh SKIP bila lib belum ada - tidak menggagalkan).

**LANJUT bila**: smoke test exit 0.
**ROLLBACK bila**: ada FAIL → investigasi; bila tidak bisa diperbaiki dalam
window → `sudo ./deploy/rollback.sh`.

---

## Fase F - Switch (MAINTENANCE WINDOW - umumkan dulu)

v2.0 masih melayani sampai titik ini. Siapkan pengumuman singkat
("CCTV NetraVision maintenance ±15 menit").

- [ ] Pastikan mediamtx **v2.0** sudah berhenti (install.sh Fase C sudah
  menghentikannya untuk melepas UDP 8189; verifikasi, jangan asumsi):
  ```bash
  sudo systemctl is-active mediamtx || echo "mediamtx v2.0 sudah berhenti"
  # Bila masih aktif, hentikan dulu (sesuaikan nama service bila beda):
  sudo systemctl stop mediamtx
  ```
- [ ] Pastikan vhost v2.0 sudah dibackup (Fase A) dan file vhost v3.0 sudah
  disiapkan install.sh di `/etc/apache2/sites-available/netra.mamura.net.id.conf`.
  **Di sinilah pergantian vhost terjadi** (bukan di Fase C).
- [ ] Nonaktifkan vhost v2.0 berdasarkan namanya, lalu aktifkan vhost v3.0:
  ```bash
  # Cari nama vhost v2.0 yang sedang aktif (bila belum tahu namanya):
  sudo apache2ctl -S | grep -i netra
  sudo a2dissite <nama-vhost-v2>   # mis. cctv-v2, atau netra.mamura.net.id bila v2 memakai nama yang sama
  sudo a2ensite netra.mamura.net.id
  ```
  Bila v2.0 memakai file yang SAMA (`netra.mamura.net.id.conf`), file itu
  sudah ditimpa install.sh dengan versi v3.0 - `a2dissite` + `a2ensite`
  dengan nama yang sama tetap dijalankan (tidak berbahaya), dan backup
  `.bak.v2` / `.bak-YYYYMMDDHHMMSS` adalah pengaman untuk rollback.
- [ ] Reload Apache dan verifikasi:
  ```bash
  sudo apachectl configtest && sudo systemctl reload apache2
  curl -sk https://netra.mamura.net.id/api/health | head -c 200; echo
  ```
- [ ] Verifikasi dari browser (HP + desktop):
  - [ ] `https://netra.mamura.net.id/login` terbuka, bisa login
  - [ ] 1 kamera tampil live (sub stream di grid)
  - [ ] Klik tile → main stream tajam di modal
  - [ ] Halaman lain (peta, admin) terbuka tanpa error

**LANJUT bila**: semua verifikasi browser OK.
**ROLLBACK bila**: ada yang fatal → `sudo ./deploy/rollback.sh` + start ulang
mediamtx v2.0 (`sudo systemctl start mediamtx`).

---

## Fase G - Rollback (hanya bila gagal)

- [ ] Jalankan: `sudo ./deploy/rollback.sh`
  - Restore vhost dari backup terbaru (`.bak-YYYYMMDDHHMMSS` dari
    install.sh, atau `.bak.v2` dari Fase A) + a2dissite vhost v3 +
    a2ensite vhost v2.0 berdasarkan namanya + reload Apache
  - `docker compose down` (volume data dipertahankan untuk investigasi)
  - Start ulang mediamtx v2.0 (dan service aplikasi v2.0 bila
    `V2_APP_SERVICE` diset)
  - Restore DB v2.0 **hanya bila dikonfirmasi interaktif** (default: tidak -
    karena DB v2.0 tidak pernah ditulis)
- [ ] Verifikasi v2.0 kembali normal dari browser.

---

## Fase H - Pensiun v2.0 (setelah v3.0 stabil ≥ 30 hari)

- [ ] v3.0 berjalan stabil 30 hari tanpa rollback.
- [ ] Arsip rekaman v2.0: JANGAN pindahkan/hapus sebelum pemindahan ke
  volume recordings v3 di Fase D TERVERIFIKASI (`salin rekaman OK`).
  Bila verifikasi Fase D belum OK, ulangi penyalinan dulu
  (`deploy/migrate-v2.py --apply --copy-recordings-only`) sampai OK.
  Setelah terverifikasi, pindahkan ke storage arsip / hapus sesuai
  kebijakan (default: pertahankan 30 hari sejak cutover, lalu hapus).
- [ ] Hentikan service v2.0 yang tersisa; arsipkan repo `cctv-monitoring`
  (tag `v2.0-final`).
- [ ] Hapus backup `.bak.v2` bila sudah tidak diperlukan.
- [ ] Update dokumen ini dengan tanggal decommission: `______`

---

## Ringkasan perintah darurat

```bash
# Status cepat
curl -s http://127.0.0.1:8100/api/health
cd /opt/netravision && sudo docker compose -f deploy/docker-compose.yml ps

# Log
cd /opt/netravision && sudo docker compose -f deploy/docker-compose.yml logs --tail=100 api

# Rollback total
sudo ./deploy/rollback.sh
```
