"""Test MediaMTXClient dengan httpx MockTransport (tanpa network)."""

import httpx
import pytest

from app.services.mediamtx import MediaMTXClient, get_mediamtx


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.method == "GET" and path == "/v3/config/paths/list":
        return httpx.Response(200, json={"items": [{"name": "stream_1", "ready": True}]})
    if request.method == "GET" and path == "/v3/config/paths/get/stream_1":
        return httpx.Response(200, json={"name": "stream_1", "ready": True})
    if request.method == "GET" and path.startswith("/v3/config/paths/get/"):
        return httpx.Response(404, json={"status": "error"})
    if request.method == "POST" and path.startswith("/v3/config/paths/add/"):
        return httpx.Response(200, json={})
    if request.method == "DELETE" and path.startswith("/v3/config/paths/delete/"):
        return httpx.Response(200, json={})
    return httpx.Response(500, json={"status": "error"})


@pytest.fixture
def client():
    c = MediaMTXClient(
        "http://127.0.0.1:9997", transport=httpx.MockTransport(_handler)
    )
    yield c


async def test_get_paths(client):
    paths = await client.get_paths()
    assert paths == [{"name": "stream_1", "ready": True}]


async def test_get_path_ada_dan_tidak(client):
    assert (await client.get_path("stream_1"))["ready"] is True
    assert await client.get_path("stream_9") is None


async def test_create_path_idempoten(client):
    # stream_1 sudah ada -> tidak POST ulang (tidak error)
    await client.create_path("stream_1", "rtsp://x")
    # stream_2 belum ada -> POST add
    await client.create_path("stream_2", "rtsp://x")


async def test_delete_path(client):
    await client.delete_path("stream_1")
    await client.delete_path("stream_tidak_ada")


async def test_unreachable_raises_runtime_error():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    c = MediaMTXClient("http://127.0.0.1:9997", transport=httpx.MockTransport(boom))
    with pytest.raises(RuntimeError, match="tidak terjangkau"):
        await c.get_paths()


def test_get_mediamtx_dari_settings():
    c = get_mediamtx()
    assert isinstance(c, MediaMTXClient)
    assert str(c._client.base_url) == "http://127.0.0.1:9997"
