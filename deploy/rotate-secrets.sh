#!/usr/bin/env bash
#
# NetraVision v3.0 - rotate-secrets.sh
# Rotasi secret deployment (JWT, Redis, Postgres) dengan aman.
#
# YANG DIROTASI (satu atau semua, default: tanya satu per satu):
#   --jwt       JWT_SECRET di deploy/.env + restart api.
#               Efek: SEMUA sesi login (user + embed) tidak berlaku;
#               pengguna harus login ulang. Refresh token lama ditolak.
#   --redis     REDIS_PASSWORD di deploy/.env + restart redis + api.
#   --postgres  Password user Postgres: ALTER USER dulu (di dalam DB),
#               lalu ubah deploy/.env, lalu restart api. Database
#               TIDAK dihapus; hanya kredensial yang berubah.
#   --all       Ketiganya, berurutan.
#
# YANG TIDAK DIROTASI (sengaja):
#   - DRIVE_TOKEN_KEY: kunci Fernet mengenkripsi SEMUA token OAuth Drive
#     di DB. Menggantinya membuat token lama tidak bisa didekripsi dan
#     semua akun Drive harus dihubungkan ulang. Prosedur manual ada di
#     docs/GOOGLE-DRIVE.md §5 — jangan otomatiskan di sini.
#   - MEDIAMTX_API_PASSWORD: disimpan di DB (system_settings) dan
#     ditulis ke deploy/mediamtx.yml oleh service migrate. Rotasi
#     butuh update DB + regenerate yml + restart mediamtx; belum
#     diotomasi — lakukan manual bila dicurigai bocor.
#
# Opsi:
#   --jwt | --redis | --postgres | --all
#   --yes   lewati konfirmasi
#
# Contoh: sudo ./deploy/rotate-secrets.sh --jwt --yes

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
ENV_FILE="$DEPLOY_DIR/.env"

DO_JWT=""; DO_REDIS=""; DO_PG=""
YES=""
for arg in "$@"; do
    case "$arg" in
        --jwt) DO_JWT="1" ;;
        --redis) DO_REDIS="1" ;;
        --postgres) DO_PG="1" ;;
        --all) DO_JWT="1"; DO_REDIS="1"; DO_PG="1" ;;
        --yes) YES="1" ;;
        *) echo -e "\033[1;31m[ FAIL ]\033[0m Opsi tidak dikenal: $arg (pakai --jwt, --redis, --postgres, --all, --yes)." >&2; exit 1 ;;
    esac
done

step()  { echo -e "\n\033[1;34m[rotate-secrets]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/rotate-secrets.sh)."
command -v docker >/dev/null 2>&1 || fail "docker belum terinstal."
command -v openssl >/dev/null 2>&1 || fail "openssl belum terinstal."
[ -f "$ENV_FILE" ] || fail "deploy/.env belum ada - jalankan install.sh dulu."
[ -n "$DO_JWT$DO_REDIS$DO_PG" ] || fail "Pilih yang dirotasi: --jwt, --redis, --postgres, atau --all."

confirm() { # $1 = pertanyaan
    if [ -n "$YES" ]; then return 0; fi
    local jawab=""
    read -r -p "$1 [y/N] " jawab || true
    [[ "${jawab:-}" =~ ^[Yy]$ ]]
}

set_env() { # $1 = var, $2 = nilai baru (ganti baris atau tambahkan)
    local var="$1" val="$2"
    if grep -qE "^${var}=" "$ENV_FILE"; then
        sed -i -E "s|^${var}=.*|${var}=${val}|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$var" "$val" >> "$ENV_FILE"
    fi
    chmod 600 "$ENV_FILE"
}

cd "$REPO_ROOT"

if [ -n "$DO_JWT" ]; then
    step "Rotasi JWT_SECRET"
    confirm "Semua sesi login akan tidak berlaku dan pengguna harus login ulang. Lanjut?" \
        || fail "Dibatalkan."
    NEW_JWT="$(openssl rand -hex 32)"
    set_env JWT_SECRET "$NEW_JWT"
    docker compose -f "$COMPOSE_FILE" up -d api \
        || fail "Restart api gagal setelah rotasi JWT - periksa .env dan logs."
    ok "JWT_SECRET dirotasi (64 hex baru) + api di-restart."
fi

if [ -n "$DO_REDIS" ]; then
    step "Rotasi REDIS_PASSWORD"
    confirm "Redis + api akan di-restart (sesi/rate-limit in-memory hilang sesaat). Lanjut?" \
        || fail "Dibatalkan."
    NEW_REDIS="$(openssl rand -hex 16)"
    set_env REDIS_PASSWORD "$NEW_REDIS"
    docker compose -f "$COMPOSE_FILE" up -d redis api \
        || fail "Restart redis/api gagal setelah rotasi - periksa .env dan logs."
    ok "REDIS_PASSWORD dirotasi + redis/api di-restart."
fi

if [ -n "$DO_PG" ]; then
    step "Rotasi POSTGRES_PASSWORD"
    confirm "Password user Postgres diubah di DB lalu .env; api di-restart. Lanjut?" \
        || fail "Dibatalkan."
    PG_USER="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2- || true)"
    PG_USER="${PG_USER:-netravision}"
    PG_DB="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2- || true)"
    PG_DB="${PG_DB:-netravision}"
    NEW_PG="$(openssl rand -hex 16)"
    # 1. Ubah dulu di DB (agar tidak ada jendela .env baru + password lama).
    # Escape kutip tunggal untuk SQL string literal.
    ESCAPED="${NEW_PG//\'/\'\'}"
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
        psql -U "$PG_USER" -d "$PG_DB" -c "ALTER USER \"$PG_USER\" WITH PASSWORD '$ESCAPED';" \
        || fail "ALTER USER gagal - .env BELUM diubah (password lama masih berlaku)."
    # 2. Baru ubah .env, lalu restart api (dan postgres, supaya env konsisten).
    set_env POSTGRES_PASSWORD "$NEW_PG"
    docker compose -f "$COMPOSE_FILE" up -d postgres api \
        || fail "Restart gagal setelah rotasi Postgres - .env sudah berisi password baru; periksa logs."
    ok "POSTGRES_PASSWORD dirotasi + postgres/api di-restart."
fi

echo -e "\n\033[1;32mRotasi selesai.\033[0m"
echo "  TIDAK dirotasi (sengaja): DRIVE_TOKEN_KEY, MEDIAMTX_API_PASSWORD - lihat header skrip ini."
echo "  Verifikasi: curl -sf http://127.0.0.1:\$(grep -E '^API_PORT=' $ENV_FILE | cut -d= -f2-)/api/health"
