"""WebSocket /ws: status kamera real-time (tanpa prefix /api, sesuai kontrak).

Auth via query param ?token= (JWT access). Browser tidak bisa mengirim header
Authorization saat handshake WebSocket, jadi token lewat query.
"""

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rbac import _user_from_token
from app.core.security import decode_token
from app.db.session import get_db
from app.routers.streams import _visible_streams

router = APIRouter()
log = logging.getLogger("netravision.ws")


class ConnectionManager:
    """Kelola koneksi /ws aktif.

    Tiap koneksi menyimpan himpunan kamera yang boleh dilihat pemiliknya;
    broadcast status disaring per koneksi agar klien hanya menerima
    perubahan kamera yang memang boleh ia lihat (A-T1).
    """

    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self.allowed: dict[WebSocket, set[int] | None] = {}

    async def connect(
        self, websocket: WebSocket, allowed_ids: set[int] | None = None
    ) -> None:
        await websocket.accept()
        self.active.append(websocket)
        self.allowed[websocket] = allowed_ids

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)
        self.allowed.pop(websocket, None)

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.active):
            try:
                msg = message
                # Saring perubahan status ke kamera yang boleh dilihat
                # koneksi ini; koneksi tanpa filter (None) menerima semua.
                if message.get("type") == "status" and isinstance(
                    message.get("changes"), list
                ):
                    allowed = self.allowed.get(ws)
                    if allowed is not None:
                        changes = [
                            c
                            for c in message["changes"]
                            if c.get("stream_id") in allowed
                        ]
                        if not changes:
                            continue
                        msg = {**message, "changes": changes}
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws")
async def ws_endpoint(
    websocket: WebSocket,
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    # A-T1: validasi penuh seperti endpoint HTTP. Token embed
    # (role "embed", sub "key:N") ditolak; user harus ada, aktif, dan
    # guest yang sudah dinonaktifkan ditolak (_user_from_token sudah
    # menangani ketiganya; token embed gagal di int("key:N") -> 401).
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = decode_token(token, settings)
        if payload.get("type") != "access" or payload.get("role") == "embed":
            raise ValueError("token bukan akses user")
        user = await _user_from_token(token, db)
    except Exception as e:
        # HTTPException dari _user_from_token ikut ditolak di sini.
        log.debug("ws auth ditolak: %s", e)
        await websocket.close(code=4401)
        return

    visible = await _visible_streams(user, db)
    allowed_ids = {s.id for s in visible}
    await manager.connect(websocket, allowed_ids)
    try:
        snapshot = [
            {"stream_id": s.id, "name": s.name, "is_online": s.is_online}
            for s in visible
        ]
        await websocket.send_json({"type": "snapshot", "streams": snapshot})
        while True:
            text = await websocket.receive_text()
            if text.strip().lower() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
