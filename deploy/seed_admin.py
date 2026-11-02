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
    """Buat admin bila belum ada. Kembalikan 'created' | 'exists'.

    Paritas v2.0: admin PERTAMA memegang peran super_admin (kuasa penuh).
    Idempoten: bila sudah ada super_admin, admin baru dibuat sebagai
    admin biasa; username yang sudah ada tidak diubah.
    """
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
            has_super = (
                await session.execute(
                    select(User.id).where(User.role == "super_admin")
                )
            ).first() is not None
            role = "admin" if has_super else "super_admin"
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    is_active=True,
                )
            )
            await session.commit()
            return f"created:{role}"
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
    if hasil.startswith("created"):
        peran = hasil.split(":", 1)[1] if ":" in hasil else "admin"
        print(f"Admin '{username}' dibuat dengan peran '{peran}'.")
    else:
        print(f"Admin '{username}' sudah ada — dilewati (idempoten).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
