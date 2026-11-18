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
#   7. Pasang cron backup harian (deploy/backup-db.cron ->
#      /etc/cron.d/netravision-backup), idempoten: hanya disalin bila
#      belum ada atau isinya berbeda; path repo di jadwal disesuaikan
#      dengan lokasi repo ini (D4).
#
# API_PORT dibaca dari env shell, lalu deploy/.env, lalu default 8100 -
# harus sama dengan nilai yang dipakai docker-compose.yml
# ("127.0.0.1:${API_PORT:-8100}:8000") dan update.sh.
#
# Contoh: sudo ./deploy/install.sh   (dari root repo)

set -euo pipefail

# Cek root PALING AWAL, sebelum langkah 0 (Apache/preflight) yang butuh
# root juga; bila terlambat, pengguna non-root mendapat error membingungkan
# dulu baru diberitahu harus sudo.
[ "$EUID" -eq 0 ] || { echo -e "\033[1;31m[ FAIL ]\033[0m Jalankan sebagai root (sudo ./deploy/install.sh)." >&2; exit 1; }

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
        if grep -qE "^${var}=" "$ENV_FILE"; then
            sed -i -E "s|^${var}=.*|${var}=${val}|" "$ENV_FILE"
        else
            # Baris belum ada (mis. .env.example lama): tambahkan, bukan diam.
            printf '%s=%s\n' "$var" "$val" >> "$ENV_FILE"
        fi
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
        if grep -qE "^${var}=" "$ENV_FILE"; then
            sed -i -E "s|^${var}=.*|${var}=${val}|" "$ENV_FILE"
        else
            printf '%s=%s\n' "$var" "$val" >> "$ENV_FILE"
        fi
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

# WEBRTC_ADDITIONAL_HOST (wajib, D1): IP/domain publik server untuk
# kandidat ICE WebRTC. docker-compose.yml memakai ${WEBRTC_ADDITIONAL_HOST:?}
# dan compose GAGAL bila kosong, gagalkan di sini dengan pesan yang jelas,
# jangan biarkan gagal di `docker compose up`.
# Prioritas: env shell WEBRTC_ADDITIONAL_HOST > nilai di .env > DOMAIN.
# DOMAIN adalah domain publik server ini, jadi default yang masuk akal.
ensure_webrtc_host() {
    local val="${WEBRTC_ADDITIONAL_HOST:-}"
    if [ -z "$val" ]; then
        val="$(grep -E '^WEBRTC_ADDITIONAL_HOST=' "$ENV_FILE" | cut -d= -f2- || true)"
    fi
    # Bersihkan bila operator menempel URL lengkap (https://domain/).
    val="${val#https://}"; val="${val#http://}"; val="${val%%/*}"
    if [ -z "$val" ] || [ "$val" = "CHANGE_ME_GENERATED_BY_INSTALL_SH" ]; then
        val="$DOMAIN"
        ok "WEBRTC_ADDITIONAL_HOST kosong - diisi default dari DOMAIN ($DOMAIN)."
    fi
    case "$val" in
        *[!A-Za-z0-9._:-]*) fail "WEBRTC_ADDITIONAL_HOST tidak valid: '$val' (isi IP/domain publik tanpa skema, contoh: $DOMAIN)." ;;
    esac
    if grep -qE '^WEBRTC_ADDITIONAL_HOST=' "$ENV_FILE"; then
        sed -i -E "s|^WEBRTC_ADDITIONAL_HOST=.*|WEBRTC_ADDITIONAL_HOST=${val}|" "$ENV_FILE"
    else
        printf '%s=%s\n' "WEBRTC_ADDITIONAL_HOST" "$val" >> "$ENV_FILE"
    fi
    ok "WEBRTC_ADDITIONAL_HOST=$val"
}
ensure_webrtc_host

# APP_ENV (K1): guard JWT_SECRET di app menolak secret default/pendek
# SELALU (bukan hanya bila APP_ENV=prod). Pastikan variabel ini ada di
# .env (default prod) dan gagalkan bila memakai secret placeholder/pendek.
if ! grep -qE '^APP_ENV=' "$ENV_FILE"; then
    printf '%s=%s\n' "APP_ENV" "prod" >> "$ENV_FILE"
    ok "APP_ENV tidak ada - diisi prod (default aman)."
fi
APP_ENV_VAL="$(grep -E '^APP_ENV=' "$ENV_FILE" | cut -d= -f2-)"
JWT_VAL="$(grep -E '^JWT_SECRET=' "$ENV_FILE" | cut -d= -f2-)"
if [ "$JWT_VAL" = "CHANGE_ME_GENERATED_BY_INSTALL_SH" ] || [ "${#JWT_VAL}" -lt 32 ]; then
    fail "JWT_SECRET masih placeholder/pendek (<32 karakter). Isi JWT_SECRET acak di deploy/.env lalu jalankan ulang."
fi
[ "$APP_ENV_VAL" = "prod" ] || warn "APP_ENV=$APP_ENV_VAL (bukan prod) - JANGAN pakai setting ini di server publik."

# mediamtx.yml harus sudah ada sebagai FILE sebelum `docker compose up`:
# service `migrate` me-mount ./mediamtx.yml sebagai file; bila belum ada,
# Docker membuatnya sebagai DIREKTORI dan setup_mediamtx gagal.
# write_text() mempertahankan mode file yang sudah ada, jadi 600 di sini
# membuat file hasil generate tetap hanya bisa dibaca owner (berisi
# password control API MediaMTX).
if [ ! -f "$DEPLOY_DIR/mediamtx.yml" ]; then
    touch "$DEPLOY_DIR/mediamtx.yml"
    ok "deploy/mediamtx.yml dibuat (kosong, akan diisi service migrate)."
fi
chmod 600 "$DEPLOY_DIR/mediamtx.yml" 2>/dev/null || warn "Gagal chmod 600 deploy/mediamtx.yml - periksa manual."

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

# API berjalan non-root (uid 10001, lihat Dockerfile + compose); volume
# recordings/apidata/gdrive_staging harus dimiliki uid itu, kalau tidak
# API gagal menulis rekaman/upload. Perbaiki kepemilikan sekali di sini
# (idempoten; gagal = peringatan, jalankan manual bila perlu).
if [ -x "$DEPLOY_DIR/fix-volume-perms.sh" ]; then
    "$DEPLOY_DIR/fix-volume-perms.sh" \
        || warn "fix-volume-perms.sh gagal - jalankan manual: sudo ./deploy/fix-volume-perms.sh"
else
    warn "deploy/fix-volume-perms.sh tidak ditemukan - lewati perbaikan izin volume."
fi

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
# Samakan dengan update.sh: -w dan PYTHONPATH eksplisit supaya alembic
# menemukan modul 'app' apa pun WORKDIR default image-nya.
docker compose -f "$COMPOSE_FILE" exec -T -w /srv/api \
    -e PYTHONPATH=/srv/api api alembic upgrade head \
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
# Sesuaikan ServerName dengan domain yang dipakai - HANYA baris ServerName,
# lalu path sertifikat ikut domain (certbot membuat sertifikat per domain).
# (G-S2: dulu sed global mengganti path sertifikat tapi sertifikat domain
# baru belum ada sehingga configtest gagal belakangan; di sini keberadaan
# sertifikat dicek LANGSUNG di bawah, jadi gagalnya dini dan pesannya jelas.)
sed -E "s|^([[:space:]]*ServerName[[:space:]]+)netra\.mamura\.net\.id|\1${DOMAIN}|" "$VHOST_SRC" > "$VHOST_DST"
sed -i -E "s|/etc/letsencrypt/live/netra\.mamura\.net\.id/|/etc/letsencrypt/live/${DOMAIN}/|g" "$VHOST_DST"
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

# ------------------------------------------------- 7. cron backup harian
step "7/6 - Pasang cron backup harian (idempoten)"
# D4: backup-db.cron sebelumnya tidak pernah terpasang otomatis.
# Pasang dari sini (install.sh dijalankan sekali saat setup awal dan
# idempoten). Jadwal di backup-db.cron memakai path contoh
# /opt/netravision; ganti hanya path skripnya dengan REPO_ROOT repo ini
# supaya cron benar-benar jalan di server ini (baris komentar manual di
# file itu tidak ikut berubah). Bila file tujuan sudah ada dan isinya
# sama, tidak disalin ulang (tanpa duplikasi).
CRON_SRC="$DEPLOY_DIR/backup-db.cron"
CRON_DST="/etc/cron.d/netravision-backup"
if [ -f "$CRON_SRC" ]; then
    TMP_CRON="$(mktemp)"
    sed "s|/opt/netravision/deploy/backup-db.sh|$REPO_ROOT/deploy/backup-db.sh|" "$CRON_SRC" > "$TMP_CRON"
    if [ -f "$CRON_DST" ] && cmp -s "$TMP_CRON" "$CRON_DST"; then
        ok "Cron backup harian sudah terpasang dan sama - tidak diubah."
    elif cp "$TMP_CRON" "$CRON_DST"; then
        chmod 644 "$CRON_DST" || warn "Gagal chmod 644 $CRON_DST - periksa manual."
        ok "Cron backup harian dipasang: $CRON_DST (setiap hari 02:00 WIB)."
    else
        warn "Gagal memasang $CRON_DST - pasang manual: sudo cp $CRON_SRC $CRON_DST && sudo chmod 644 $CRON_DST (sesuaikan path repo di jadwal)."
    fi
    rm -f "$TMP_CRON"
else
    warn "deploy/backup-db.cron tidak ditemukan - lewati pemasangan cron backup."
fi

echo -e "\n\033[1;32m==============================================\033[0m"
echo -e "\033[1;32m NetraVision v3.0 fondasi TERPASANG.\033[0m"
echo -e "\033[1;32m==============================================\033[0m"
echo "  API      : http://127.0.0.1:${API_PORT}/api/health (via Apache setelah Fase F: https://${DOMAIN}/api/health)"
echo "  WebRTC   : UDP 8189 langsung ke server; sinyal via https://${DOMAIN}/whep/"
echo "  Lanjut ke CUTOVER Fase D (migrasi data), lalu Fase F untuk switch vhost."
echo "  Update berikutnya: sudo ./deploy/update.sh"
