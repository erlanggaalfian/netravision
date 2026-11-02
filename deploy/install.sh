#!/usr/bin/env bash
#
# NetraVision v3.0 — install.sh
# Instalasi / setup awal di server. IDEMPOTEN: aman dijalankan ulang.
#
# Yang dilakukan:
#   1. Cek prasyarat (root, docker + compose plugin, apache2)
#   2. Siapkan deploy/.env (dari .env.example; generate secret acak bila placeholder)
#   3. docker compose up -d, tunggu postgres sehat
#   4. Jalankan migrasi Alembic via container api
#   5. Pasang vhost Apache netra.mamura.net.id (80/443 tetap milik Apache)
#   6. Health check GET /api/health
#
# Contoh: sudo ./deploy/install.sh   (dari root repo)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
ENV_FILE="$DEPLOY_DIR/.env"
VHOST_SRC="$DEPLOY_DIR/apache/netra.mamura.net.id.conf"
VHOST_DST="/etc/apache2/sites-available/netra.mamura.net.id.conf"
DOCROOT="/var/www/netravision/out"

step()  { echo -e "\n\033[1;34m[install]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

# ---------------------------------------------------------------- 1. prasyarat
step "1/6 — Cek prasyarat"
[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/install.sh)."
command -v docker >/dev/null 2>&1 || fail "docker belum terinstal. Instal dulu: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin belum ada. Instal 'docker-compose-plugin'."
command -v apache2 >/dev/null 2>&1 || fail "apache2 belum terinstal di server ini."
command -v openssl >/dev/null 2>&1 || fail "openssl belum terinstal."
command -v curl >/dev/null 2>&1 || fail "curl belum terinstal."
[ -f "$REPO_ROOT/apps/api/Dockerfile" ] || fail "apps/api/Dockerfile belum ada (dibangun di Fase 0 oleh tim API)."
ok "Prasyarat terpenuhi."

# ------------------------------------------------- 2. environment (.env)
step "2/6 — Siapkan deploy/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$DEPLOY_DIR/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok "Dibuat dari .env.example"
else
    ok "Sudah ada — tidak ditimpa (idempoten)."
fi

gen_secret() { # $1 = nama var, $2 = panjang hex
    local var="$1" len="$2" val
    val="$(grep -E "^${var}=" "$ENV_FILE" | cut -d= -f2-)"
    if [ "$val" = "CHANGE_ME_GENERATED_BY_INSTALL_SH" ] || [ -z "$val" ]; then
        val="$(openssl rand -hex "$len")"
        sed -i -E "s|^${var}=.*|${var}=${val}|" "$ENV_FILE"
        ok "$var dibuat acak."
    else
        ok "$var sudah terisi — tidak diubah."
    fi
}
gen_secret POSTGRES_PASSWORD 16
gen_secret JWT_SECRET 32

# ------------------------------------------------- 3. docker compose up
step "3/6 — Menjalankan service (docker compose up -d)"
cd "$REPO_ROOT"
docker compose -f "$COMPOSE_FILE" up -d
ok "Container berjalan."

step "Menunggu PostgreSQL sehat (maks 90 dtk)..."
for i in $(seq 1 90); do
    if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -q 2>/dev/null; then
        ok "PostgreSQL sehat."
        break
    fi
    [ "$i" -eq 90 ] && fail "PostgreSQL tidak sehat setelah 90 dtk. Cek: docker compose -f $COMPOSE_FILE logs postgres"
    sleep 1
done

# ------------------------------------------------- 4. migrasi database
step "4/6 — Migrasi database (alembic upgrade head)"
docker compose -f "$COMPOSE_FILE" exec -T api alembic upgrade head \
    || fail "Migrasi gagal. Cek: docker compose -f $COMPOSE_FILE logs api"
ok "Migrasi selesai."

# ------------------------------------------------- 5. vhost Apache
step "5/6 — Pasang vhost Apache netra.mamura.net.id"
mkdir -p "$DOCROOT"
# Placeholder bila frontend (Fase 2) belum di-build — diganti update.sh.
if [ ! -f "$DOCROOT/index.html" ]; then
    cat > "$DOCROOT/index.html" <<'HTML'
<!doctype html><html lang="id"><head><meta charset="utf-8"><title>NetraVision</title></head>
<body style="font-family:sans-serif;text-align:center;padding:4rem">
<h1>NetraVision v3.0</h1><p>Fondasi terpasang. Frontend menyusul di Fase 2.</p>
</body></html>
HTML
    ok "Placeholder index.html dipasang (frontend Fase 2 akan mengganti)."
fi
cp "$VHOST_SRC" "$VHOST_DST"
a2enmod -q proxy proxy_http proxy_wstunnel rewrite ssl headers \
    || fail "Gagal mengaktifkan modul Apache."
a2ensite -q netra.mamura.net.id \
    || fail "Gagal a2ensite netra.mamura.net.id."
apachectl configtest || fail "apachectl configtest GAGAL — perbaiki vhost dulu."
systemctl reload apache2 || fail "Gagal reload apache2."
ok "Vhost aktif. Port 80/443 tetap milik Apache; vhost lain tidak disentuh."

# ------------------------------------------------- 6. health check
step "6/6 — Health check"
sleep 3
if curl -sf -o /dev/null --max-time 10 http://127.0.0.1:8100/api/health; then
    ok "GET /api/health -> OK"
else
    fail "Health check GAGAL. Cek: docker compose -f $COMPOSE_FILE logs api"
fi

echo -e "\n\033[1;32m==============================================\033[0m"
echo -e "\033[1;32m NetraVision v3.0 fondasi TERPASANG.\033[0m"
echo -e "\033[1;32m==============================================\033[0m"
echo "  API      : http://127.0.0.1:8100/api/health (via Apache: https://netra.mamura.net.id/api/health)"
echo "  WebRTC   : UDP 8189 langsung ke server; sinyal via https://netra.mamura.net.id/whep/"
echo "  Update berikutnya: sudo ./deploy/update.sh"
