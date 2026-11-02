# NetraVision v3.0 — Runbook Cutover

Panduan langkah-demi-langkah memindahkan produksi dari v2.0 ("Mamura Stream")
ke v3.0 di server yang sama. **Eksekusi dilakukan di server, sebagai root.**

Aturan keras yang dijaga sepanjang proses:

- Port 80/443 **tetap milik Apache** — tidak ada container yang bind ke sana.
- Database v2.0 (MariaDB) **tidak pernah ditulis** oleh proses migrasi (hanya dibaca).
- Setiap fase punya kriteria **LANJUT** vs **ROLLBACK** yang eksplisit di bawah.

> **Downtime**: dibutuhkan *maintenance window* singkat (±5–15 menit) pada
> Fase F saat vhost dialihkan. Di luar itu v2.0 tetap melayani normal.

Estimasi total: 1–2 jam untuk instalasi + migrasi pertama kali
(tergantung ukuran database dan arsip rekaman).

---

## Fase A — Backup (v2.0 tetap jalan)

- [ ] Dump database v2.0 (MariaDB):
  ```bash
  mkdir -p /backup
  mysqldump -u <v2_user> -p <v2_db> > /backup/netravision-v2-$(date +%Y%m%d).sql
  ls -lh /backup/netravision-v2-*.sql   # pastikan file tidak kosong
  ```
- [ ] Backup arsip rekaman v2.0 (bila di disk yang sama — jangan dipindah, cukup catat):
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
**ROLLBACK**: belum ada yang diubah — cukup ulangi backup yang gagal.

---

## Fase B — Preflight

- [ ] Clone/pull repo v3.0 di server (atau salin dari workstation):
  ```bash
  git clone https://github.com/erlanggaalfian/netravision.git /opt/netravision
  cd /opt/netravision
  ```
- [ ] Jalankan preflight:
  ```bash
  python3 scripts/preflight.py
  ```
- [ ] Semua cek berstatus OK (peringatan UDP 8189 boleh — lihat Fase F).

**LANJUT bila**: exit code 0, tidak ada `[ GAGAL ]`.
**ROLLBACK**: belum ada yang diubah — perbaiki item yang gagal, ulangi.

---

## Fase C — Install

- [ ] Jalankan (butuh root; estimasi 10–30 menit — dominan download image Docker):
  ```bash
  sudo ./deploy/install.sh
  ```
  Skrip ini: preflight ulang → siapkan `.env` → `compose up` → tunggu Postgres →
  migrasi Alembic → pasang vhost v3.0 → health check.
- [ ] (Opsional tapi disarankan) buat admin awal:
  ```bash
  sudo NV_ADMIN_USER=admin NV_ADMIN_PASS='<rahasia-kuat>' ./deploy/install.sh
  ```
  Tanpa env tersebut, langkah seed dilewati dengan pesan (bisa dibuat belakangan
  via API atau dengan menjalankan ulang install.sh — idempoten).

**LANJUT bila**: di akhir ada `GET /api/health -> OK`.
**ROLLBACK bila**: health check gagal setelah 3x percobaan → `sudo ./deploy/rollback.sh`,
lalu investigasi log (`docker compose logs api`).

---

## Fase D — Migrasi data v2.0 → v3.0

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

**LANJUT bila**: angka dry-run masuk akal dan `--apply` selesai tanpa error.
**ROLLBACK bila**: apply gagal di tengah → JANGAN lanjut; database v3 bisa
dikosongkan (`--apply --force` setelah perbaiki penyebabnya) atau
`sudo ./deploy/rollback.sh`. Database v2.0 tetap utuh.

---

## Fase E — Seed admin + smoke test

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
- [ ] Semua cek PASS (WS boleh SKIP bila lib belum ada — tidak menggagalkan).

**LANJUT bila**: smoke test exit 0.
**ROLLBACK bila**: ada FAIL → investigasi; bila tidak bisa diperbaiki dalam
window → `sudo ./deploy/rollback.sh`.

---

## Fase F — Switch (MAINTENANCE WINDOW — umumkan dulu)

v2.0 masih melayani sampai titik ini. Siapkan pengumuman singkat
("CCTV NetraVision maintenance ±15 menit").

- [ ] Hentikan mediamtx **v2.0** (melepas UDP 8189 untuk stack v3.0):
  ```bash
  sudo systemctl stop mediamtx   # sesuaikan dengan nama service v2.0 bila beda
  ```
- [ ] Pastikan vhost v2.0 sudah dibackup (Fase A). Lalu **nonaktifkan vhost lama
  hanya bila namanya berbeda** dari `netra.mamura.net.id.conf`. Bila v2.0 memakai
  file yang SAMA (`netra.mamura.net.id.conf`), install.sh sudah menimpanya dengan
  versi v3.0 — tidak perlu a2dissite; backup `.bak.v2` adalah pengaman.
- [ ] Bila v2.0 memakai nama vhost berbeda:
  ```bash
  sudo a2dissite <nama-vhost-v2>
  ```
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

## Fase G — Rollback (hanya bila gagal)

- [ ] Jalankan: `sudo ./deploy/rollback.sh`
  - Restore vhost dari `.bak.v2` + reload Apache
  - `docker compose down` (volume data dipertahankan untuk investigasi)
  - Restore DB v2.0 **hanya bila dikonfirmasi interaktif** (default: tidak —
    karena DB v2.0 tidak pernah ditulis)
- [ ] Start ulang mediamtx v2.0 bila dihentikan di Fase F.
- [ ] Verifikasi v2.0 kembali normal dari browser.

---

## Fase H — Pensiun v2.0 (setelah v3.0 stabil ≥ 30 hari)

- [ ] v3.0 berjalan stabil 30 hari tanpa rollback.
- [ ] Arsip rekaman v2.0: pindahkan ke storage arsip / hapus sesuai kebijakan
  (default: pertahankan 30 hari sejak cutover, lalu hapus).
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
