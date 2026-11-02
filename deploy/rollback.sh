#!/usr/bin/env bash
#
# NetraVision v3.0 — rollback.sh
# Mengembalikan server ke v2.0 bila cutover v3.0 gagal.
#
# Yang dilakukan:
#   1. Restore vhost Apache dari backup .bak.v2 (dibuat saat Fase F cutover)
#   2. Matikan stack Docker v3.0 (docker compose down)
#   3. Restore database v2.0 dari dump Fase A — HANYA bila dikonfirmasi
#      interaktif (destruktif; default: JANGAN, karena migrasi v3.0 hanya
#      MEMBACA database v2.0 dan tidak pernah mengubahnya).
#
# Contoh: sudo ./deploy/rollback.sh   (dari root repo)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
VHOST_LIVE="/etc/apache2/sites-available/netra.mamura.net.id.conf"
VHOST_BAK="/etc/apache2/sites-available/netra.mamura.net.id.conf.bak.v2"

step()  { echo -e "\n\033[1;34m[rollback]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/rollback.sh)."

# ------------------------------------------------- 1. restore vhost v2.0
step "1/3 — Restore vhost Apache v2.0"
if [ -f "$VHOST_BAK" ]; then
    cp "$VHOST_BAK" "$VHOST_LIVE"
    apachectl configtest || fail "apachectl configtest GAGAL setelah restore — perbaiki manual."
    systemctl reload apache2 || fail "Gagal reload apache2."
    ok "Vhost v2.0 dikembalikan dari $VHOST_BAK."
else
    warn "$VHOST_BAK tidak ditemukan — vhost TIDAK diubah. Periksa manual bila perlu."
fi

# ------------------------------------------------- 2. matikan stack v3.0
step "2/3 — Matikan stack Docker v3.0"
cd "$REPO_ROOT"
if command -v docker >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" down \
        && ok "Stack v3.0 dimatikan (volume data TIDAK dihapus)." \
        || warn "docker compose down gagal — cek manual."
else
    warn "docker tidak ada — lewati."
fi
echo "    Volume netravision_pgdata / netravision_recordings sengaja dipertahankan"
echo "    untuk investigasi. Hapus manual bila sudah tidak dibutuhkan: "
echo "      docker volume rm netravision_pgdata netravision_recordings"

# ------------------------------------------------- 3. database v2.0 (interaktif)
step "3/3 — Database v2.0"
echo "    CATATAN: migrate-v2.py HANYA MEMBACA database v2.0 (MariaDB) —"
echo "    database v2.0 tidak diubah selama cutover, jadi restore umumnya"
echo "    TIDAK diperlukan."
echo
echo "    Bila Anda sempat mengubah database v2.0 secara manual dan ingin"
echo "    mengembalikannya dari dump Fase A, perintahnya:"
echo
echo "      mysql -u <v2_user> -p <v2_db> < /backup/netravision-v2-<TANGGAL>.sql"
echo
read -r -p "    Tampilkan panduan restore detail? [y/N] " jawab
if [[ "$jawab" =~ ^[Yy]$ ]]; then
    echo
    echo "    1. Pastikan dump Fase A ada, mis. /backup/netravision-v2-20261102.sql"
    echo "    2. Hentikan aplikasi v2.0 dulu bila masih berjalan."
    echo "    3. mysql -u <v2_user> -p <v2_db> < /backup/netravision-v2-20261102.sql"
    echo "    4. Verifikasi: buka https://netra.mamura.net.id dan login v2.0."
    echo
    read -r -p "    Jalankan restore SEKARANG? Tindakan ini DESTRUKTIF. [y/N] " jawab2
    if [[ "$jawab2" =~ ^[Yy]$ ]]; then
        read -r -p "    Path file dump: " dump
        read -r -p "    User MariaDB v2.0: " dbuser
        read -r -p "    Nama database v2.0: " dbname
        [ -f "$dump" ] || fail "File dump tidak ditemukan: $dump"
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
