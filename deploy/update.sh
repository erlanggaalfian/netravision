#!/usr/bin/env bash
#
# NetraVision v3.0 - update.sh
# Update di server produksi. IDEMPOTEN: aman dijalankan ulang.
#
# Yang dilakukan:
#   0. Backup pra-update (WAJIB kecuali --no-backup): SHA git lama,
#      revisi alembic saat ini, pg_dump database ke
#      /backup/netravision-v3-<timestamp>.sql.gz, dan snapshot
#      DocumentRoot (docroot.tar.gz). Pointer ke backup terbaru:
#      /backup/netravision-v3-latest (symlink). Dipakai
#      deploy/rollback-v3.sh bila update gagal.
#   1. git pull (fast-forward only) atau checkout tag bila UPDATE_REF
#      diisi tag rilis. CATATAN: gate CI belum ditegakkan, belum ada
#      tag rilis (lihat deploy/VERSIONS.md); update masih menarik
#      branch saat ini. Jangan jadikan ini satu-satunya pengaman.
#   2. Build frontend (Next.js static export -> DocumentRoot Apache)
#      secara ATOMIK: build ke staging out.new-<sha>, lalu swap dengan
#      mv (bukan rsync --delete langsung ke DocumentRoot yang sedang
#      disajikan). Rilis lama disimpan (2 terakhir).
#   3. docker compose up -d --build
#   4. Migrasi database (alembic upgrade head) - SETELAH rebuild, supaya
#      image baru (yang berisi file migrasi baru) yang menjalankannya
#   5. Health check GET /api/health
#   6. Smoke test (mode health-only, tanpa kredensial admin)
#
# API_PORT dibaca dari env shell, lalu deploy/.env, lalu default 8100 -
# harus sama dengan nilai yang dipakai docker-compose.yml
# ("127.0.0.1:${API_PORT:-8100}:8000").
#
# Opsi:
#   --no-backup    lewati backup pra-update (TIDAK disarankan; hanya
#                  untuk darurat bila /backup penuh / postgres mati)
#   --allow-dirty  izinkan git pull walau working tree kotor
#
# Contoh: sudo ./deploy/update.sh   (dari root repo)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
DOCROOT="/var/www/netravision/out"
BACKUP_ROOT="/backup"
# Belum diputuskan di sini: dibaca dari deploy/.env setelah cek file di bawah.
API_PORT="${API_PORT:-}"
# Tag rilis yang sudah lolos CI, bila ada (mis. UPDATE_REF=v3.1.0).
# Kosong = tarik branch saat ini dengan git pull --ff-only (perilaku lama).
UPDATE_REF="${UPDATE_REF:-}"
NO_BACKUP=""
ALLOW_DIRTY=""
for arg in "$@"; do
    case "$arg" in
        --no-backup) NO_BACKUP="1" ;;
        --allow-dirty) ALLOW_DIRTY="1" ;;
        *) echo -e "\033[1;31m[ FAIL ]\033[0m Opsi tidak dikenal: $arg (pakai --no-backup, --allow-dirty)." >&2; exit 1 ;;
    esac
done

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

# ---------------------------------------------------------------- 0. backup pra-update
# Backup adalah satu-satunya jaring pengaman bila migrasi / build gagal.
# Tanpa ini, rollback-v3.sh tidak punya apa-apa untuk dikembalikan.
BACKUP_DIR=""
if [ -z "$NO_BACKUP" ]; then
    step "0/6 - Backup pra-update (database + DocumentRoot + SHA git)"
    [ -z "$(git status --porcelain)" ] || { [ -n "$ALLOW_DIRTY" ] || fail "Working tree kotor - commit/stash dulu, atau jalankan dengan --allow-dirty."; warn "Working tree kotor - lanjut karena --allow-dirty."; }
    TS="$(date +%Y%m%d%H%M%S)"
    BACKUP_DIR="$BACKUP_ROOT/netravision-v3-$TS"
    mkdir -p "$BACKUP_DIR" || fail "Tidak bisa membuat $BACKUP_DIR - periksa izin /backup."
    SHA_OLD="$(git rev-parse HEAD)"
    # D2: `alembic current` mencetak "<revisi> (head)"; simpan hanya ID
    # revisi murni (potong di spasi pertama) supaya rollback-v3.sh bisa
    # memakainya langsung sebagai `alembic downgrade <revisi>`.
    ALEMBIC_REV_OLD="$(docker compose -f "$COMPOSE_FILE" exec -T api alembic current 2>/dev/null | head -1 || echo unknown)"
    ALEMBIC_REV_OLD="${ALEMBIC_REV_OLD%% *}"
    [ -n "$ALEMBIC_REV_OLD" ] || ALEMBIC_REV_OLD="unknown"
    {
        echo "timestamp=$TS"
        echo "sha_old=$SHA_OLD"
        echo "branch=$(git rev-parse --abbrev-ref HEAD)"
        echo "alembic_rev_old=$ALEMBIC_REV_OLD"
    } > "$BACKUP_DIR/manifest.txt"
    # pg_dump: postgres harus sedang berjalan (instalasi lama). Bila mati,
    # JANGAN lanjut tanpa backup - gagalkan, kecuali --no-backup.
    PG_USER="$(grep -E '^POSTGRES_USER=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
    PG_USER="${PG_USER:-netravision}"
    PG_DB="$(grep -E '^POSTGRES_DB=' "$DEPLOY_DIR/.env" | cut -d= -f2- || true)"
    PG_DB="${PG_DB:-netravision}"
    if docker compose -f "$COMPOSE_FILE" ps -q postgres >/dev/null 2>&1 \
        && [ -n "$(docker compose -f "$COMPOSE_FILE" ps -q postgres 2>/dev/null)" ]; then
        docker compose -f "$COMPOSE_FILE" exec -T postgres \
            pg_dump -U "$PG_USER" -d "$PG_DB" \
            | gzip > "$BACKUP_DIR/db.sql.gz" \
            || fail "pg_dump gagal - update dibatalkan (database belum diubah). Jalankan dengan --no-backup hanya bila sadar risikonya."
        gzip -t "$BACKUP_DIR/db.sql.gz" || fail "File backup db.sql.gz korup (gzip -t gagal)."
        [ -s "$BACKUP_DIR/db.sql.gz" ] || fail "File backup db.sql.gz kosong."
        ok "pg_dump tersimpan: $BACKUP_DIR/db.sql.gz"
    else
        fail "Container postgres tidak berjalan - pg_dump tidak bisa dibuat. Nyalakan stack dulu (docker compose up -d) atau jalankan dengan --no-backup bila sadar risikonya."
    fi
    # Snapshot DocumentRoot (bila sudah ada).
    if [ -d "$DOCROOT" ]; then
        tar czf "$BACKUP_DIR/docroot.tar.gz" -C "$(dirname "$DOCROOT")" "$(basename "$DOCROOT")" \
            || fail "Snapshot DocumentRoot gagal."
        ok "Snapshot DocumentRoot tersimpan: $BACKUP_DIR/docroot.tar.gz"
    else
        warn "DocumentRoot $DOCROOT belum ada - tidak ada snapshot frontend."
    fi
    ln -sfn "$BACKUP_DIR" "$BACKUP_ROOT/netravision-v3-latest"
    ok "Backup pra-update selesai: $BACKUP_DIR (SHA lama $SHA_OLD)"
else
    warn "Backup pra-update DILEWATI (--no-backup). Rollback v3 tidak punya dump terbaru bila update ini gagal."
fi

# ---------------------------------------------------------------- 1. git pull / checkout tag
step "1/6 - Ambil kode terbaru"
if [ -n "$UPDATE_REF" ]; then
    # Tag rilis (sudah lolos CI) lebih aman daripada main mentah.
    git fetch --tags || fail "git fetch --tags gagal."
    git rev-parse "$UPDATE_REF^{tag}" >/dev/null 2>&1 \
        || fail "UPDATE_REF=$UPDATE_REF bukan tag yang dikenal. Cek: git tag -l"
    git checkout "$UPDATE_REF" || fail "git checkout $UPDATE_REF gagal."
    ok "Checkout tag rilis: $UPDATE_REF ($(git rev-parse --short HEAD))"
else
    git pull --ff-only || fail "git pull gagal (ada konflik / bukan fast-forward). Selesaikan manual dulu."
    ok "Repo terbaru: $(git rev-parse --short HEAD)"
fi

# mediamtx.yml harus sudah ada sebagai FILE sebelum `docker compose up`
# (service migrate me-mount-nya sebagai file; bila belum ada, Docker
# membuatnya sebagai DIREKTORI dan setup_mediamtx gagal).
if [ ! -f "$DEPLOY_DIR/mediamtx.yml" ]; then
    touch "$DEPLOY_DIR/mediamtx.yml"
    ok "deploy/mediamtx.yml dibuat (kosong, akan diisi service migrate)."
fi
chmod 600 "$DEPLOY_DIR/mediamtx.yml" 2>/dev/null || warn "Gagal chmod 600 deploy/mediamtx.yml - periksa manual."

# ------------------------------------------------- 2. build frontend (atomik)
step "2/6 - Build frontend"
if [ -f "$REPO_ROOT/apps/web/package.json" ]; then
    # Build di container Node 20.19.6 (di-pin; host bisa Node 18 -
    # Tailwind v4 butuh 20+). Tidak mengganggu aplikasi lain di server.
    # Dockerfile multi-stage tersedia di apps/web/Dockerfile untuk CI;
    # di server tetap dipakai pola lama (docker run) supaya out/ tetap
    # dihasilkan di host untuk swap atomik di bawah.
    docker run --rm -v "$REPO_ROOT/apps/web:/app" -w /app node:20.19.6-alpine \
        sh -c "npm ci && npm run build" \
        || fail "Build frontend gagal."
    [ -d "$REPO_ROOT/apps/web/out" ] || fail "Hasil build apps/web/out tidak ditemukan (cek output: 'export' di next.config)."
    SHA_NEW="$(git rev-parse --short HEAD)"
    STAGING="/var/www/netravision/out.new-$SHA_NEW"
    OLD_KEPT="/var/www/netravision/out.old-$SHA_NEW"
    rm -rf "$STAGING"
    mkdir -p "$(dirname "$DOCROOT")"
    # Salin hasil build ke staging (bukan langsung ke DocumentRoot yang
    # sedang disajikan Apache, pengunjung tidak boleh mendapat campuran
    # file lama+baru selama rsync berjalan).
    if command -v rsync >/dev/null 2>&1; then
        mkdir -p "$STAGING"
        rsync -a "$REPO_ROOT/apps/web/out/" "$STAGING/"
    else
        cp -a "$REPO_ROOT/apps/web/out" "$STAGING"
    fi
    [ -n "$DOCROOT" ] && [ "$DOCROOT" != "/" ] || fail "DOCROOT tidak aman: '$DOCROOT'."
    # Swap: staging -> DocumentRoot, yang lama disimpan sebagai cadangan.
    if [ -d "$DOCROOT" ]; then
        rm -rf "$OLD_KEPT"
        mv "$DOCROOT" "$OLD_KEPT"
    fi
    mv "$STAGING" "$DOCROOT" || fail "Swap DocumentRoot gagal - DocumentRoot lama ada di $OLD_KEPT, pulihkan manual."
    ok "Frontend ter-deploy ke $DOCROOT (rilis lama disimpan di $OLD_KEPT)"
    # Simpan maksimal 2 rilis lama; hapus yang lebih tua.
    ls -dt /var/www/netravision/out.old-* 2>/dev/null | tail -n +3 | while read -r old; do
        [ -n "$old" ] && [ "$old" != "/" ] && rm -rf "$old" && warn "Rilis lama dihapus: $old"
    done
else
    warn "apps/web belum ada (Fase 2) - lewati build frontend."
fi

# ------------------------------------------------- 3. rebuild & restart
# Rebuild DULU: image baru berisi file migrasi baru. Migrasi jalan di
# langkah 4, di dalam image baru (G-K1: migrasi sebelum rebuild membuat
# migrasi baru tidak pernah diterapkan karena image lama tak punya filenya).
step "3/6 - docker compose up -d --build"
docker compose -f "$COMPOSE_FILE" up -d --build \
    || fail "docker compose up gagal. Cek: docker compose -f $COMPOSE_FILE logs"
ok "Semua service berjalan."

# API berjalan non-root (uid 10001); pastikan volume tetap milik uid itu
# setelah rebuild (idempoten; gagal = peringatan, jalankan manual).
if [ -x "$DEPLOY_DIR/fix-volume-perms.sh" ]; then
    "$DEPLOY_DIR/fix-volume-perms.sh" \
        || warn "fix-volume-perms.sh gagal - jalankan manual: sudo ./deploy/fix-volume-perms.sh"
fi

# ------------------------------------------------- 4. migrasi database
step "4/6 - Migrasi database"
if [ -f "$REPO_ROOT/apps/api/Dockerfile" ]; then
    # PYTHONPATH=/srv/api agar alembic menemukan modul 'app'.
    # Dijalankan SETELAH rebuild supaya file migrasi baru sudah ada di image.
    docker compose -f "$COMPOSE_FILE" exec -T -w /srv/api \
        -e PYTHONPATH=/srv/api api alembic upgrade head \
        || fail "Migrasi gagal. Cek: docker compose -f $COMPOSE_FILE logs api - dan pulihkan dengan sudo ./deploy/rollback-v3.sh bila perlu (backup di ${BACKUP_DIR:-/backup/netravision-v3-latest})."
    ok "Migrasi selesai."
else
    warn "apps/api belum ada - lewati migrasi."
fi

# ------------------------------------------------- 5. health check
step "5/6 - Health check"
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
    fail "Health check GAGAL setelah 60 dtk. Cek: docker compose -f $COMPOSE_FILE logs api - dan pulihkan dengan sudo ./deploy/rollback-v3.sh bila perlu (backup di ${BACKUP_DIR:-/backup/netravision-v3-latest})."
fi

# ------------------------------------------------- 6. smoke test (health-only)
step "6/6 - Smoke test (health-only, tanpa kredensial admin)"
# Mode health-only memakai stdlib saja (tanpa httpx) sehingga selalu bisa
# jalan di server. Smoke test lengkap (login/streams/metrics/WS) tetap
# tersedia manual: python3 scripts/smoke_test.py --username ... --password ...
if python3 "$REPO_ROOT/scripts/smoke_test.py" --health-only \
        --base-url "http://127.0.0.1:${API_PORT}" --timeout 10; then
    ok "Smoke test health-only lolos."
else
    warn "Smoke test health-only GAGAL - /api/health di langkah 5 lolos, tapi periksa: python3 scripts/smoke_test.py --base-url http://127.0.0.1:${API_PORT} --username <admin> --password <pass>"
fi

echo -e "\n\033[1;32m==============================================\033[0m"
echo -e "\033[1;32m NetraVision v3.0 UPDATE SELESAI.\033[0m"
echo -e "\033[1;32m==============================================\033[0m"
echo "  Revisi   : $(git rev-parse --short HEAD)"
echo "  Backup   : ${BACKUP_DIR:-dilewati (--no-backup)}"
echo "  Publik   : https://netra.mamura.net.id"
