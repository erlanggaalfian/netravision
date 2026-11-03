"""Test hardening Fase 4: rate limit, security headers, audit log, metrik."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.rate_limit import reset_rate_limits
from app.models.misc import AuditLog
from tests.conftest import auth_as, make_user


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _audit_factory_for(db_session):
    """Factory session audit yang menunjuk ke DB sqlite milik test ini."""
    engine = db_session.bind
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_login_rate_limited(app_client):
    app, _, _ = app_client
    async with _client(app) as c:
        statuses = []
        for _ in range(7):
            r = await c.post(
                "/api/auth/login",
                json={"username": "nope", "password": "salah"},
            )
            statuses.append(r.status_code)
        # 5x boleh lewat (401 kredensial salah), ke-6+ harus 429.
        assert statuses[:5] == [401] * 5, statuses
        assert 429 in statuses[5:], statuses
        r429 = await c.post(
            "/api/auth/login", json={"username": "nope", "password": "salah"}
        )
        assert r429.status_code == 429
        assert "retry-after" in {k.lower() for k in r429.headers}


async def test_security_headers(app_client):
    app, _, _ = app_client
    async with _client(app) as c:
        r = await c.get("/api/health")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert (
            r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        )
        assert "camera=()" in r.headers.get("permissions-policy", "")
        # X-Frame-Options SENGAJA tidak ada (embed mitra harus bisa di-iframe).
        assert "x-frame-options" not in {k.lower() for k in r.headers}


async def test_admin_mutation_writes_audit_log(app_client):
    app, _, db = app_client
    # Arahkan middleware audit ke DB test (bukan postgres produksi).
    app.state.audit_session_factory = _audit_factory_for(db)
    admin = make_user()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/users",
            json={"username": "auditme", "password": "rahasia123", "role": "user"},
        )
        assert r.status_code == 201, r.text

    rows = (
        (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "POST /api/admin/users")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) >= 1
    row = rows[0]
    assert row.resource == "/api/admin/users"
    assert row.detail["status_code"] == 201
    # auth_as mem-bypass JWT asli -> tercatat sebagai anonymous, tanpa gagal.
    assert row.detail["actor"] == "anonymous"
    assert row.actor_id is None

    # GET tidak dicatat.
    n_before = len(rows)
    async with _client(app) as c:
        await c.get("/api/admin/users")
    rows2 = (await db.execute(select(AuditLog))).scalars().all()
    assert len(rows2) == n_before


async def test_metrics_admin_only(app_client):
    app, _, _ = app_client
    admin = make_user()
    user = make_user(id=2, username="op", role="user")
    async with _client(app) as c:
        await c.get("/api/health")
        auth_as(app, user)
        r = await c.get("/api/metrics")
        assert r.status_code == 403
        auth_as(app, admin)
        r = await c.get("/api/metrics")
        assert r.status_code == 200
        body = r.text
        # Format eksposisi Prometheus.
        assert "nv_http_requests_total" in body
        assert "nv_http_latency_seconds" in body
        assert 'path_template="/api/health"' in body


async def test_scan_rate_limited(app_client):
    """Scan dibatasi 10/menit — request ke-11 harus 429."""
    app, _, db = app_client
    admin = make_user()
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        statuses = []
        for _ in range(11):
            r = await c.post(
                "/api/admin/scan",
                json={"brand": "auto", "host": "192.168.1.10",
                      "user": "admin", "password": "x", "probe": False},
            )
            statuses.append(r.status_code)
        assert statuses[:10] == [200] * 10, statuses
        assert statuses[10] == 429, statuses
        assert "retry-after" in {k.lower() for k in r.headers}


async def test_audit_logs_failed_mutation(app_client):
    """Mutasi admin yang gagal tetap tercatat beserta status code-nya."""
    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    admin = make_user()
    db.add(admin)
    await db.commit()
    auth_as(app, admin)
    async with _client(app) as c:
        r = await c.post("/api/admin/streams/999/sharing", json={"user_ids": []})
        assert r.status_code == 404

    rows = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == "POST /api/admin/streams/999/sharing")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].detail["status_code"] == 404


async def test_audit_logs_real_actor(app_client):
    """Dengan JWT asli (tanpa override), actor tercatat sebagai username."""
    from app.core.config import get_settings
    from app.core.security import create_access_token

    app, _, db = app_client
    app.state.audit_session_factory = _audit_factory_for(db)
    admin = make_user()
    db.add(admin)
    await db.commit()
    tok = create_access_token(admin.id, admin.username, admin.role, get_settings())
    # Tanpa auth_as — auth route memakai JWT asli end-to-end.
    async with _client(app) as c:
        r = await c.post(
            "/api/admin/users",
            json={"username": "auditreal", "password": "rahasia123", "role": "user"},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 201, r.text

    rows = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "POST /api/admin/users")
        )
    ).scalars().all()
    assert len(rows) >= 1
    row = rows[-1]
    assert row.detail["actor"] == "admin"
    assert row.actor_id == admin.id
    assert row.detail["status_code"] == 201
