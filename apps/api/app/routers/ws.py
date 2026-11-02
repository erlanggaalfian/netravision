"""WebSocket /ws: status kamera real-time (tanpa prefix /api, sesuai kontrak).

Auth via query param ?token= (JWT access). Browser tidak bisa mengirim header
Authorization saat handshake WebSocket, jadi token lewat query.
"""

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.streams import Stream

router = APIRouter()
log = logging.getLogger("netravision.ws")


class ConnectionManager:
    """Kelola koneksi /ws aktif."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_json(message)
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
    authed = False
    if token:
        try:
            payload = decode_token(token, settings)
            authed = payload.get("type") == "access"
        except ValueError:
            authed = False
    if not authed:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    try:
        result = await db.execute(
            select(Stream).where(Stream.is_active.is_(True)).order_by(Stream.id)
        )
        snapshot = [
            {"stream_id": s.id, "name": s.name, "is_online": s.is_online}
            for s in result.scalars().all()
        ]
        await websocket.send_json({"type": "snapshot", "streams": snapshot})
        while True:
            text = await websocket.receive_text()
            if text.strip().lower() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
