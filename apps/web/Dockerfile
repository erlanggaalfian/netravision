# NetraVision v3.0 - Web (Next.js static export)
# Multi-stage: build di Node, hasil akhirnya hanya direktori out/.
#
# Dipakai CI (.github/workflows/ci.yml) untuk memastikan build web
# reproduktif tanpa bergantung pada Node di host:
#   docker build -f apps/web/Dockerfile apps/web
# Untuk mengekstrak hasil build ke host (tanpa menjalankan server):
#   docker build -o type=local,dest=./out -f apps/web/Dockerfile apps/web
# Di server produksi, deploy/update.sh tetap memakai pola lama
# (docker run node ... npm ci && npm run build) supaya out/ dihasilkan
# di host untuk swap atomik ke DocumentRoot Apache.
#
# Di-pin ke 20.19.6-alpine (terverifikasi ada di Docker Hub, 2026-11-18).
# Daftar versi yang dipakai ada di deploy/VERSIONS.md.

FROM node:20.19.6-alpine AS build
WORKDIR /app
# Cache layer dependensi: salin manifest dulu, baru sisa kode.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# next.config.ts: output "export" -> hasil di /app/out (disajikan Apache).
RUN npm run build

# Stage akhir hanya berisi hasil export statis (tanpa Node, tanpa source).
FROM scratch AS export
COPY --from=build /app/out /out
