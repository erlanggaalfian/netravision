#!/usr/bin/env bash
#
# NetraVision v3.0 — update.sh
# Update di server produksi. IDEMPOTEN: aman dijalankan ulang.
#
# Yang dilakukan:
#   1. git pull (fast-forward only)
#   2. Build frontend (Next.js static export -> DocumentRoot Apache)
#   3. Migrasi database (alembic upgrade head)
#   4. docker compose up -d --build
#   5. Health check GET /api/health
#
# Contoh: sudo ./deploy/update.sh   (dari root repo)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
DOCROOT="/var/www/netravision/out"
API_PORT="${API_PORT:-8100}"

step()  { echo -e "\n\033[1;34m[update]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ SKIP ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/update.sh)."
command -v docker >/dev/null 2>&1 || fail "docker belum terinstal — jalankan install.sh dulu."
[ -f "$DEPLOY_DIR/.env" ] || fail "deploy/.env belum ada — jalankan install.sh dulu."

cd "$REPO_ROOT"

# ---------------------------------------------------------------- 1. git pull
step "1/5 — git pull"
git pull --ff-only || fail "git pull gagal (ada konflik / bukan fast-forward). Selesaikan manual dulu."
ok "Repo terbaru: $(git rev-parse --short HEAD)"

# ------------------------------------------------- 2. build frontend
step "2/5 — Build frontend"
if [ -f "$REPO_ROOT/apps/web/package.json" ]; then
    # Build di container Node 20 (host bisa Node 18 — Tailwind v4 butuh 20+).
    # Tidak mengganggu aplikasi lain di server.
    docker run --rm -v "$REPO_ROOT/apps/web:/app" -w /app node:20-alpine \
        sh -c "npm ci && npm run build" \
        || fail "Build frontend gagal."
    [ -d "$REPO_ROOT/apps/web/out" ] || fail "Hasil build apps/web/out tidak ditemukan (cek output: 'export' di next.config)."
    mkdir -p "$DOCROOT"
    # Sinkronkan hasil build ke DocumentRoot (hapus file lama yang tak terpakai).
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete "$REPO_ROOT/apps/web/out/" "$DOCROOT/"
    else
        cp -a "$REPO_ROOT/apps/web/out/." "$DOCROOT/"
    fi
    ok "Frontend ter-deploy ke $DOCROOT"
else
    warn "apps/web belum ada (Fase 2) — lewati build frontend."
fi

# ------------------------------------------------- 3. migrasi database
step "3/5 — Migrasi database"
if [ -f "$REPO_ROOT/apps/api/Dockerfile" ]; then
    docker compose -f "$COMPOSE_FILE" up -d api >/dev/null \
        || fail "Gagal menjalankan container api."
    # PYTHONPATH=/srv/api agar alembic menemukan modul 'app'.
    docker compose -f "$COMPOSE_FILE" exec -T -w /srv/api \
        -e PYTHONPATH=/srv/api api alembic upgrade head \
        || fail "Migrasi gagal. Cek: docker compose -f $COMPOSE_FILE logs api"
    ok "Migrasi selesai."
else
    warn "apps/api belum ada — lewati migrasi."
fi

# ------------------------------------------------- 4. rebuild & restart
step "4/5 — docker compose up -d --build"
docker compose -f "$COMPOSE_FILE" up -d --build \
    || fail "docker compose up gagal. Cek: docker compose -f $COMPOSE_FILE logs"
ok "Semua service berjalan."

# ------------------------------------------------- 5. health check
step "5/5 — Health check"
sleep 5
if curl -sf -o /dev/null --max-time 10 "http://127.0.0.1:${API_PORT}/api/health"; then
    ok "GET /api/health -> OK"
else
    fail "Health check GAGAL. Cek: docker compose -f $COMPOSE_FILE logs api"
fi

echo -e "\n\033[1;32m==============================================\033[0m"
echo -e "\033[1;32m NetraVision v3.0 UPDATE SELESAI.\033[0m"
echo -e "\033[1;32m==============================================\033[0m"
echo "  Revisi   : $(git rev-parse --short HEAD)"
echo "  Publik   : https://netra.mamura.net.id"
