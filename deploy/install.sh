#!/usr/bin/env bash
#
# NetraVision v3.0 - install.sh
# Instalasi / setup awal di server. IDEMPOTEN: aman dijalankan ulang.
#
# Yang dilakukan:
#   0. Pastikan Apache berjalan (start/enable bila perlu), lalu
#      preflight check (scripts/preflight.py) - gagal -> berhenti
#   1. Cek prasyarat (root, docker + compose plugin, apache2)
#   2. Siapkan deploy/.env (dari .env.example; generate secret acak bila
#      placeholder, termasuk DRIVE_TOKEN_KEY untuk aktivasi Drive)
#   3. Hentikan mediamtx v2.0 (melepas UDP 8189), lalu
#      docker compose up -d, tunggu postgres sehat
#   4. Jalankan migrasi Alembic via container api
#   4b. Seed admin awal (opsional; hanya bila NV_ADMIN_USER/PASS diset)
#   5. Siapkan file vhost Apache netra.mamura.net.id - TANPA a2ensite/reload.
#      Pergantian vhost (a2ensite v3 + a2dissite v2 + reload) dilakukan di
#      CUTOVER Fase F (maintenance window); v2.0 tetap melayani sampai sana.
#   6. Health check GET /api/health
#
# API_PORT dibaca dari env shell, lalu deploy/.env, lalu default 8100 -
# harus sama dengan nilai yang dipakai docker-compose.yml
# ("127.0.0.1:${API_PORT:-8100}:8000") dan update.sh.
#
# Contoh: sudo ./deploy/install.sh   (dari root repo)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
ENV_FILE="$DEPLOY_DIR/.env"
# Domain bisa dioverride: DOMAIN=cctv.netbackup.my.id ./install.sh
DOMAIN="${DOMAIN:-netra.mamura.net.id}"
# Port API host; diputuskan setelah .env dibuat (env shell menang).
API_PORT="${API_PORT:-}"
VHOST_SRC="$DEPLOY_DIR/apache/netra.mamura.net.id.conf"
VHOST_DST="/etc/apache2/sites-available/${DOMAIN}.conf"
DOCROOT="/var/www/netravision/out"

step()  { echo -e "\n\033[1;34m[install]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

# ---------------------------------------------------------------- 0. apache + preflight
# Preflight menuntut Apache sudah listen di 80/443 - nyalakan dulu bila
# terinstal tapi belum berjalan (G-S12: tanpa langkah ini server baru
# selalu gagal di preflight).
step "0/6 - Pastikan Apache berjalan"
if command -v apache2 >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1; then
    if ! systemctl is-active --quiet apache2 2>/dev/null; then
        systemctl enable --now apache2 \
            && ok "Apache dinyalakan (enable --now)." \
            || warn "Gagal menyalakan Apache - preflight di bawah akan memberi tahu."
    else
        ok "Apache sudah berjalan."
    fi
else
    warn "apache2/systemctl tidak ada - preflight di bawah akan memberi tahu."
fi

step "0/6 - Preflight check"
python3 "$REPO_ROOT/scripts/preflight.py" \
    || fail "Preflight GAGAL - perbaiki item di atas, lalu jalankan ulang."
ok "Preflight lolos."

# ---------------------------------------------------------------- 1. prasyarat
step "1/6 - Cek prasyarat"
[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/install.sh)."
command -v docker >/dev/null 2>&1 || fail "docker belum terinstal. Instal dulu: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin belum ada. Instal 'docker-compose-plugin'."
command -v apache2 >/dev/null 2>&1 || fail "apache2 belum terinstal di server ini."
command -v openssl >/dev/null 2>&1 || fail "openssl belum terinstal."
command -v curl >/dev/null 2>&1 || fail "curl belum terinstal."
[ -f "$REPO_ROOT/apps/api/Dockerfile" ] || fail "apps/api/Dockerfile belum ada (dibangun di Fase 0 oleh tim API)."
ok "Prasyarat terpenuhi."

# ------------------------------------------------- 2. environment (.env)
step "2/6 - Siapkan deploy/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$DEPLOY_DIR/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok "Dibuat dari .env.example"
else
    ok "Sudah ada - tidak ditimpa (idempoten)."
fi

gen_secret() { # $1 = nama var, $2 = panjang hex
    local var="$1" len="$2" val
    val="$(grep -E "^${var}=" "$ENV_FILE" | cut -d= -f2-)"
    if [ "$val" = "CHANGE_ME_GENERATED_BY_INSTALL_SH" ] || [ -z "$val" ]; then
        val="$(openssl rand -hex "$len")"
        sed -i -E "s|^${var}=.*|${var}=${val}|" "$ENV_FILE"
        ok "$var dibuat acak."
    else
        ok "$var sudah terisi - tidak diubah."
    fi
}
gen_secret POSTGRES_PASSWORD 16
gen_secret JWT_SECRET 32
# G-R5: password Redis internal (compose mewajibkan REDIS_PASSWORD).
gen_secret REDIS_PASSWORD 16

gen_fernet_key() { # DRIVE_TOKEN_KEY: kunci Fernet (base64 urlsafe 32 byte)
    local var="DRIVE_TOKEN_KEY" val
    val="$(grep -E "^${var}=" "$ENV_FILE" | cut -d= -f2-)"
    if [ "$val" = "CHANGE_ME_GENERATED_BY_INSTALL_SH" ] || [ -z "$val" ]; then
        # cryptography bila ada; kalau tidak, openssl + tr ke urlsafe base64.
        if python3 -c "from cryptography.fernet import Fernet" 2>/dev/null; then
            val="$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
        else
            val="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
        fi
        [ "${#val}" -eq 44 ] || fail "Gagal membuat DRIVE_TOKEN_KEY (panjang ${#val}, harus 44)."
        sed -i -E "s|^${var}=.*|${var}=${val}|" "$ENV_FILE"
        ok "$var dibuat acak."
    else
        ok "$var sudah terisi - tidak diubah."
    fi
}
gen_fernet_key

# API_PORT: env shell menang, lalu deploy/.env, lalu default 8100.
if [ -z "$API_PORT" ]; then
    API_PORT="$(grep -E '^API_PORT=' "$ENV_FILE" | cut -d= -f2- || true)"
    API_PORT="${API_PORT:-8100}"
fi

# ------------------------------------------------- 3. docker compose up
# Mediamtx v2.0 masih memegang UDP 8189 -> `compose up` pasti gagal
# (port already allocated). Hentikan dulu; preflight sudah GAGAL bila
# port masih terpakai setelah langkah ini (G-T1).
step "3/6 - Hentikan mediamtx v2.0 (bila masih jalan)"
if command -v systemctl >/dev/null 2>&1 \
    && systemctl list-unit-files 2>/dev/null | grep -q '^mediamtx\.service'; then
    if systemctl is-active --quiet mediamtx 2>/dev/null; then
        systemctl stop mediamtx \
            && ok "mediamtx v2.0 dihentikan (UDP 8189 dibebaskan)." \
            || fail "Gagal menghentikan mediamtx v2.0 - hentikan manual (systemctl stop mediamtx), lalu jalankan ulang."
    else
        ok "mediamtx v2.0 sudah tidak jalan."
    fi
else
    warn "Unit mediamtx tidak ditemukan - anggap v2.0 tidak jalan via systemd."
fi

step "3/6 - Menjalankan service (docker compose up -d)"
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
step "4/6 - Migrasi database (alembic upgrade head)"
docker compose -f "$COMPOSE_FILE" exec -T api alembic upgrade head \
    || fail "Migrasi gagal. Cek: docker compose -f $COMPOSE_FILE logs api"
ok "Migrasi selesai."

# ------------------------------------------------- 4b. seed admin (opsional)
step "4b/6 - Seed admin awal (opsional)"
if [ -n "${NV_ADMIN_USER:-}" ] && [ -n "${NV_ADMIN_PASS:-}" ]; then
    docker compose -f "$COMPOSE_FILE" run --rm \
        -v "$DEPLOY_DIR/seed_admin.py:/seed_admin.py:ro" \
        -e PYTHONPATH=/srv/api \
        -e NV_ADMIN_USER -e NV_ADMIN_PASS \
        api python /seed_admin.py \
        || warn "seed_admin gagal - buat admin manual via API nanti."
else
    warn "NV_ADMIN_USER/NV_ADMIN_PASS tidak diset - lewati seed admin."
fi

# ------------------------------------------------- 5. vhost Apache (siapkan saja)
# HANYA menyiapkan file vhost - TIDAK a2ensite/reload di sini. Pergantian
# vhost (a2ensite v3 + a2dissite v2 + reload) dilakukan di CUTOVER Fase F
# (maintenance window); v2.0 tetap melayani sampai sana (G-T2).
step "5/6 - Siapkan file vhost Apache $DOMAIN (belum diaktifkan)"
mkdir -p "$DOCROOT"
# Placeholder bila frontend (Fase 2) belum di-build - diganti update.sh.
if [ ! -f "$DOCROOT/index.html" ]; then
    cat > "$DOCROOT/index.html" <<'HTML'
<!doctype html><html lang="id"><head><meta charset="utf-8"><title>NetraVision</title></head>
<body style="font-family:sans-serif;text-align:center;padding:4rem">
<h1>NetraVision v3.0</h1><p>Fondasi terpasang. Frontend menyusul di Fase 2.</p>
</body></html>
HTML
    ok "Placeholder index.html dipasang (frontend Fase 2 akan mengganti)."
fi
# Backup vhost lama bila ada (jangan menimpa v2 yang masih hidup tanpa jejak).
# Nama backup berstempel waktu ini yang dipakai rollback.sh (G-S13).
if [ -f "$VHOST_DST" ]; then
    cp "$VHOST_DST" "$VHOST_DST.bak-$(date +%Y%m%d%H%M%S)"
    warn "Vhost lama dibackup sebelum ditimpa."
fi
# Sesuaikan ServerName dengan domain yang dipakai - HANYA baris ServerName.
# (G-S2: sed global dulu ikut mengganti path sertifikat
# /etc/letsencrypt/live/<domain>/... sehingga configtest gagal.)
sed -E "s|^([[:space:]]*ServerName[[:space:]]+)netra\.mamura\.net\.id|\1${DOMAIN}|" "$VHOST_SRC" > "$VHOST_DST"
# Samakan port proxy API dengan API_PORT yang dipakai compose.
sed -i -E "s|127\.0\.0\.1:8100|127.0.0.1:${API_PORT}|g" "$VHOST_DST"
# Validasi sertifikat ADA dulu sebelum vhost ini dipakai (G-S2): bila
# cert untuk $DOMAIN belum ada, gagal di sini dengan pesan jelas, bukan
# di configtest Fase F setelah semua service jalan.
for cert in $(grep -E '^[[:space:]]*SSLCertificate(File|KeyFile)' "$VHOST_DST" | awk '{print $2}'); do
    [ -f "$cert" ] || fail "Sertifikat belum ada: $cert - buat dulu dengan certbot untuk $DOMAIN, lalu jalankan ulang."
done
a2enmod -q proxy proxy_http proxy_wstunnel rewrite ssl headers \
    || fail "Gagal mengaktifkan modul Apache."
ok "File vhost disiapkan di $VHOST_DST (BELUM diaktifkan)."
warn "Pergantian vhost dilakukan di CUTOVER Fase F: a2ensite $DOMAIN + a2dissite <vhost-v2> + reload."
ok "Port 80/443 tetap milik Apache; vhost lain tidak disentuh."

# ------------------------------------------------- 6. health check
step "6/6 - Health check"
sleep 3
if curl -sf -o /dev/null --max-time 10 "http://127.0.0.1:${API_PORT}/api/health"; then
    ok "GET /api/health -> OK"
else
    fail "Health check GAGAL. Cek: docker compose -f $COMPOSE_FILE logs api"
fi

echo -e "\n\033[1;32m==============================================\033[0m"
echo -e "\033[1;32m NetraVision v3.0 fondasi TERPASANG.\033[0m"
echo -e "\033[1;32m==============================================\033[0m"
echo "  API      : http://127.0.0.1:${API_PORT}/api/health (via Apache setelah Fase F: https://${DOMAIN}/api/health)"
echo "  WebRTC   : UDP 8189 langsung ke server; sinyal via https://${DOMAIN}/whep/"
echo "  Lanjut ke CUTOVER Fase D (migrasi data), lalu Fase F untuk switch vhost."
echo "  Update berikutnya: sudo ./deploy/update.sh"
