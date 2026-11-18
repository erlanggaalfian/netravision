#!/usr/bin/env bash
#
# NetraVision v3.0 - fix-volume-perms.sh
# Perbaiki kepemilikan volume Docker agar service `api` (non-root,
# uid 10001 = user `netra` di apps/api/Dockerfile) bisa menulis:
#   recordings, apidata (/srv/api/data), gdrive_staging (/mnt/gdrive)
#
# IDEMPOTEN: aman dijalankan ulang. Dijalankan otomatis oleh
# deploy/install.sh dan deploy/update.sh setelah `docker compose up`.
# Bila dijalankan manual: sudo ./deploy/fix-volume-perms.sh
#
# Cara kerja: `docker compose run --user root --no-deps api chown ...`
# memakai image api sendiri (tidak perlu pull image lain). Bila itu
# gagal, fallback ke container alpine sekali pakai.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
API_UID="${API_UID:-10001}"

step()  { echo -e "\n\033[1;34m[fix-volume-perms]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/fix-volume-perms.sh)."
command -v docker >/dev/null 2>&1 || fail "docker belum terinstal."
[ -f "$COMPOSE_FILE" ] || fail "docker-compose.yml tidak ditemukan: $COMPOSE_FILE"

step "Mengubah pemilik volume ke uid $API_UID (recordings, apidata, gdrive_staging)"
cd "$REPO_ROOT"
if docker compose -f "$COMPOSE_FILE" run --rm --user root --no-deps api \
        chown -R "$API_UID:$API_UID" /recordings /srv/api/data /mnt/gdrive; then
    ok "Kepemilikan volume diperbaiki (uid $API_UID)."
    exit 0
fi
warn "compose run gagal - coba fallback container alpine sekali pakai."
if docker run --rm \
        -v netravision_recordings:/recordings \
        -v netravision_apidata:/srv/api/data \
        -v netravision_gdrive_staging:/mnt/gdrive \
        alpine:3.21 chown -R "$API_UID:$API_UID" /recordings /srv/api/data /mnt/gdrive; then
    ok "Kepemilikan volume diperbaiki via alpine (uid $API_UID)."
    exit 0
fi
fail "Gagal memperbaiki kepemilikan volume. Perintah manual: docker run --rm -v netravision_recordings:/recordings -v netravision_apidata:/srv/api/data -v netravision_gdrive_staging:/mnt/gdrive alpine:3.21 chown -R $API_UID:$API_UID /recordings /srv/api/data /mnt/gdrive"
