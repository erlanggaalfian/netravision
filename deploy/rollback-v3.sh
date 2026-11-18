#!/usr/bin/env bash
#
# NetraVision v3.0 - rollback-v3.sh
# Mengembalikan server ke kondisi SEBELUM update v3.x -> v3.y yang gagal.
# Pasangan dari deploy/update.sh (yang membuat backup pra-update).
#
# Yang dilakukan (berurutan):
#   0. Baca manifest backup: SHA git lama, revisi alembic lama, dump DB,
#      snapshot DocumentRoot. Backup default: /backup/netravision-v3-latest
#      (symlink yang dibuat update.sh) atau --backup-dir <dir>.
#   1. git checkout branch lama + reset --hard SHA lama (tetap di branch,
#      bukan detached HEAD, supaya `git pull --ff-only` di update.sh
#      berikutnya tetap bisa jalan; working tree harus bersih, kecuali
#      --force)
#   2. Restore DocumentRoot dari docroot.tar.gz (swap atomik via staging)
#   3. Restore database dari db.sql.gz (JALUR UTAMA - mengembalikan juga
#      tabel alembic_version). Bila dump tidak ada dan revisi alembic
#      berubah, coba `alembic downgrade <revisi-lama>` via service
#      `migrate` one-shot (best-effort) SEBELUM stack di-start ulang,
#      supaya api kode lama tidak start dengan skema baru.
#   4. docker compose up -d --build (image dari kode lama) + health check
#
# PERINGATAN: restore database DESTRUKTIF — data yang masuk SETELAH backup
# (kamera/user/rekaman baru) akan hilang. Konfirmasi interaktif diminta
# kecuali --yes.
#
# Opsi:
#   --backup-dir <dir>  pakai backup tertentu (default: /backup/netravision-v3-latest)
#   --no-restore-db     jangan restore database (hanya kode + frontend)
#   --yes               lewati konfirmasi
#   --force             izinkan working tree kotor
#
# Contoh:
#   sudo ./deploy/rollback-v3.sh
#   sudo ./deploy/rollback-v3.sh --backup-dir /backup/netravision-v3-20261118090000 --yes

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
DOCROOT="/var/www/netravision/out"

BACKUP_DIR="/backup/netravision-v3-latest"
NO_RESTORE_DB=""
YES=""
FORCE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --backup-dir) BACKUP_DIR="${2:-}"; shift 2 ;;
        --no-restore-db) NO_RESTORE_DB="1"; shift ;;
        --yes) YES="1"; shift ;;
        --force) FORCE="1"; shift ;;
        *) echo -e "\033[1;31m[ FAIL ]\033[0m Opsi tidak dikenal: $1" >&2; exit 1 ;;
    esac
done

step()  { echo -e "\n\033[1;34m[rollback-v3]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/rollback-v3.sh)."
command -v docker >/dev/null 2>&1 || fail "docker belum terinstal."
[ -f "$DEPLOY_DIR/.env" ] || fail "deploy/.env belum ada - jalankan install.sh dulu."

# ---------------------------------------------------------------- 0. baca manifest
step "0/4 - Baca backup pra-update"
[ -d "$BACKUP_DIR" ] || fail "Backup tidak ditemukan: $BACKUP_DIR (update.sh membuatnya di /backup/netravision-v3-<timestamp>; symlink terbaru: /backup/netravision-v3-latest)."
[ -f "$BACKUP_DIR/manifest.txt" ] || fail "manifest.txt tidak ada di $BACKUP_DIR - backup tidak lengkap."
# shellcheck disable=SC1090
SHA_OLD="$(grep -E '^sha_old=' "$BACKUP_DIR/manifest.txt" | cut -d= -f2-)"
BRANCH_OLD="$(grep -E '^branch=' "$BACKUP_DIR/manifest.txt" | cut -d= -f2-)"
ALEMBIC_OLD="$(grep -E '^alembic_rev_old=' "$BACKUP_DIR/manifest.txt" | cut -d= -f2-)"
# D2: tahan manifest lama yang menyimpan mentah hasil `alembic current`
# ("<revisi> (head)"); buang suffix itu, pakai hanya ID revisi murni.
ALEMBIC_OLD="${ALEMBIC_OLD%% *}"
[ -n "$SHA_OLD" ] || fail "manifest.txt tidak berisi sha_old."
echo "    Backup dir : $BACKUP_DIR"
echo "    SHA lama   : $SHA_OLD"
echo "    Branch lama: ${BRANCH_OLD:-tidak tercatat}"
echo "    Alembic lama: ${ALEMBIC_OLD:-tidak tercatat}"
echo "    Dump DB    : $([ -f "$BACKUP_DIR/db.sql.gz" ] && echo "$BACKUP_DIR/db.sql.gz" || echo "TIDAK ADA")"
echo "    Docroot    : $([ -f "$BACKUP_DIR/docroot.tar.gz" ] && echo "$BACKUP_DIR/docroot.tar.gz" || echo "TIDAK ADA")"
if [ -z "$YES" ]; then
    echo
    echo "    PERINGATAN: restore database akan MENGHAPUS data yang masuk setelah backup."
    read -r -p "    Lanjutkan rollback ke $SHA_OLD? [y/N] " jawab || true
    [[ "${jawab:-}" =~ ^[Yy]$ ]] || { echo "Dibatalkan."; exit 0; }
fi

cd "$REPO_ROOT"
[ -z "$(git status --porcelain)" ] || { [ -n "$FORCE" ] || fail "Working tree kotor - commit/stash dulu, atau jalankan dengan --force."; warn "Working tree kotor - lanjut karena --force."; }

# ---------------------------------------------------------------- 1. kode lama
step "1/4 - Checkout kode lama ($SHA_OLD)"
# D1: checkout branch lama dulu, lalu reset --hard ke SHA lama, supaya
# HEAD tetap di branch (bukan detached HEAD) dan `git pull --ff-only`
# di update.sh berikutnya tetap bisa jalan.
if [ -n "${BRANCH_OLD:-}" ] && [ "$BRANCH_OLD" != "unknown" ] && [ "$BRANCH_OLD" != "HEAD" ]; then
    git checkout "$BRANCH_OLD" || fail "git checkout $BRANCH_OLD gagal."
    git reset --hard "$SHA_OLD" || fail "git reset --hard $SHA_OLD gagal."
else
    warn "Branch lama tidak tercatat di manifest (manifest lama) - fallback ke checkout SHA (detached HEAD; git pull --ff-only nanti gagal, checkout branch manual)."
    git checkout "$SHA_OLD" || fail "git checkout $SHA_OLD gagal."
fi
ok "Kode dikembalikan ke $(git rev-parse --short HEAD) di branch $(git rev-parse --abbrev-ref HEAD)."

# mediamtx.yml harus ada sebagai file sebelum compose up (lihat update.sh).
if [ ! -f "$DEPLOY_DIR/mediamtx.yml" ]; then
    touch "$DEPLOY_DIR/mediamtx.yml"
fi
chmod 600 "$DEPLOY_DIR/mediamtx.yml" 2>/dev/null || true

# ---------------------------------------------------------------- 2. frontend lama
step "2/4 - Restore DocumentRoot"
if [ -f "$BACKUP_DIR/docroot.tar.gz" ]; then
    # docroot.tar.gz berisi direktori top-level `out/` (dibuat update.sh
    # dengan `tar czf ... -C /var/www/netravision out`).
    STAGING="$(mktemp -d /var/www/netravision/.rollback-staging.XXXXXX)"
    tar xzf "$BACKUP_DIR/docroot.tar.gz" -C "$STAGING" \
        || fail "Ekstrak docroot.tar.gz gagal."
    [ -d "$STAGING/out" ] || fail "docroot.tar.gz tidak berisi direktori out/."
    # Swap: DocumentRoot yang rusak disimpan dulu, baru hasil restore
    # dipindah ke tempatnya (bukan tar langsung ke DocumentRoot, supaya
    # file build baru yang tidak ada di backup tidak tertinggal).
    BROKEN="/var/www/netravision/out.broken-$(date +%Y%m%d%H%M%S)"
    if [ -d "$DOCROOT" ]; then
        mv "$DOCROOT" "$BROKEN" || fail "Gagal memindahkan DocumentRoot lama ke $BROKEN."
    fi
    mv "$STAGING/out" "$DOCROOT" || fail "Gagal memindahkan hasil restore ke $DOCROOT (yang lama ada di ${BROKEN:-})."
    rm -rf "$STAGING"
    ok "DocumentRoot dikembalikan dari docroot.tar.gz (yang rusak disimpan di ${BROKEN:-tidak ada})."
else
    warn "Tidak ada docroot.tar.gz di backup - frontend tidak dipulihkan."
fi

# ---------------------------------------------------------------- 3. database
step "3/4 - Restore database"
if [ -n "$NO_RESTORE_DB" ]; then
    warn "Restore database DILEWATI (--no-restore-db). Bila migrasi sudah jalan, skema DB tetap baru sementara kode sudah lama - periksa alembic current."
elif [ -f "$BACKUP_DIR/db.sql.gz" ]; then
    PG_USER="$(grep -E '^POSTGRES_USER=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
    PG_USER="${PG_USER:-netravision}"
    PG_DB="$(grep -E '^POSTGRES_DB=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
    PG_DB="${PG_DB:-netravision}"
    # Hentikan api dulu supaya tidak ada yang menulis saat restore.
    docker compose -f "$COMPOSE_FILE" stop api 2>/dev/null || true
    docker compose -f "$COMPOSE_FILE" up -d postgres || fail "Gagal menyalakan postgres untuk restore."
    for i in $(seq 1 30); do
        docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -q -U "$PG_USER" -d "$PG_DB" 2>/dev/null && break
        [ "$i" -eq 30 ] && fail "PostgreSQL tidak sehat setelah 30 dtk."
        sleep 1
    done
    gzip -t "$BACKUP_DIR/db.sql.gz" || fail "File backup db.sql.gz korup (gzip -t gagal)."
    # dropdb/createdb: dump berisi CREATE TABLE dst; database harus kosong.
    docker compose -f "$COMPOSE_FILE" exec -T postgres dropdb -U "$PG_USER" --if-exists "$PG_DB" \
        || fail "dropdb gagal."
    docker compose -f "$COMPOSE_FILE" exec -T postgres createdb -U "$PG_USER" -O "$PG_USER" "$PG_DB" \
        || fail "createdb gagal."
    gunzip -c "$BACKUP_DIR/db.sql.gz" \
        | docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -q -v ON_ERROR_STOP=1 \
        || fail "Restore pg_dump gagal - database mungkin setengah ter-restore. Jangan jalankan update lagi sebelum memeriksa manual."
    ok "Database dikembalikan dari $BACKUP_DIR/db.sql.gz."
else
    warn "Tidak ada db.sql.gz di backup - coba alembic downgrade bila revisi berubah."
    if [ -n "${ALEMBIC_OLD:-}" ] && [ "$ALEMBIC_OLD" != "unknown" ]; then
        # D3: downgrade DULU, baru `up -d --build` di langkah 4. Bila api
        # kode lama di-start dulu dengan skema baru, api bisa crash-loop
        # sehingga `exec api alembic downgrade` tidak bisa jalan.
        # Downgrade lewat service `migrate` one-shot (image dibangun dari
        # kode lama hasil checkout langkah 1; argumen run meng-override
        # command default-nya `alembic upgrade head`, jadi tidak ikut
        # meng-upgrade). Postgres harus jalan untuk downgrade ini.
        PG_USER="$(grep -E '^POSTGRES_USER=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
        PG_USER="${PG_USER:-netravision}"
        PG_DB="$(grep -E '^POSTGRES_DB=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
        PG_DB="${PG_DB:-netravision}"
        docker compose -f "$COMPOSE_FILE" stop api 2>/dev/null || true
        docker compose -f "$COMPOSE_FILE" up -d postgres || fail "Gagal menyalakan postgres untuk downgrade."
        for i in $(seq 1 30); do
            docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -q -U "$PG_USER" -d "$PG_DB" 2>/dev/null && break
            [ "$i" -eq 30 ] && fail "PostgreSQL tidak sehat setelah 30 dtk."
            sleep 1
        done
        docker compose -f "$COMPOSE_FILE" build migrate \
            || fail "docker compose build migrate gagal saat persiapan downgrade."
        docker compose -f "$COMPOSE_FILE" run --rm migrate alembic downgrade "$ALEMBIC_OLD" \
            && ok "alembic downgrade ke $ALEMBIC_OLD selesai." \
            || warn "alembic downgrade gagal - data yang dihapus migrasi TIDAK kembali. Pulihkan dari pg_dump manual bila ada."
    else
        warn "Revisi alembic lama tidak tercatat - lewati downgrade."
    fi
fi

# ---------------------------------------------------------------- 4. rebuild + health
step "4/4 - Rebuild stack lama + health check"
docker compose -f "$COMPOSE_FILE" up -d --build \
    || fail "docker compose up gagal. Cek: docker compose -f $COMPOSE_FILE logs"
ok "Semua service berjalan."
if [ -x "$DEPLOY_DIR/fix-volume-perms.sh" ]; then
    "$DEPLOY_DIR/fix-volume-perms.sh" \
        || warn "fix-volume-perms.sh gagal - jalankan manual: sudo ./deploy/fix-volume-perms.sh"
fi
API_PORT="$(grep -E '^API_PORT=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
API_PORT="${API_PORT:-8100}"
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
echo -e "\033[1;32m NetraVision v3.0 ROLLBACK-V3 SELESAI.\033[0m"
echo -e "\033[1;32m==============================================\033[0m"
echo "  Revisi   : $(git rev-parse --short HEAD)"
echo "  Backup   : $BACKUP_DIR"
echo "  Publik   : https://netra.mamura.net.id"
