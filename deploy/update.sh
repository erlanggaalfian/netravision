#!/usr/bin/env bash
#
# NetraVision v3.0 - update.sh
# Update di server produksi. IDEMPOTEN: aman dijalankan ulang.
#
# Yang dilakukan:
#   1. git pull (fast-forward only)
#   2. Build frontend (Next.js static export -> DocumentRoot Apache)
#   3. docker compose up -d --build
#   4. Migrasi database (alembic upgrade head) - SETELAH rebuild, supaya
#      image baru (yang berisi file migrasi baru) yang menjalankannya
#   5. Health check GET /api/health
#
# API_PORT dibaca dari env shell, lalu deploy/.env, lalu default 8100 -
# harus sama dengan nilai yang dipakai docker-compose.yml
# ("127.0.0.1:${API_PORT:-8100}:8000").
#
# Contoh: sudo ./deploy/update.sh   (dari root repo)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
DOCROOT="/var/www/netravision/out"
# Belum diputuskan di sini: dibaca dari deploy/.env setelah cek file di bawah.
API_PORT="${API_PORT:-}"

step()  { echo -e "\n\033[1;34m[update]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ SKIP ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/update.sh)."
command -v docker >/dev/null 2>&1 || fail "docker belum terinstal - jalankan install.sh dulu."
[ -f "$DEPLOY_DIR/.env" ] || fail "deploy/.env belum ada - jalankan install.sh dulu."
# API_PORT: env shell menang, lalu deploy/.env, lalu default 8100.
if [ -z "$API_PORT" ]; then
    API_PORT="$(grep -E '^API_PORT=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
    API_PORT="${API_PORT:-8100}"
fi

cd "$REPO_ROOT"

# ---------------------------------------------------------------- 1. git pull
step "1/5 - git pull"
git pull --ff-only || fail "git pull gagal (ada konflik / bukan fast-forward). Selesaikan manual dulu."
ok "Repo terbaru: $(git rev-parse --short HEAD)"

# ------------------------------------------------- 2. build frontend
step "2/5 - Build frontend"
if [ -f "$REPO_ROOT/apps/web/package.json" ]; then
    # Build di container Node 20 (host bisa Node 18 - Tailwind v4 butuh 20+).
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
        # Tanpa rsync: hapus dulu isi DocumentRoot supaya file build lama
        # yang sudah dihapus di apps/web/out tidak tetap tersaji
        # (setara --delete pada rsync di atas).
        # Pengaman: jangan pernah hapus bila DOCROOT kosong atau root (/).
        [ -n "$DOCROOT" ] && [ "$DOCROOT" != "/" ] || fail "DOCROOT tidak aman: '$DOCROOT'."
        find "$DOCROOT" -mindepth 1 -delete
        cp -a "$REPO_ROOT/apps/web/out/." "$DOCROOT/"
    fi
    ok "Frontend ter-deploy ke $DOCROOT"
else
    warn "apps/web belum ada (Fase 2) - lewati build frontend."
fi

# ------------------------------------------------- 3. rebuild & restart
# Rebuild DULU: image baru berisi file migrasi baru. Migrasi jalan di
# langkah 4, di dalam image baru (G-K1: migrasi sebelum rebuild membuat
# migrasi baru tidak pernah diterapkan karena image lama tak punya filenya).
step "3/5 - docker compose up -d --build"
docker compose -f "$COMPOSE_FILE" up -d --build \
    || fail "docker compose up gagal. Cek: docker compose -f $COMPOSE_FILE logs"
ok "Semua service berjalan."

# ------------------------------------------------- 4. migrasi database
step "4/5 - Migrasi database"
if [ -f "$REPO_ROOT/apps/api/Dockerfile" ]; then
    # PYTHONPATH=/srv/api agar alembic menemukan modul 'app'.
    # Dijalankan SETELAH rebuild supaya file migrasi baru sudah ada di image.
    docker compose -f "$COMPOSE_FILE" exec -T -w /srv/api \
        -e PYTHONPATH=/srv/api api alembic upgrade head \
        || fail "Migrasi gagal. Cek: docker compose -f $COMPOSE_FILE logs api"
    ok "Migrasi selesai."
else
    warn "apps/api belum ada - lewati migrasi."
fi

# ------------------------------------------------- 5. health check
step "5/5 - Health check"
# API butuh waktu start; coba ulang sampai 60 detik, bukan sekali tembak.
HEALTH_OK=""
for i in $(seq 1 12); do
    if curl -sf -o /dev/null --max-time 5 "http://127.0.0.1:${API_PORT}/api/health"; then
        HEALTH_OK="1"
        break
    fi
    sleep 5
done
if [ -n "$HEALTH_OK" ]; then
    ok "GET /api/health -> OK"
else
    fail "Health check GAGAL setelah 60 dtk. Cek: docker compose -f $COMPOSE_FILE logs api"
fi

echo -e "\n\033[1;32m==============================================\033[0m"
echo -e "\033[1;32m NetraVision v3.0 UPDATE SELESAI.\033[0m"
echo -e "\033[1;32m==============================================\033[0m"
echo "  Revisi   : $(git rev-parse --short HEAD)"
echo "  Publik   : https://netra.mamura.net.id"
