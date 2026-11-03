"""Klien control API MediaMTX (v3).

Dipakai untuk mendaftarkan path stream_{id} / stream_{id}_sub,
mengecek status path, dan menghapus path yang tidak dipakai lagi.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings


class MediaMTXClient:
    """Wrapper async di atas MediaMTX control API.

    Args:
        base_url: mis. "http://127.0.0.1:9997"
        username/password: opsional, bila control API diproteksi.
        transport: opsional, untuk testing (httpx.MockTransport).
    """

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        auth = (username, password) if username and password else None
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            auth=auth,
            transport=transport,
            timeout=httpx.Timeout(5.0),
            # Jangan ikut proxy ambient (HTTP_PROXY dsb.): ini client
            # server-ke-server di jaringan lokal.
            trust_env=False,
        )

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            resp = await self._client.request(method, path, **kwargs)
            if resp.status_code == 404:
                return resp
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            # Semua error HTTP/timeout/connection -> RuntimeError agar pemanggil
            # cukup tangkap satu tipe (kontrak: gagal = RuntimeError).
            raise RuntimeError(
                f"MediaMTX tidak terjangkau di {self._client.base_url}: {exc}"
            ) from exc

    async def get_paths(self) -> list[dict]:
        """Daftar semua path yang terdaftar di MediaMTX."""
        resp = await self._request("GET", "/v3/config/paths/list")
        data = resp.json()
        return data.get("items", data) if isinstance(data, dict) else data

    async def get_path(self, name: str) -> dict | None:
        """Detail satu path, atau None bila tidak terdaftar."""
        resp = await self._request("GET", f"/v3/config/paths/get/{name}")
        if resp.status_code == 404:
            return None
        return resp.json()

    async def create_path(self, name: str, source: str,
                          record: bool = False) -> None:
        """Daftarkan path dengan source RTSP (idempoten bila sudah ada)."""
        if await self.get_path(name):
            return
        body: dict = {"source": source}
        if record:
            body["record"] = True
        await self._request(
            "POST", f"/v3/config/paths/add/{name}", json=body
        )

    async def patch_path(self, name: str, patch: dict) -> None:
        """Ubah konfigurasi path yang sudah ada (mis. record on/off)."""
        await self._request(
            "PATCH", f"/v3/config/paths/patch/{name}", json=patch
        )

    async def ensure_path(self, name: str, conf: dict) -> None:
        """Pastikan path ada dengan konfigurasi `conf`.

        Belum ada -> add. Sudah ada tapi beda -> patch (hanya bila beda, agar
        sync berkala tidak me-reload path yang sedang ditonton)."""
        cur = await self.get_path(name)
        if cur is None:
            await self._request("POST", f"/v3/config/paths/add/{name}", json=conf)
        elif any(cur.get(k) != v for k, v in conf.items()):
            await self.patch_path(name, conf)

    async def path_ready(self, name: str) -> bool:
        """Status runtime: sumber path sedang tersambung & mengirim media."""
        resp = await self._request("GET", f"/v3/paths/get/{name}")
        if resp.status_code == 404:
            return False
        return bool(resp.json().get("ready"))

    async def delete_path(self, name: str) -> None:
        """Hapus path bila terdaftar."""
        resp = await self._request("DELETE", f"/v3/config/paths/delete/{name}")
        if resp.status_code not in (200, 404):
            resp.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()


def get_mediamtx() -> MediaMTXClient:
    """Factory dari settings (field: mediamtx_api_url).

    TODO Fase 1+: tambah mediamtx_api_user/mediamtx_api_password di config
    bila control API diproteksi di produksi.
    """
    settings = get_settings()
    return MediaMTXClient(base_url=settings.mediamtx_api_url)
