"""Router media (K-1): proxy WHEP/HLS ke MediaMTX di balik auth.

MASALAH (K-1): Apache mem-proxy /whep/ dan /hls/ LANGSUNG ke MediaMTX,
jadi siapa pun bisa membuka URL live stream (WHEP dan HLS) tanpa login.

PENUTUP: Apache dialihkan (lihat laporan K-1, perubahan Apache oleh
koordinator) supaya /whep/ dan /hls/ diteruskan ke router ini
(/api/media/whep/* dan /api/media/hls/*), BUKAN ke MediaMTX. Router ini
memvalidasi kredensial dulu, baru mem-proxy request ke MediaMTX
(127.0.0.1:8889/8888 di host, atau host mediamtx: di jaringan Docker):

- Pengguna login: token media (?token=, JWT singkat per-stream dari
  POST /api/media/token). Token terikat satu path (stream_{id} atau
  stream_{id}_sub); token kamera A tidak berlaku untuk kamera B.
  Akses kamera dicek ULANG di tiap request proxy (DB), jadi pencabutan
  grant langsung mematikan token yang sudah diterbitkan.
- Halaman embed publik: token sesi embed (?session=, sudah diterbitkan
  /external/stream dan sudah ditempel di URL WHEP embed). Validatornya
  memeriksa kunci masih aktif dan kamera masih terikat kunci itu.
- Tanpa kredensial, kredensial salah, atau kredensial untuk kamera lain:
  401. Kredensial sah tapi tanpa akses kamera: 403. Stream tidak ada
  atau nonaktif: 404.

HLS: hls.js mengambil segmen lewat URL relatif dari playlist, jadi
proxy menulis ulang playlist (.m3u8) dan menempel kredensial yang sama
ke tiap URI segmen/init (lihat app/services/media_auth.py).
WHEP: hanya sinyal POST (SDP) yang lewat proxy; media WebRTC (UDP
8189) tetap langsung browser ke MediaMTX, terikat sesi WHEP yang
sudah terautentikasi. PATCH/DELETE sesi WHEP ikut di-proxy supaya
klien WHEP yang memakainya tetap berfungsi.

CATATAN: Playback (rekaman) TIDAK lewat router ini dan tidak diubah:
rekaman tetap dilayani app/routers/recordings.py seperti semula.

Port MediaMTX TIDAK diekspos ke publik (compose hanya publish ke
127.0.0.1); satu-satunya jalan publik ke stream adalah proxy ini.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import rate_limited
from app.core.rbac import _check_camera_access, get_current_user
from app.db.session import get_db
from app.models.streams import Stream
from app.models.users import User
from app.routers.external import _validate_session_token
from app.services.media_auth import (
    MAX_PROXY_BODY_BYTES,
    MEDIA_TOKEN_TTL_SECONDS,
    create_media_token,
    credential_query,
    media_path_for,
    parse_media_path,
    rewrite_playlist,
    validate_media_token,
)

router = APIRouter(tags=["media"])
log = logging.getLogger("netravision.media")

# Batas isi respons upstream yang dibaca ke RAM (playlist kecil, segmen
# HLS 1 detik; 64 MiB jauh di atas ukuran wajar keduanya).
_MAX_UPSTREAM_BYTES = MAX_PROXY_BODY_BYTES


class MediaTokenRequest(BaseModel):
    stream_id: int = Field(gt=0)
    sub: bool = False


class MediaTokenResponse(BaseModel):
    token: str
    expires_at: str
    path: str
    whep_url: str
    hls_url: str


def _host_of(url: str) -> str:
    """Host dari satu URL (\"http://mediamtx:9997\" -> \"mediamtx\")."""
    return urlsplit(url).hostname or "127.0.0.1"


def _whep_base(settings: Settings) -> str:
    """Basis HTTP sinyal WHEP MediaMTX.

    Bila mediamtx_whep_base diubah eksplisit dari default, pakai itu.
    Bila tidak, turunkan host dari mediamtx_api_url (yang SUDAH diset
    benar di compose: http://mediamtx:9997) dengan port 8889. Ini
    penting di Docker: default 127.0.0.1:8889 tidak terjangkau dari
    container api, sedangkan host mediamtx terjangkau lewat jaringan
    Docker. Di jalan native, api_url default 127.0.0.1:9997 memberi
    127.0.0.1:8889 seperti semula.
    """
    default = Settings.model_fields["mediamtx_whep_base"].default
    if settings.mediamtx_whep_base and settings.mediamtx_whep_base != default:
        return settings.mediamtx_whep_base.rstrip("/")
    return f"http://{_host_of(settings.mediamtx_api_url)}:8889"


def _hls_base(settings: Settings) -> str:
    """Basis HTTP HLS MediaMTX (port 8888, host sama seperti api_url)."""
    return f"http://{_host_of(settings.mediamtx_api_url)}:8888"


class MediaUpstream:
    """Klien HTTP ke MediaMTX (WHEP :8889, HLS :8888).

    transport: opsional, untuk testing (httpx.MockTransport).
    follow_redirects: MediaMTX mengalihkan mis. /stream_1 ke
    /stream_1/index.m3u8; ikuti di sisi server supaya browser tidak
    pernah melihat redirect tanpa kredensial.
    """

    def __init__(
        self,
        whep_base: str,
        hls_base: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.whep_base = whep_base.rstrip("/")
        self.hls_base = hls_base.rstrip("/")
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            trust_env=False,
        )

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        return await self._client.request(method, url, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()


async def get_media_upstream() -> AsyncIterator[MediaUpstream]:
    """Dependency FastAPI: satu klien upstream per request, lalu tutup."""
    settings = get_settings()
    upstream = MediaUpstream(_whep_base(settings), _hls_base(settings))
    try:
        yield upstream
    finally:
        await upstream.aclose()


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


async def _authorize_media(
    request: Request,
    db: AsyncSession,
    path: str,
) -> str:
    """Validasi kredensial untuk satu path media.

    Return query kredensial (\"token=...\" atau \"session=...\") untuk
    penulisan ulang playlist HLS. Raise 401/403/404 sesuai kasus.
    Urutan: sintaks path -> kredensial -> stream ada/aktif -> akses.
    """
    try:
        stream_id, _ = parse_media_path(path)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="stream tidak ditemukan") from e

    token = request.query_params.get("token") or _bearer_token(request)
    session = request.query_params.get("session")
    if not token and not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="butuh token media atau sesi embed",
        )

    if token:
        try:
            payload = validate_media_token(token, get_settings())
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
            ) from e
        if payload.get("path") != path:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token media bukan untuk stream ini",
            )
        sub = payload.get("sub")
        try:
            user_id = int(str(sub))
        except (TypeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token media tidak valid",
            ) from e
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="pengguna tidak aktif",
            )
        stream = await db.get(Stream, stream_id)
        if stream is None or not stream.is_active:
            raise HTTPException(status_code=404, detail="stream tidak ditemukan")
        # Cek ulang akses kamera di tiap request: pencabutan grant
        # langsung mematikan token yang sudah diterbitkan.
        await _check_camera_access(stream_id, user, db)
        cred = credential_query(token, None)
    else:
        try:
            await _validate_session_token(db, session or "", stream_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
            ) from e
        stream = await db.get(Stream, stream_id)
        if stream is None or not stream.is_active:
            raise HTTPException(status_code=404, detail="stream tidak ditemukan")
        cred = credential_query(None, session)

    assert cred is not None
    return cred


def _public_media_urls(path: str, cred: str) -> tuple[str, str]:
    """URL publik (relatif, lewat Apache) untuk satu path + kredensial."""
    whep_url = f"/whep/{path}/whep?{cred}"
    hls_url = f"/hls/{path}/index.m3u8?{cred}"
    return whep_url, hls_url


@router.post(
    "/media/token",
    response_model=MediaTokenResponse,
    dependencies=[Depends(rate_limited(60, 60))],
)
async def issue_media_token(
    data: MediaTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MediaTokenResponse:
    """Terbitkan token media singkat untuk satu kamera (main atau sub).

    Pemanggil harus login dan punya akses lihat ke kamera itu
    (aturan yang sama seperti GET /streams). Token hanya berlaku
    untuk path yang diminta, 60 menit.
    """
    stream = await db.get(Stream, data.stream_id)
    if stream is None or not stream.is_active:
        raise HTTPException(status_code=404, detail="stream tidak ditemukan")
    if data.sub and not stream.sub_url:
        raise HTTPException(
            status_code=404, detail="kamera tidak punya sub stream"
        )
    await _check_camera_access(data.stream_id, user, db)
    path = media_path_for(data.stream_id, data.sub)
    settings = get_settings()
    token, expires_at = create_media_token(
        settings,
        subject=str(user.id),
        stream_id=data.stream_id,
        path=path,
        ttl_seconds=MEDIA_TOKEN_TTL_SECONDS,
    )
    cred = credential_query(token, None)
    assert cred is not None
    whep_url, hls_url = _public_media_urls(path, cred)
    return MediaTokenResponse(
        token=token,
        expires_at=expires_at.isoformat(),
        path=path,
        whep_url=whep_url,
        hls_url=hls_url,
    )


async def _proxy_upstream(
    request: Request,
    method: str,
    upstream_url: str,
    upstream: MediaUpstream,
) -> httpx.Response:
    """Teruskan satu request ke MediaMTX. Error jaringan -> 502."""
    headers: dict[str, str] = {}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type
    body = await request.body() if method in ("POST", "PATCH", "PUT") else None
    try:
        resp = await upstream.request(
            method, upstream_url, headers=headers, content=body
        )
    except httpx.HTTPError as e:
        log.warning("media proxy ke %s gagal: %s", upstream_url, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="MediaMTX tidak terjangkau",
        ) from e
    if len(resp.content) > _MAX_UPSTREAM_BYTES:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="respons MediaMTX terlalu besar",
        )
    return resp


def _passthrough_response(
    resp: httpx.Response,
    content: bytes,
    location_prefix: str | None = None,
) -> Response:
    """Bangun respons FastAPI dari respons upstream.

    Hanya Content-Type yang diteruskan (plus Location yang ditulis
    ulang ke prefix publik bila diminta); header lain upstream tidak
    perlu bocor ke browser.
    """
    headers: dict[str, str] = {}
    content_type = resp.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type
    location = resp.headers.get("location")
    if location and location_prefix:
        # MediaMTX mengembalikan Location relatif ke root-nya
        # (/stream_1/whep/<id>); kembalikan ke prefix publik
        # (/whep/stream_1/whep/<id>) supaya klien WHEP yang memakai
        # sesi (PATCH/DELETE) tetap lewat proxy ber-auth.
        loc_path = urlsplit(location).path.lstrip("/")
        headers["location"] = f"{location_prefix}/{loc_path}"
    return Response(
        content=content, status_code=resp.status_code, headers=headers
    )


@router.post("/media/whep/{path}/whep")
async def proxy_whep(
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    upstream: MediaUpstream = Depends(get_media_upstream),
) -> Response:
    """Proxy sinyal WHEP (POST SDP offer -> SDP answer)."""
    await _authorize_media(request, db, path)
    upstream_url = f"{upstream.whep_base}/{path}/whep"
    resp = await _proxy_upstream(request, "POST", upstream_url, upstream)
    return _passthrough_response(resp, resp.content, location_prefix="/whep")


@router.api_route(
    "/media/whep/{path}/whep/{session_path:path}",
    methods=["PATCH", "DELETE"],
)
async def proxy_whep_session(
    path: str,
    session_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    upstream: MediaUpstream = Depends(get_media_upstream),
) -> Response:
    """Proxy manajemen sesi WHEP (PATCH ICE / DELETE tutup sesi)."""
    await _authorize_media(request, db, path)
    upstream_url = f"{upstream.whep_base}/{path}/whep/{session_path}"
    resp = await _proxy_upstream(
        request, request.method, upstream_url, upstream
    )
    return _passthrough_response(resp, resp.content, location_prefix="/whep")


@router.get("/media/hls/{rest:path}")
async def proxy_hls(
    rest: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    upstream: MediaUpstream = Depends(get_media_upstream),
) -> Response:
    """Proxy HLS: playlist (.m3u8) ditulis ulang, segmen diteruskan.

    Segmen pertama path HARUS nama path media yang sah (stream_{id}
    atau stream_{id}_sub); sisanya nama berkas MediaMTX (index.m3u8,
    seg-*.m4s, init.mp4, ...). Token dicek terhadap path itu.
    """
    first = (rest or "").split("/", 1)[0]
    try:
        parse_media_path(first)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="stream tidak ditemukan") from e
    if "/" not in rest:
        raise HTTPException(status_code=404, detail="stream tidak ditemukan")
    cred = await _authorize_media(request, db, first)
    upstream_url = f"{upstream.hls_base}/{rest}"
    resp = await _proxy_upstream(request, "GET", upstream_url, upstream)
    content_type = resp.headers.get("content-type", "")
    is_playlist = rest.endswith(".m3u8") or "mpegurl" in content_type
    if is_playlist:
        text = resp.content.decode("utf-8", errors="replace")
        rewritten = rewrite_playlist(text, cred)
        return _passthrough_response(resp, rewritten.encode("utf-8"))
    return _passthrough_response(resp, resp.content)
