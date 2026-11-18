"""Klien control API MediaMTX (v3).

Dipakai untuk mendaftarkan path stream_{id} / stream_{id}_sub,
mengecek status path, dan menghapus path yang tidak dipakai lagi.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings

log = logging.getLogger("netravision.mediamtx")

# P0: SATU lock proses untuk semua mutasi path MediaMTX. Sync loop
# (main.py), admin, dan reconnect memakai instance client berbeda, jadi
# lock per-instance tidak cukup, lock ini di level modul agar
# ensure/create/patch/delete dari mana pun ter-serialisasi.
MEDIA_PATH_LOCK = asyncio.Lock()


def mediamtx_path_lock() -> asyncio.Lock:
    """Kembalikan lock mutasi path MediaMTX (ekspor untuk main.py).

    Pakai sebagai `async with mediamtx_path_lock():` untuk mengelompokkan
    beberapa mutasi menjadi satu bagian kritis. Jangan ambil lock ini lalu
    memanggil ensure/create/patch/delete: mereka sudah mengambilnya
    sendiri dan asyncio.Lock tidak reentrant (deadlock).
    """
    return MEDIA_PATH_LOCK


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
        # Retry 1x HANYA untuk GET (idempotent) pada error koneksi/timeout,
        # dengan backoff 0,3 detik. POST/PATCH/DELETE TIDAK di-retry:
        # pengulangan add bisa menduplikasi efek di sisi server, dan
        # 4xx (mis. 409 path sudah ada) tidak pernah di-retry.
        # Timeout tetap 5 detik (di AsyncClient); tidak diubah.
        attempts = 2 if method.upper() == "GET" else 1
        for attempt in range(attempts):
            try:
                resp = await self._client.request(method, path, **kwargs)
                if resp.status_code == 404:
                    return resp
                resp.raise_for_status()
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.3)
                    continue
                # Semua error HTTP/timeout/connection -> RuntimeError agar
                # pemanggil cukup tangkap satu tipe (kontrak: gagal =
                # RuntimeError).
                raise RuntimeError(
                    f"MediaMTX tidak terjangkau di {self._client.base_url}: {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"MediaMTX tidak terjangkau di {self._client.base_url}: {exc}"
                ) from exc

    async def get_paths(self) -> list[dict]:
        """Daftar semua path yang terdaftar di MediaMTX.

        Temuan 3.20: bentuk respons divalidasi. Bila API mengembalikan
        dict tanpa `items` (atau `items` bukan list), kembalikan []
        dan catat error, jangan kembalikan dict mentah: pemanggil yang
        mengiterasi dict akan mendapat string kunci dan mengira tidak
        ada path, sehingga pembersihan path yatim mati diam-diam.
        """
        resp = await self._request("GET", "/v3/config/paths/list")
        data = resp.json()
        if isinstance(data, list):
            return [p for p in data if isinstance(p, dict)]
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return [p for p in items if isinstance(p, dict)]
            # P0: JANGAN log isi data mentah, field `source` bisa berisi
            # URL RTSP berkredensial. Hanya bentuknya: nama-nama key
            # (tanpa nilai) dan jumlahnya.
            log.warning(
                "MediaMTX get_paths: respons dict tanpa items list: "
                "keys=%s (n=%d)",
                sorted(data.keys()),
                len(data),
            )
            return []
        log.warning(
            "MediaMTX get_paths: respons bukan list/dict: type=%s",
            type(data).__name__,
        )
        return []

    async def get_path(self, name: str) -> dict | None:
        """Detail satu path, atau None bila tidak terdaftar."""
        resp = await self._request("GET", f"/v3/config/paths/get/{name}")
        if resp.status_code == 404:
            return None
        return resp.json()

    async def create_path(self, name: str, source: str,
                          record: bool = False) -> None:
        """Daftarkan path dengan source RTSP (idempoten bila sudah ada).

        Seluruh mutasi lewat MEDIA_PATH_LOCK (lihat atas file).
        """
        async with MEDIA_PATH_LOCK:
            if await self.get_path(name):
                return
            body: dict = {"source": source}
            if record:
                body["record"] = True
            await self._request(
                "POST", f"/v3/config/paths/add/{name}", json=body
            )

    async def patch_path(self, name: str, patch: dict) -> None:
        """Ubah konfigurasi path yang sudah ada (mis. record on/off).

        Seluruh mutasi lewat MEDIA_PATH_LOCK (lihat atas file).
        """
        async with MEDIA_PATH_LOCK:
            await self._request(
                "PATCH", f"/v3/config/paths/patch/{name}", json=patch
            )

    async def ensure_path(self, name: str, conf: dict) -> None:
        """Pastikan path ada dengan konfigurasi `conf`.

        H2: Belum ada -> add. Sudah ada tapi beda -> patch HANYA key yang
        berbeda (bukan seluruh conf), dan lewati sama sekali bila semua key
        sudah sama, agar sync berkala tiap 60 detik tidak me-reload path
        yang sedang ditonton. Perbandingan dinormalisasi (bool vs string)
        karena API MediaMTX kadang mengembalikan bentuk yang berbeda.

        Seluruh check-then-act berjalan di bawah MEDIA_PATH_LOCK (lihat
        atas file) supaya dua pemanggil bersamaan tidak balapan add.
        patch_path TIDAK dipanggil dari sini, ia mengambil lock yang
        sama dan asyncio.Lock tidak reentrant, PATCH dilakukan langsung
        lewat _request di bawah lock yang sama.
        """
        async with MEDIA_PATH_LOCK:
            cur = await self.get_path(name)
            if cur is None:
                try:
                    await self._request("POST", f"/v3/config/paths/add/{name}", json=conf)
                except RuntimeError:
                    # Temuan 3.20: check-then-act bisa balapan. Dua pemanggil
                    # bersamaan sama-sama melihat path belum ada, lalu yang
                    # kedua gagal add (409/sudah ada). Baca ulang: bila path
                    # kini ada, lanjut ke patch-diff di bawah; bila tetap
                    # tidak ada, errornya nyata dan dilempar ulang.
                    cur = await self.get_path(name)
                    if cur is None:
                        raise
                else:
                    return
            diff = {
                k: v for k, v in conf.items() if not _conf_value_equal(cur.get(k), v)
            }
            if diff:
                await self._request(
                    "PATCH", f"/v3/config/paths/patch/{name}", json=diff
                )

    async def path_ready(self, name: str) -> bool:
        """Status runtime: sumber path sedang tersambung & mengirim media."""
        resp = await self._request("GET", f"/v3/paths/get/{name}")
        if resp.status_code == 404:
            return False
        return bool(resp.json().get("ready"))

    async def delete_path(self, name: str) -> None:
        """Hapus path bila terdaftar.

        Seluruh mutasi lewat MEDIA_PATH_LOCK (lihat atas file).
        """
        async with MEDIA_PATH_LOCK:
            resp = await self._request("DELETE", f"/v3/config/paths/delete/{name}")
            if resp.status_code not in (200, 404):
                resp.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()


def _conf_value_equal(cur_val, want_val) -> bool:
    """Samakah nilai config MediaMTX yang ada dengan yang diinginkan?"""
    if cur_val == want_val:
        return True
    if isinstance(want_val, bool) and isinstance(cur_val, str):
        low = cur_val.strip().lower()
        return low in ("true", "yes", "1") if want_val else low in ("false", "no", "0")
    if isinstance(want_val, str) and isinstance(cur_val, bool):
        return _conf_value_equal(want_val, cur_val)
    if cur_val is None or want_val is None:
        return False
    return str(cur_val).strip() == str(want_val).strip()


def get_mediamtx() -> MediaMTXClient:
    """Factory dari settings (field: mediamtx_api_url).

    Dipakai pemakaian langsung (main.py, tes). Router WAJIB memakai
    `get_mediamtx_dep` (dependency yield) supaya client ditutup.

    4.11: kredensial control API (mediamtx_api_user/password) dikirim
    bila dikonfigurasi; kosong = tanpa auth (perilaku lama).
    Password diambil dari database (system_settings, di-cache saat
    startup lifespan); env MEDIAMTX_API_PASSWORD hanya fallback bila
    cache kosong (mis. sebelum startup selesai / di tes).
    """
    from app.services.system_settings import get_mediamtx_password  # noqa: PLC0415

    settings = get_settings()
    password = get_mediamtx_password() or settings.mediamtx_api_password or None
    return MediaMTXClient(
        base_url=settings.mediamtx_api_url,
        username=settings.mediamtx_api_user or None,
        password=password,
    )


async def get_mediamtx_dep() -> AsyncIterator[MediaMTXClient]:
    """Dependency FastAPI untuk router (temuan 3.8).

    `get_mediamtx()` membuat `httpx.AsyncClient` baru tiap panggilan;
    sebagai dependency biasa (tanpa yield) tidak ada yang memanggil
    `aclose()`, jadi tiap request admin/stream membocorkan satu client
    beserta connection pool-nya. Versi yield ini menutup client di
    `finally`, apa pun hasil endpoint-nya.
    """
    client = get_mediamtx()
    try:
        yield client
    finally:
        await client.aclose()
