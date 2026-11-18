# NetraVision v3.0 - API (FastAPI)
# Di-pin ke 3.13.18-slim (terverifikasi ada di Docker Hub, 2026-11-18).
# Daftar versi yang dipakai ada di deploy/VERSIONS.md.
FROM python:3.13.18-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Non-root: service api di docker-compose.yml berjalan sebagai uid 10001.
# Volume recordings/apidata/gdrive_staging harus dimiliki uid ini
# (deploy/fix-volume-perms.sh, dipanggil install.sh/update.sh).
# CATATAN: jangan tambah `--workers 2` di CMD, rate limit, klaim upload,
# lockout login, dan state OAuth disimpan in-memory per proses dan hanya
# benar untuk satu worker uvicorn (lihat app/core/rate_limit.py dan
# app/services/upload_claims.py).
RUN groupadd -r netra -g 10001 \
 && useradd -r -g netra -u 10001 -d /srv/api -s /usr/sbin/nologin netra

WORKDIR /srv/api

COPY pyproject.toml requirements.lock ./
# ffmpeg/rclone: tanpa pin versi apt eksplisit (lihat deploy/VERSIONS.md -
# pin `ffmpeg=7.*` bukan spesifikasi apt yang valid dan memecahkan build
# saat snapshot Debian bergeser; reproduktibilitas dikunci lewat digest
# image bila dibutuhkan).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg rclone \
 && rm -rf /var/lib/apt/lists/* \
 && pip install -r requirements.lock \
 && pip install . --no-deps

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Service `migrate` di compose berjalan sebagai root (user: "0:0") dan
# tidak memakai USER ini; api (long-running) memakainya.
USER netra

EXPOSE 8000

# Liveness di dalam image (selain healthcheck di docker-compose.yml),
# supaya image tetap punya healthcheck bila dijalankan di luar Compose.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)"

# Migrasi dijalankan oleh deploy/update.sh sebelum container di-restart.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
