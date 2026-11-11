"""Test WebSocket /ws: auth token, snapshot, ping/pong."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.streams import Stream
from tests.conftest import auth_as, make_user


async def _seed(db):
    # A-T1: snapshot WS hanya berisi kamera yang terlihat untuk user.
    # Pakai super_admin agar Cam 1 masuk snapshot.
    db.add(make_user(role="super_admin"))
    db.add(Stream(id=1, name="Cam 1", rtsp_url="rtsp://cam/1",
                  main_url="rtsp://cam/1", is_active=True, is_online=True))
    await db.commit()


def _token():
    return create_access_token(1, "admin", "super_admin", get_settings())


async def test_ws_snapshot_and_ping(app_client):
    app, _, db = app_client
    await _seed(db)
    auth_as(app, make_user())  # tidak dipakai /ws, tapi aman bila ada guard
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={_token()}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["streams"] == [
                {"stream_id": 1, "name": "Cam 1", "is_online": True}
            ]
            ws.send_text("ping")
            assert ws.receive_json() == {"type": "pong"}


async def test_ws_rejects_no_token(app_client):
    app, _, db = app_client
    await _seed(db)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws"):
                pass
        assert exc.value.code == 4401


async def test_ws_rejects_bad_token(app_client):
    app, _, db = app_client
    await _seed(db)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws?token=salah"):
                pass
        assert exc.value.code == 4401
