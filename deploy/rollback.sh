#!/usr/bin/env bash
#
# NetraVision v3.0 - rollback.sh
# Mengembalikan server ke v2.0 bila cutover v3.0 gagal.
#
# Yang dilakukan:
#   1. Restore vhost Apache v2.0 dari backup terbaru (stempel waktu
#      .bak-YYYYMMDDHHMMSS dari install.sh, atau .bak.v2 dari Fase A),
#      a2dissite vhost v3, a2ensite vhost v2.0 berdasarkan namanya, reload
#   2. Matikan stack Docker v3.0 (docker compose down)
#   3. Start ulang aplikasi/mediamtx v2.0
#   4. Restore database v2.0 dari dump Fase A - HANYA bila dikonfirmasi
#      interaktif (destruktif; default: JANGAN, karena migrasi v3.0 hanya
#      MEMBACA database v2.0 dan tidak pernah mengubahnya).
#
# Nama vhost v2.0 bisa dioverride: V2_VHOST_NAME=... ./deploy/rollback.sh
# Service aplikasi v2.0 (bila berupa unit systemd) bisa dioverride:
# V2_APP_SERVICE=... ./deploy/rollback.sh
#
# Contoh: sudo ./deploy/rollback.sh   (dari root repo)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
# Vhost v3 (nama file = domain default); nama vhost v2.0 dibaca dari
# backup yang direstore (atau V2_VHOST_NAME bila di-override).
VHOST_V3_NAME="netra.mamura.net.id"
VHOST_LIVE="/etc/apache2/sites-available/${VHOST_V3_NAME}.conf"
V2_VHOST_NAME="${V2_VHOST_NAME:-}"

step()  { echo -e "\n\033[1;34m[rollback]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/rollback.sh)."

# ------------------------------------------------- 1. restore vhost v2.0
step "1/4 - Restore vhost Apache v2.0"
# Backup yang benar: install.sh membuat .bak-YYYYMMDDHHMMSS (stempel waktu),
# Fase A membuat .bak.v2. Pakai yang TERBARU dari keduanya - jangan hanya
# andalkan .bak.v2 (G-S13: backup Fase A bisa saja terlewat).
VHOST_BAK=""
for cand in "$VHOST_LIVE".bak-[0-9]* "$VHOST_LIVE".bak.v2; do
    [ -f "$cand" ] || continue
    if [ -z "$VHOST_BAK" ] || [ "$cand" -nt "$VHOST_BAK" ]; then
        VHOST_BAK="$cand"
    fi
done
if [ -n "$VHOST_BAK" ]; then
    # Nama file backup -> nama vhost asal: hapus akhiran .bak-* / .bak.v2.
    RESTORED_NAME="$(basename "$VHOST_BAK" | sed -E 's/\.bak(-[0-9]+|\.v2)$//')"
    RESTORED_PATH="/etc/apache2/sites-available/${RESTORED_NAME}"
    cp "$VHOST_BAK" "$RESTORED_PATH"
    ok "Vhost dikembalikan dari $VHOST_BAK ke $RESTORED_PATH."
    # Nama vhost v2.0: override env, lalu nama file backup, lalu default.
    if [ -z "$V2_VHOST_NAME" ]; then
        V2_VHOST_NAME="${RESTORED_NAME%.conf}"
    fi
    # Matikan vhost v3 bila namanya berbeda dari vhost v2.0.
    if [ "$V2_VHOST_NAME" != "$VHOST_V3_NAME" ]; then
        a2dissite -q "$VHOST_V3_NAME" 2>/dev/null \
            && ok "Vhost v3 ($VHOST_V3_NAME) dinonaktifkan." \
            || warn "Vhost v3 tidak aktif / gagal dinonaktifkan - cek manual."
    fi
    a2ensite -q "$V2_VHOST_NAME" \
        || fail "Gagal a2ensite vhost v2.0 ($V2_VHOST_NAME)."
    apachectl configtest || fail "apachectl configtest GAGAL setelah restore - perbaiki manual."
    systemctl reload apache2 || fail "Gagal reload apache2."
    ok "Vhost v2.0 ($V2_VHOST_NAME) aktif kembali."
else
    warn "Tidak ada backup vhost ditemukan ($VHOST_LIVE.bak-* / .bak.v2) - vhost TIDAK diubah. Periksa manual bila perlu."
fi

# ------------------------------------------------- 2. matikan stack v3.0
step "2/4 - Matikan stack Docker v3.0"
cd "$REPO_ROOT"
if command -v docker >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" down \
        && ok "Stack v3.0 dimatikan (volume data TIDAK dihapus)." \
        || warn "docker compose down gagal - cek manual."
else
    warn "docker tidak ada - lewati."
fi
echo "    Volume netravision_pgdata / netravision_recordings sengaja dipertahankan"
echo "    untuk investigasi. Hapus manual bila sudah tidak dibutuhkan: "
echo "      docker volume rm netravision_pgdata netravision_recordings"

# ------------------------------------------------- 3. start ulang v2.0
step "3/4 - Start ulang aplikasi/mediamtx v2.0"
if command -v systemctl >/dev/null 2>&1; then
    if systemctl list-unit-files 2>/dev/null | grep -q '^mediamtx\.service'; then
        systemctl start mediamtx \
            && ok "mediamtx v2.0 dijalankan kembali." \
            || warn "Gagal start mediamtx v2.0 - jalankan manual: sudo systemctl start mediamtx"
    else
        warn "Unit mediamtx tidak ditemukan - nyalakan mediamtx v2.0 manual bila dijalankan tanpa systemd."
    fi
    if [ -n "${V2_APP_SERVICE:-}" ]; then
        systemctl start "$V2_APP_SERVICE" \
            && ok "Service aplikasi v2.0 ($V2_APP_SERVICE) dijalankan kembali." \
            || warn "Gagal start $V2_APP_SERVICE - cek manual."
    else
        warn "V2_APP_SERVICE tidak diset - bila aplikasi v2.0 berupa service systemd, nyalakan manual (atau jalankan ulang dengan V2_APP_SERVICE=<nama-unit>)."
    fi
else
    warn "systemctl tidak ada - nyalakan mediamtx/aplikasi v2.0 manual."
fi

# ------------------------------------------------- 4. database v2.0 (interaktif)
step "4/4 - Database v2.0"
echo "    CATATAN: migrate-v2.py HANYA MEMBACA database v2.0 (MariaDB) -"
echo "    database v2.0 tidak diubah selama cutover, jadi restore umumnya"
echo "    TIDAK diperlukan."
echo
echo "    Bila Anda sempat mengubah database v2.0 secara manual dan ingin"
echo "    mengembalikannya dari dump Fase A, perintahnya:"
echo
echo "      mysql -u <v2_user> -p <v2_db> < /backup/netravision-v2-<TANGGAL>.sql"
echo
read -r -p "    Tampilkan panduan restore detail? [y/N] " jawab || true
if [[ "${jawab:-}" =~ ^[Yy]$ ]]; then
    echo
    echo "    1. Pastikan dump Fase A ada, mis. /backup/netravision-v2-20261102.sql"
    echo "    2. Hentikan aplikasi v2.0 dulu bila masih berjalan."
    echo "    3. mysql -u <v2_user> -p <v2_db> < /backup/netravision-v2-20261102.sql"
    echo "    4. Verifikasi: buka https://netra.mamura.net.id dan login v2.0."
    echo
    read -r -p "    Jalankan restore SEKARANG? Tindakan ini DESTRUKTIF. [y/N] " jawab2 || true
    if [[ "${jawab2:-}" =~ ^[Yy]$ ]]; then
        command -v mysql >/dev/null 2>&1 || fail "Perintah 'mysql' tidak ditemukan - instal klien MariaDB dulu."
        read -r -p "    Path file dump: " dump || true
        read -r -p "    User MariaDB v2.0: " dbuser || true
        read -r -p "    Nama database v2.0: " dbname || true
        [ -f "${dump:-}" ] || fail "File dump tidak ditemukan: ${dump:-}"
        [ -n "${dbuser:-}" ] && [ -n "${dbname:-}" ] || fail "User dan nama database wajib diisi."
        # shellcheck disable=SC2086
        mysql -u "$dbuser" -p "$dbname" < "$dump" \
            && ok "Restore database v2.0 selesai." \
            || fail "Restore gagal."
    else
        ok "Restore database dilewati (pilihan aman)."
    fi
else
    ok "Restore database dilewati."
fi

echo -e "\n\033[1;32mRollback selesai. Verifikasi: https://netra.mamura.net.id (v2.0).\033[0m"
