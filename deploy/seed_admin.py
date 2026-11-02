#!/usr/bin/env python3
"""Seed admin awal NetraVision v3.0. IDEMPOTEN: user yang sudah ada dilewati.

Dipanggil deploy/install.sh (di dalam container api):
  docker compose run --rm -v ./deploy/seed_admin.py:/seed_admin.py:ro \\
      -e PYTHONPATH=/srv/api -e NV_ADMIN_USER -e NV_ADMIN_PASS \\
      api python /seed_admin.py

Env wajib: NV_ADMIN_USER, NV_ADMIN_PASS (exit 2 bila kosong),
           DATABASE_URL (sudah ada di deploy/.env via compose env_file).
"""

from __future__ import annotations

import asyncio
import os
import sys

try:
    from app.models.users import User  # bila dijalankan dengan PYTHONPATH=/srv/api
except ImportError:
    sys.path.insert(0, os.environ.get("APP_SRC", "/srv/api"))
    from app.models.users import User

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.security import hash_password


async def ensure_admin(username: str, password: str, db_url: str) -> str:
    """Buat admin bila belum ada. Kembalikan 'created' | 'exists'."""
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            existing = (
                await session.execute(
                    select(User).where(User.username == username)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return "exists"
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role="admin",
                    is_active=True,
                )
            )
            await session.commit()
            return "created"
    finally:
        await engine.dispose()


def main() -> int:
    username = os.environ.get("NV_ADMIN_USER", "").strip()
    password = os.environ.get("NV_ADMIN_PASS", "")
    if not username or not password:
        print(
            "SEED ADMIN DILEWATI: set NV_ADMIN_USER dan NV_ADMIN_PASS "
            "untuk membuat admin awal (bukan error).",
            file=sys.stderr,
        )
        return 2
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("GAGAL: DATABASE_URL kosong.", file=sys.stderr)
        return 1
    hasil = asyncio.run(ensure_admin(username, password, db_url))
    if hasil == "created":
        print(f"Admin '{username}' dibuat.")
    else:
        print(f"Admin '{username}' sudah ada — dilewati (idempoten).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
