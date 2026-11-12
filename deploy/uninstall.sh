#!/usr/bin/env bash
#
# NetraVision v3.0 - uninstall.sh
# Menghapus instalasi v3.0 dari server. IDEMPOTEN: aman dijalankan ulang,
# langkah yang sudah tidak ada dilewati (bukan gagal).
#
# Yang dilakukan:
#   1. Matikan stack Docker v3.0 (container api, postgres, redis, mediamtx,
#      migrate, netravision). Volume data TIDAK dihapus kecuali
#      --delete-data (destruktif: database, rekaman, dan upload ikut hilang).
#   2. Nonaktifkan dan hapus vhost Apache v3.0, lalu reload Apache.
#      Vhost lain dan vhost v2.0 (bila ada) TIDAK disentuh.
#   3. Hapus DocumentRoot frontend (/var/www/netravision/out).
#   4. Hapus direktori repo ini, hanya bila --delete-repo (destruktif:
#      termasuk .env dan riwayat git lokal). Dijadwalkan setelah script
#      keluar karena script ini tinggal di dalam repo.
#
# TIDAK dilakukan: menghapus Docker itu sendiri, menghapus Apache,
# menghapus database v2.0 (MariaDB), menghapus sertifikat Let's Encrypt,
# menghapus backup vhost (.bak-*) di /etc/apache2/sites-available.
#
# Opsi:
#   --yes           lewati semua konfirmasi (untuk otomatisasi)
#   --delete-data   hapus juga volume Docker (database + rekaman + upload)
#   --delete-repo   hapus juga direktori repo ini setelah selesai
#
# Contoh:
#   sudo ./deploy/uninstall.sh
#   sudo ./deploy/uninstall.sh --yes --delete-data
#   sudo ./deploy/uninstall.sh --yes --delete-data --delete-repo

set -euo pipefail

# Cek root PALING AWAL, sebelum langkah apa pun.
[ "$EUID" -eq 0 ] || { echo -e "\033[1;31m[ FAIL ]\033[0m Jalankan sebagai root (sudo ./deploy/uninstall.sh)." >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
DOMAIN="$(grep -E '^DOMAIN=' "$DEPLOY_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
DOMAIN="${DOMAIN:-netra.mamura.net.id}"
VHOST_PATH="/etc/apache2/sites-available/${DOMAIN}.conf"
DOCROOT="/var/www/netravision/out"

YES=""
DELETE_DATA=""
DELETE_REPO=""
for arg in "$@"; do
    case "$arg" in
        --yes) YES="1" ;;
        --delete-data) DELETE_DATA="1" ;;
        --delete-repo) DELETE_REPO="1" ;;
        *) echo -e "\033[1;31m[ FAIL ]\033[0m Opsi tidak dikenal: $arg (pakai --yes, --delete-data, --delete-repo)." >&2; exit 1 ;;
    esac
done

step()  { echo -e "\n\033[1;34m[uninstall]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

confirm() { # $1 = pertanyaan; kembalikan 0 bila ya
    if [ -n "$YES" ]; then return 0; fi
    local jawab=""
    read -r -p "$1 [y/N] " jawab || true
    [[ "${jawab:-}" =~ ^[Yy]$ ]]
}

echo "NetraVision v3.0 akan dihapus dari server ini."
echo "  Repo     : $REPO_ROOT"
echo "  Domain   : $DOMAIN"
echo "  Data     : $([ -n "$DELETE_DATA" ] && echo "DIHAPUS (volume Docker)" || echo "dipertahankan (volume Docker)")"
echo "  Repo dir : $([ -n "$DELETE_REPO" ] && echo "DIHAPUS" || echo "dipertahankan")"
confirm "Lanjutkan uninstall?" || { echo "Dibatalkan."; exit 0; }

# ------------------------------------------------- 1. matikan stack Docker
step "1/4 - Matikan stack Docker v3.0"
if command -v docker >/dev/null 2>&1 && [ -f "$COMPOSE_FILE" ]; then
    if [ -n "$DELETE_DATA" ]; then
        confirm "Hapus SEMUA data (database, rekaman, upload)? Tindakan ini DESTRUKTIF." || { echo "Dibatalkan."; exit 0; }
        docker compose -f "$COMPOSE_FILE" down -v \
            && ok "Stack dimatikan, volume ikut dihapus." \
            || warn "docker compose down -v gagal - cek manual: docker ps -a; docker volume ls"
    else
        docker compose -f "$COMPOSE_FILE" down \
            && ok "Stack dimatikan (volume data dipertahankan)." \
            || warn "docker compose down gagal - cek manual: docker ps -a"
        echo "    Volume dipertahankan. Hapus manual bila sudah tidak dibutuhkan:"
        echo "      docker volume rm netravision_pgdata netravision_redisdata netravision_recordings netravision_apidata"
    fi
else
    warn "docker / docker-compose.yml tidak ada - lewati (mungkin sudah tidak terinstal)."
fi

# ------------------------------------------------- 2. hapus vhost Apache
step "2/4 - Hapus vhost Apache v3.0"
if [ -f "$VHOST_PATH" ]; then
    if command -v a2dissite >/dev/null 2>&1; then
        a2dissite -q "$DOMAIN" 2>/dev/null \
            && ok "Vhost $DOMAIN dinonaktifkan." \
            || warn "Vhost $DOMAIN tidak aktif / gagal dinonaktifkan."
    fi
    rm -f "$VHOST_PATH" && ok "File vhost dihapus: $VHOST_PATH"
    if command -v apachectl >/dev/null 2>&1; then
        apachectl configtest >/dev/null 2>&1 \
            && systemctl reload apache2 2>/dev/null \
            && ok "Apache reload." \
            || warn "apachectl configtest / reload gagal - periksa manual."
    fi
else
    warn "Vhost $DOMAIN tidak ditemukan - lewati."
fi
echo "    Backup vhost (.bak-*) di /etc/apache2/sites-available TIDAK dihapus."

# ------------------------------------------------- 3. hapus DocumentRoot
step "3/4 - Hapus DocumentRoot frontend"
if [ -d "$DOCROOT" ]; then
    [ -n "$DOCROOT" ] && [ "$DOCROOT" != "/" ] || fail "DOCROOT tidak aman: '$DOCROOT'."
    rm -rf "$DOCROOT" && ok "Dihapus: $DOCROOT"
else
    warn "DocumentRoot tidak ada - lewati."
fi

# ------------------------------------------------- 4. hapus repo (opsional)
step "4/4 - Direktori repo"
if [ -n "$DELETE_REPO" ]; then
    confirm "Hapus direktori repo $REPO_ROOT (termasuk .env dan riwayat git lokal)?" || { echo "Repo dipertahankan."; DELETE_REPO=""; }
fi
if [ -n "$DELETE_REPO" ]; then
    # Script ini tinggal di dalam repo, jadi penghapusan dijadwalkan
    # setelah script keluar (3 detik cukup untuk bash selesai membaca).
    ( sleep 3; rm -rf "$REPO_ROOT" ) >/dev/null 2>&1 &
    ok "Repo akan dihapus setelah script keluar: $REPO_ROOT"
else
    ok "Repo dipertahankan. Hapus manual bila perlu: rm -rf $REPO_ROOT"
fi

echo -e "\n\033[1;32m==============================================\033[0m"
echo -e "\033[1;32m NetraVision v3.0 UNINSTALL SELESAI.\033[0m"
echo -e "\033[1;32m==============================================\033[0m"
echo "  Domain $DOMAIN sudah tidak dilayani v3.0."
echo "  Docker, Apache, MariaDB v2.0, dan sertifikat TIDAK dihapus."
