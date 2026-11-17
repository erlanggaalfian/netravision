"""WebSocket /ws: status kamera real-time (tanpa prefix /api, sesuai kontrak).

Auth via query param ?token= (JWT access). Browser tidak bisa mengirim header
Authorization saat handshake WebSocket, jadi token lewat query.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rbac import _user_from_token
from app.core.security import decode_token
from app.db.session import get_db, get_session_factory
from app.routers.streams import _visible_streams

router = APIRouter()
log = logging.getLogger("netravision.ws")

# 4.10: token sebelumnya hanya dicek sekali saat handshake, lalu koneksi
# hidup selamanya (user dinonaktifkan / grant dicabut tetap menerima
# broadcast). Kini sesi divalidasi ulang berkala dan koneksi idle
# ditutup. Konstanta modul (bukan settings) supaya test bisa
# monkeypatch tanpa mengubah .env.
WS_REVALIDATE_SECONDS = 300.0  # cek ulang user aktif + hak kamera
WS_IDLE_SECONDS = 120.0  # tanpa pesan apa pun selama ini -> tutup

# A-1.23: batas siaran per koneksi (klien lambat tidak boleh menahan
# siaran status ke semua klien lain), ukuran pesan masuk, dan laju ping.
_BROADCAST_TIMEOUT = 5.0  # detik per koneksi
_MAX_MESSAGE_BYTES = 16 * 1024  # 16 KiB; pesan ws hanya ping/JSON kecil
_MAX_PINGS_PER_WINDOW = 20  # ping per jendela 10 detik (banjir diabaikan)
_PING_WINDOW_SEC = 10.0


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
        # A-1.23: kirim ke semua koneksi bersamaan dengan timeout per
        # koneksi; sebelumnya berurutan tanpa timeout, jadi satu klien
        # lambat menahan siaran status ke semua klien lain.
        async def _send(ws: WebSocket, msg: dict) -> WebSocket | None:
            try:
                await asyncio.wait_for(
                    ws.send_json(msg), timeout=_BROADCAST_TIMEOUT
                )
                return None
            except Exception:
                return ws

        jobs = []
        for ws in list(self.active):
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
            jobs.append(_send(ws, msg))
        dead = [ws for ws in await asyncio.gather(*jobs) if ws is not None]
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
    # Penolakan dilakukan dengan accept() dulu lalu close(4401): bila
    # close tanpa accept, uvicorn menjawab handshake dengan HTTP 403
    # dan browser mencatat "WebSocket is closed before the connection
    # is established" berulang-ulang tiap token kedaluwarsa. Dengan
    # accept + close, klien mendapat close event bersih berkode 4401
    # (tanpa error console) dan bisa refresh token lalu sambung ulang.
    async def _reject_unauthorized() -> None:
        try:
            await websocket.accept()
        except Exception:
            return
        try:
            await websocket.close(code=4401)
        except Exception:
            pass

    if not token:
        await _reject_unauthorized()
        return
    try:
        payload = decode_token(token, settings)
        if payload.get("type") != "access" or payload.get("role") == "embed":
            raise ValueError("token bukan akses user")
        user = await _user_from_token(token, db)
    except Exception as e:
        # HTTPException dari _user_from_token ikut ditolak di sini.
        log.debug("ws auth ditolak: %s", e)
        await _reject_unauthorized()
        return

    visible = await _visible_streams(user, db)
    allowed_ids = {s.id for s in visible}
    await manager.connect(websocket, allowed_ids)
    ping_times: list[float] = []

    async def _revalidate() -> bool:
        """Cek ulang token + user aktif + hak kamera (4.10).

        Sesi DB endpoint sudah lama hidup, jadi buka sesi baru.
        Bila masih sah, perbarui allowed_ids dan kirim snapshot baru
        bila hak berubah. False = tutup koneksi (4401, frontend lalu
        refresh token dan sambung ulang).
        """
        nonlocal allowed_ids
        try:
            async with get_session_factory()() as fresh_db:
                fresh_user = await _user_from_token(token, fresh_db)
                fresh_visible = await _visible_streams(fresh_user, fresh_db)
        except Exception as e:
            log.debug("ws revalidasi gagal: %s", e)
            return False
        new_ids = {s.id for s in fresh_visible}
        if new_ids != allowed_ids:
            allowed_ids = new_ids
            manager.allowed[websocket] = new_ids
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "streams": [
                        {
                            "stream_id": s.id,
                            "name": s.name,
                            "is_online": s.is_online,
                        }
                        for s in fresh_visible
                    ],
                }
            )
        return True

    try:
        snapshot = [
            {"stream_id": s.id, "name": s.name, "is_online": s.is_online}
            for s in visible
        ]
        await websocket.send_json({"type": "snapshot", "streams": snapshot})
        # 4.10: receive dibatasi timeout supaya revalidasi berkala dan
        # idle timeout bisa jalan (sebelumnya receive_text() menggantung
        # selamanya). Frontend mengirim ping tiap 25 detik, jauh di
        # bawah WS_IDLE_SECONDS.
        last_msg = time.monotonic()
        last_check = last_msg
        token_exp = payload.get("exp")
        while True:
            now = time.monotonic()
            idle_left = WS_IDLE_SECONDS - (now - last_msg)
            if idle_left <= 0:
                log.debug("ws idle timeout, tutup koneksi")
                try:
                    await websocket.close(code=1000)
                except Exception:
                    pass
                break
            next_check_in = WS_REVALIDATE_SECONDS - (now - last_check)
            if isinstance(token_exp, (int, float)):
                next_check_in = min(
                    next_check_in, max(0.0, token_exp - time.time())
                )
            if next_check_in <= 0:
                last_check = time.monotonic()
                if not await _revalidate():
                    try:
                        await websocket.close(code=4401)
                    except Exception:
                        pass
                    break
                continue
            try:
                text = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=min(idle_left, next_check_in),
                )
            except asyncio.TimeoutError:
                continue
            last_msg = time.monotonic()
            # A-1.23: pesan masuk dibatasi ukuran (sebelumnya tanpa
            # batas) dan ping dibatasi lajunya (sebelumnya tanpa rate
            # limit); pesan raksasa menutup koneksi (1009), ping yang
            # terlalu rapat diabaikan diam-diam.
            if len(text.encode("utf-8", "ignore")) > _MAX_MESSAGE_BYTES:
                await websocket.close(code=1009)
                break
            # Keepalive: terima ping polos ("ping") maupun JSON dari hook
            # browser ({"type":"ping"}). Sebelumnya hanya "ping" polos
            # yang dibalas, jadi pong tidak pernah kembali ke browser.
            is_ping = text.strip().lower() == "ping"
            if not is_ping:
                try:
                    data = json.loads(text)
                    is_ping = isinstance(data, dict) and data.get("type") == "ping"
                except Exception:
                    is_ping = False
            if is_ping:
                now = time.monotonic()
                ping_times = [t for t in ping_times if t > now - _PING_WINDOW_SEC]
                if len(ping_times) < _MAX_PINGS_PER_WINDOW:
                    ping_times.append(now)
                    await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        # Putus tak terduga (mis. error jaringan di tengah receive):
        # bersihkan koneksi seperti disconnect, jangan biarkan
        # exception merambat sebagai 500 dan koneksi menggantung.
        log.debug("ws putus tak terduga: %s", e)
        manager.disconnect(websocket)
    # Keluar loop normal (mis. pesan terlalu besar -> close 1009):
    # koneksi tetap harus dilepas dari manager.
    manager.disconnect(websocket)
