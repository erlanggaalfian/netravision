"""Setup MediaMTX saat deploy: pastikan password ada di DB lalu tulis mediamtx.yml.

Dipakai service `migrate` di docker-compose (setelah `alembic upgrade head`):
    python -m app.db.setup_mediamtx [/deploy]
Membaca template deploy/mediamtx.yml.template dan menulis
deploy/mediamtx.yml dengan password dari database. Idempotent: bila
password sudah ada di DB, dipakai yang itu; bila mediamtx.yml sudah
terisi password yang sama, ditulis ulang dengan isi yang sama.
"""

import asyncio
import logging
import sys
from pathlib import Path

from app.db.session import get_session_factory
from app.services.system_settings import (
    ensure_mediamtx_password,
    render_mediamtx_yml,
)

log = logging.getLogger("netravision.setup_mediamtx")


async def _run(deploy_dir: Path) -> None:
    template_path = deploy_dir / "mediamtx.yml.template"
    output_path = deploy_dir / "mediamtx.yml"
    if not template_path.is_file():
        # Fallback: bila template belum ada (repo lama), pakai
        # mediamtx.yml yang ada sebagai template (harus mengandung
        # placeholder).
        template_path = output_path
    template_text = template_path.read_text(encoding="utf-8")
    factory = get_session_factory()
    async with factory() as db:
        password = await ensure_mediamtx_password(db)
    output_path.write_text(
        render_mediamtx_yml(template_text, password), encoding="utf-8"
    )
    log.info("mediamtx.yml ditulis dari template (password dari database)")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    deploy_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/deploy")
    asyncio.run(_run(deploy_dir))


if __name__ == "__main__":
    main()
