"""Registrasi semua model agar Alembic melihat metadata lengkap."""

from app.models import access, groups, keys, misc, streams, users  # noqa: F401
from app.models.access import StreamAdminGrant, StreamPermission, UserStreamAccess
from app.models.groups import GroupStream, StreamGroup
from app.models.keys import ApiAccessLog, ApiKey, ApiKeyStream
from app.models.misc import AdConfig, Alert, AuditLog, DetectionEvent
from app.models.streams import Stream
from app.models.users import User

__all__ = [
    "User",
    "Stream",
    "UserStreamAccess",
    "StreamPermission",
    "StreamAdminGrant",
    "ApiKey",
    "ApiKeyStream",
    "ApiAccessLog",
    "AdConfig",
    "DetectionEvent",
    "Alert",
    "AuditLog",
    "StreamGroup",
    "GroupStream",
]
