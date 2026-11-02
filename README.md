# NetraVision v3.0

Sistem monitoring CCTV modern — tulis ulang penuh dari v2.0 ("Mamura Stream").
Deploy di `netra.mamura.net.id`, berdampingan dengan virtualhost Apache lain
(port 80/443 tetap milik Apache).

## Struktur monorepo

```
apps/
  api/        # Backend: FastAPI modular (Python), async SQLAlchemy 2, Alembic
  web/        # Frontend: Next.js + React 19 + TypeScript + Tailwind (static export)
  detector/   # Worker AI detection (YOLO) — MODUL OPSIONAL, enable/disable
packages/
  contracts/  # Kontrak OpenAPI (sumber kebenaran API; tipe TS digenerate)
deploy/
  apache/         # vhost netra.mamura.net.id
  docker-compose.yml
  mediamtx.yml
  install.sh      # instalasi idempoten dari bash
  update.sh       # pembaruan: pull → build → migrasi → restart
docs/
  BLUEPRINT.md        # arsitektur (disalin dari perencanaan)
  MIGRATION-MAP.md    # peta 52 endpoint → router
  SECURITY-CHECKLIST.md
```

## Dokumen perencanaan

Sumber keputusan ada di `~/workspace/netravision-v3/` (BLUEPRINT.md, MIGRATION-MAP.md).
Aturan yang dikunci:

- **Tidak ada fitur/grouping yang dihilangkan** — hanya diperbarui
- Path `/api/*` kompatibel; kontrak `/api/external/*` **tidak berubah**
- Sub stream + main stream dipertahankan (sub untuk grid, main untuk fokus)
- Brand-aware stream resolver: ONVIF → template brand → pola generik
- Mobile & desktop dua-duanya first-class; PWA
- Rekaman: lokal / Google Drive / keduanya (per kamera)
- AI detection: modul opsional (enable/disable)

## Fase

- **Fase 0** — Fondasi (repo, kontrak, DB, infra, CI) ← sekarang
- Fase 1 — API inti (auth, RBAC, streams, WebSocket)
- Fase 2 — Web v3.0 (live, playback, peta, admin)
- Fase 3 — Rekaman & embed + migrasi data v2.0
- Fase 4 — Hardening (checklist audit, observability, uji beban, PWA)
- Fase 5 — Cutover (berdampingan → alih domain → v2.0 pensiun)

Setiap fase: demo + gate persetujuan sebelum lanjut. Push ≠ deploy.
