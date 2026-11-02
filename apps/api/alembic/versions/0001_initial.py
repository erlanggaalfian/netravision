"""Migrasi awal: 12 tabel NetraVision v3.0.

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("refresh_token_hash", sa.String(64), nullable=True),
        _ts(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("rtsp_url", sa.String(512), nullable=False),
        sa.Column("brand", sa.String(64), nullable=True),
        sa.Column("main_url", sa.String(512), nullable=True),
        sa.Column("sub_url", sa.String(512), nullable=True),
        sa.Column("onvif_profile", sa.String(128), nullable=True),
        sa.Column("group_name", sa.String(128), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recording_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("storage_mode", sa.String(16), nullable=False, server_default="local"),
        _ts(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_streams"),
    )
    op.create_index("ix_streams_group_name", "streams", ["group_name"])

    op.create_table(
        "user_stream_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("can_view", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_control", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_user_stream_access_user_id_users"),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="CASCADE",
                                name="fk_user_stream_access_stream_id_streams"),
        sa.PrimaryKeyConstraint("id", name="pk_user_stream_access"),
        sa.UniqueConstraint("user_id", "stream_id", name="uq_user_stream_access_user_id"),
    )

    op.create_table(
        "stream_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("can_view", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_download", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="CASCADE",
                                name="fk_stream_permissions_stream_id_streams"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_stream_permissions_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_stream_permissions"),
    )

    op.create_table(
        "stream_admin_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("can_manage", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="CASCADE",
                                name="fk_stream_admin_grants_stream_id_streams"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_stream_admin_grants_admin_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_stream_admin_grants"),
        sa.UniqueConstraint("stream_id", "admin_id", name="uq_stream_admin_grants_stream_id"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("domain_lock", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        _ts(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )

    op.create_table(
        "api_key_streams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE",
                                name="fk_api_key_streams_api_key_id_api_keys"),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="CASCADE",
                                name="fk_api_key_streams_stream_id_streams"),
        sa.PrimaryKeyConstraint("id", name="pk_api_key_streams"),
        sa.UniqueConstraint("api_key_id", "stream_id", name="uq_api_key_streams_api_key_id"),
    )

    op.create_table(
        "api_access_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=True),
        sa.Column("stream_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="SET NULL",
                                name="fk_api_access_logs_api_key_id_api_keys"),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="SET NULL",
                                name="fk_api_access_logs_stream_id_streams"),
        sa.PrimaryKeyConstraint("id", name="pk_api_access_logs"),
    )
    op.create_index("ix_api_access_logs_created_at", "api_access_logs", ["created_at"])

    op.create_table(
        "ad_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ad_config"),
        sa.UniqueConstraint("key", name="uq_ad_config_key"),
    )

    op.create_table(
        "detection_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("snapshot_path", sa.String(512), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="CASCADE",
                                name="fk_detection_events_stream_id_streams"),
        sa.PrimaryKeyConstraint("id", name="pk_detection_events"),
    )
    op.create_index("ix_detection_events_detected_at", "detection_events", ["detected_at"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("stream_id", sa.Integer(), nullable=True),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(512), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_alerts_user_id_users"),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="SET NULL",
                                name="fk_alerts_stream_id_streams"),
        sa.ForeignKeyConstraint(["event_id"], ["detection_events.id"], ondelete="SET NULL",
                                name="fk_alerts_event_id_detection_events"),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_audit_logs_actor_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    for table in (
        "audit_logs",
        "alerts",
        "detection_events",
        "ad_config",
        "api_access_logs",
        "api_key_streams",
        "api_keys",
        "stream_admin_grants",
        "stream_permissions",
        "user_stream_access",
        "streams",
        "users",
    ):
        op.drop_table(table)
