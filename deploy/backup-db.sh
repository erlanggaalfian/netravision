#!/usr/bin/env bash
#
# NetraVision v3.0 - backup-db.sh
# Backup database harian (pg_dump -> gzip) dengan retensi 7 hari.
#
# Dijalankan manual atau via cron (lihat deploy/backup-db.cron):
#   sudo ./deploy/backup-db.sh
#   sudo BACKUP_DIR=/backup ./deploy/backup-db.sh
#
# Output: /backup/netravision-v3-<timestamp>.sql.gz (+ manifest.txt)
# Format sama dengan backup pra-update di deploy/update.sh, sehingga
# deploy/rollback-v3.sh bisa memakai backup ini juga (--backup-dir).
# Retensi: backup berumur >7 hari dihapus otomatis (hanya file
# netravision-v3-*.sql.gz + manifest.txt di BACKUP_DIR).
#
# UJI RESTORE BULANAN (wajib): backup yang tidak pernah diuji restore
# dianggap tidak ada. Prosedur uji ada di docs/ (restore ke database
# sementara, JANGAN ke database produksi):
#   gunzip -c /backup/netravision-v3-<ts>.sql.gz | psql -U netravision -d netravision_test

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
BACKUP_DIR="${BACKUP_DIR:-/backup}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

step()  { echo -e "\n\033[1;34m[backup-db]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[  OK  ]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[ WARN ]\033[0m $*" >&2; }
fail()  { echo -e "\033[1;31m[ FAIL ]\033[0m $*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "Jalankan sebagai root (sudo ./deploy/backup-db.sh)."
command -v docker >/dev/null 2>&1 || fail "docker belum terinstal."
[ -f "$DEPLOY_DIR/.env" ] || fail "deploy/.env belum ada - jalankan install.sh dulu."
mkdir -p "$BACKUP_DIR" || fail "Tidak bisa membuat $BACKUP_DIR."

PG_USER="$(grep -E '^POSTGRES_USER=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
PG_USER="${PG_USER:-netravision}"
PG_DB="$(grep -E '^POSTGRES_DB=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
PG_DB="${PG_DB:-netravision}"

TS="$(date +%Y%m%d%H%M%S)"
OUT_DIR="$BACKUP_DIR/netravision-v3-$TS"
mkdir -p "$OUT_DIR"

step "pg_dump $PG_DB -> $OUT_DIR/db.sql.gz"
docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" \
    | gzip > "$OUT_DIR/db.sql.gz" \
    || fail "pg_dump gagal (pastikan stack berjalan: docker compose -f $COMPOSE_FILE ps)."
gzip -t "$OUT_DIR/db.sql.gz" || fail "File backup korup (gzip -t gagal)."
[ -s "$OUT_DIR/db.sql.gz" ] || fail "File backup kosong."
# D2: `alembic current` mencetak "<revisi> (head)"; simpan hanya ID
# revisi murni (potong di spasi pertama) supaya rollback-v3.sh bisa
# memakainya langsung sebagai `alembic downgrade <revisi>`.
ALEMBIC_REV_OLD="$(docker compose -f "$COMPOSE_FILE" exec -T api alembic current 2>/dev/null | head -1 || echo unknown)"
ALEMBIC_REV_OLD="${ALEMBIC_REV_OLD%% *}"
[ -n "$ALEMBIC_REV_OLD" ] || ALEMBIC_REV_OLD="unknown"
{
    echo "timestamp=$TS"
    echo "sha_old=$(cd "$REPO_ROOT" && git rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "branch=$(cd "$REPO_ROOT" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    echo "alembic_rev_old=$ALEMBIC_REV_OLD"
    echo "source=backup-db.sh (harian)"
} > "$OUT_DIR/manifest.txt"
ln -sfn "$OUT_DIR" "$BACKUP_DIR/netravision-v3-latest"
ok "Backup selesai: $OUT_DIR/db.sql.gz ($(du -h "$OUT_DIR/db.sql.gz" | cut -f1))"

step "Prune backup > $RETENTION_DAYS hari"
# Hanya direktori backup harian/pra-update (netravision-v3-*); symlink
# netravision-v3-latest tidak ikut terhapus (bukan direktori).
find "$BACKUP_DIR" -maxdepth 1 -type d -name 'netravision-v3-*' -mtime "+$RETENTION_DAYS" -print -exec rm -rf {} + \
    || warn "Prune gagal sebagian - periksa manual."
ok "Prune selesai."
