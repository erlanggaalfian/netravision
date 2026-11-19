"""Auth: login, refresh (rotation), logout, guest.

Path dipertahankan persis seperti v2.0: POST /api/auth/login|refresh|logout|guest.

T-2: login/refresh/guest menerbitkan token sebagai cookie HttpOnly
(nv_access, nv_refresh); refresh juga membaca cookie itu, dengan body
JSON sebagai fallback klien API. Logout menghapus kedua cookie.
"""

import hmac
import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import client_ip, rate_limited
from app.core.rbac import get_current_user
from app.core.security import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    revoke_access_token,
    verify_password,
)
from app.db.session import get_db
from app.models.users import User
from app.schemas.auth import GuestIn, LoginIn, TokenOut

router = APIRouter(tags=["auth"])
log = logging.getLogger("netravision.auth")

# Hash bcrypt dummy untuk user yang tidak ada / nonaktif: login tetap
# menjalankan verify_password supaya waktu respons tidak membocorkan
# apakah username itu ada (timing oracle). Hash dibuat sekali per proses
# dari nilai acak, jadi tidak pernah cocok dengan password nyata.
_DUMMY_HASH = hash_password(secrets.token_hex(32))

# Kunci login per (username, IP), 4.9: kunci per username saja bisa
# dipakai untuk DoS akun (penyerang yang tahu username super_admin
# menguncinya berulang dari IP-nya sendiri). Dengan kunci gabungan,
# kegagalan dari satu IP hanya mengunci kombinasi username+IP itu;
# pemilik sah dari IP lain tetap bisa masuk. Rate limit per IP (5/menit
# di endpoint) tetap menjadi lapisan pertama; kunci ini melengkapi
# terhadap brute force dari banyak IP terhadap satu username.
# Direset saat login berhasil. In-memory per proses, seperti rate limiter.
_login_failures: dict[tuple[str, str], tuple[int, float]] = {}


def _login_locked(username: str, ip: str) -> bool:
    entry = _login_failures.get((username, ip))
    if entry is None:
        return False
    count, last = entry
    settings = get_settings()
    if count < settings.login_max_attempts:
        return False
    if time.monotonic() - last > settings.login_lockout_minutes * 60:
        _login_failures.pop((username, ip), None)
        return False
    return True


def _login_failed(username: str, ip: str) -> None:
    count, _last = _login_failures.get((username, ip), (0, 0.0))
    _login_failures[(username, ip)] = (count + 1, time.monotonic())


def _login_succeeded(username: str, ip: str) -> None:
    _login_failures.pop((username, ip), None)


def reset_login_attempts() -> None:
    """Kosongkan kunci login (dipakai test agar antar-test terisolasi)."""
    _login_failures.clear()


# T-2: cookie HttpOnly untuk token. Secure hanya bila request lewat HTTPS
# (di belakang Apache produksi selalu HTTPS; di demo/dev HTTP lokal
# cookie tetap terkirim karena Secure=False). SameSite=Lax: cookie ikut
# pada navigasi top-level dan request same-site, tapi tidak pada request
# cross-site biasa. Frontend adalah static export satu origin dengan API
# (proxy /api/* yang sama), jadi cookie first-party ini selalu terkirim.
# 2026-11-18: di prod Secure SELALU True. Sebelumnya Secure bergantung
# pada request.url.scheme tanpa ProxyHeadersMiddleware, dan Apache
# mem-proxy HTTP ke Uvicorn, scheme yang dilihat API adalah http,
# sehingga cookie kemungkinan diterbitkan Secure=False di produksi.
# Dengan ProxyHeadersMiddleware di main.py, X-Forwarded-Proto dari
# Apache sudah dipercaya; penjaga prod di sini adalah lapis kedua.
def _cookie_secure(request: Request) -> bool:
    if get_settings().app_env == "prod":
        return True
    return request.url.scheme == "https"


def _set_auth_cookies(
    response: Response,
    request: Request,
    access: str,
    refresh: str | None,
    expires_in: int,
) -> None:
    secure = _cookie_secure(request)
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=expires_in,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    if refresh:
        settings = get_settings()
        response.set_cookie(
            REFRESH_COOKIE,
            refresh,
            max_age=settings.jwt_refresh_days * 86400,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/api/auth",
        )
    else:
        # Tamu tidak punya refresh token: hapus cookie refresh basi
        # dari sesi sebelumnya supaya tidak ikut terkirim.
        response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
# 4.2: grace window dipersempit dari 60 detik menjadi 10 detik.
# Fungsinya hanya menahan race refresh bersamaan (dua request dengan
# token yang sama meluncur bersamaan, mis. retry klien / double-submit);
# 10 detik jauh di atas jeda race normal, tapi jauh di bawah jendela
# replay 60 detik sebelumnya yang membuat token curian dan token korban
# sama-sama sah selama satu menit penuh.
_GRACE_SECONDS = 10.0
# user_id -> (hash token lama, jti token lama, batas grace monotonic).
_recent_refresh: dict[int, tuple[str, str | None, float]] = {}


def _grace_accept(user_id: int, token_hash: str, jti: str | None) -> bool:
    entry = _recent_refresh.get(user_id)
    if entry is None:
        return False
    old_hash, old_jti, until = entry
    if time.monotonic() > until:
        _recent_refresh.pop(user_id, None)
        return False
    # Token grace harus SAMA PERSIS dengan yang baru dirotasi (hash dan
    # jti cocok): token lain dari keluarga yang sama bukan retry
    # bersamaan, melainkan pemakaian ulang.
    return hmac.compare_digest(old_hash, token_hash) and old_jti == jti


def _grace_remember(user_id: int, old_hash: str | None, old_jti: str | None) -> None:
    if old_hash:
        _recent_refresh[user_id] = (
            old_hash, old_jti, time.monotonic() + _GRACE_SECONDS
        )


def _grace_clear(user_id: int) -> None:
    _recent_refresh.pop(user_id, None)


# 4.2: token yang SUDAH dirotasi keluar (hash -> batas ingat monotonic).
# Dipakai deteksi pemakaian ulang: token yang dipresentasikan lagi
# SETELAH grace window habis bukan retry, melainkan reuse, kemungkinan
# token curian yang dipakai penyerang setelah korban sempat me-rotasi.
# Disimpan in-memory per proses (cukup untuk deployment single-replica);
# restart proses menghapus ingatan ini, tapi hash aktif di DB tetap
# melindungi (token lama tetap ditolak 401, hanya tanpa pencabutan
# keluarga). Dibatasi 8 hash terakhir per user, TTL = umur refresh.
_rotated_out: dict[int, dict[str, float]] = {}
_MAX_ROTATED_PER_USER = 8


def _rotated_remember(user_id: int, old_hash: str | None) -> None:
    if not old_hash:
        return
    settings = get_settings()
    ttl = max(settings.jwt_refresh_days, 1) * 86400.0
    seen = _rotated_out.setdefault(user_id, {})
    seen[old_hash] = time.monotonic() + ttl
    while len(seen) > _MAX_ROTATED_PER_USER:
        oldest = min(seen, key=lambda h: seen[h])
        del seen[oldest]


def _rotated_contains(user_id: int, token_hash: str) -> bool:
    seen = _rotated_out.get(user_id)
    if not seen:
        return False
    now = time.monotonic()
    expired = [h for h, until in seen.items() if until <= now]
    for h in expired:
        del seen[h]
    return token_hash in seen


def _rotated_clear(user_id: int) -> None:
    _rotated_out.pop(user_id, None)


def reset_refresh_state() -> None:
    """Kosongkan grace + jejak token terotasi (dipakai test)."""
    _recent_refresh.clear()
    _rotated_out.clear()


def revoke_refresh_sessions(user: User) -> None:
    """Cabut SEMUA sesi refresh milik user (4.1).

    Dipakai saat password diganti (oleh diri sendiri maupun admin) dan
    saat akun dinonaktifkan: sesi curian tidak boleh hidup selamanya
    walau password sudah diganti. Membersihkan hash + jti di DB dan
    grace + jejak rotasi di memori. Pemanggil wajib commit.
    """
    user.refresh_token_hash = None
    user.refresh_token_jti = None
    _grace_clear(user.id)
    _rotated_clear(user.id)


async def _get_active_user(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(
        select(User).where(User.username == username, User.is_active.is_(True))
    )
    return result.scalars().first()


def _revoke_presented_access(request: Request) -> None:
    """Cabut access token yang dipresentasikan request ini (logout /
    ganti password sendiri). Token dibaca dari cookie HttpOnly dulu,
    lalu header Authorization. Kegagalan decode diabaikan (token
    sudah tidak valid = tidak perlu dicabut)."""
    raw = request.cookies.get(ACCESS_COOKIE)
    if not raw:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            raw = auth[7:].strip() or None
    if raw:
        revoke_access_token(raw, get_settings())


# 2026-11-18: mode cookie-only opt-in. Klien browser yang mengirim
# header `X-Cookie-Only-Auth: 1` TIDAK menerima token di body respons
# (hanya cookie HttpOnly yang diset), menutup celah token di body
# yang bisa dicuri lewat XSS. Klien API tetap menerima token di body
# secara default, karena banyak klien/test mengandalkannya; default
# BELUM dibalik ke cookie-only (butuh perubahan frontend + klien API
# lebih dulu). Bila header ini dikirim, access_token di body berupa
# string kosong dan refresh_token None.
_COOKIE_ONLY_HEADER = "x-cookie-only-auth"


def _token_out_for_request(request: Request, pair: TokenOut) -> TokenOut:
    if request.headers.get(_COOKIE_ONLY_HEADER, "").strip().lower() in (
        "1", "true", "yes",
    ):
        return TokenOut(
            access_token="",
            refresh_token=None,
            expires_in=pair.expires_in,
        )
    return pair


def _token_pair(user: User) -> TokenOut:
    settings = get_settings()
    access = create_access_token(user.id, user.username, user.role, settings)
    refresh, jti = create_refresh_token(user.id, settings)
    # Login baru membatalkan grace token lama user ini dan memulai
    # keluarga token baru (jejak rotasi lama ikut dibuang).
    _grace_clear(user.id)
    _rotated_clear(user.id)
    user.refresh_token_hash = hash_token(refresh)
    user.refresh_token_jti = jti
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_minutes * 60,
    )


@router.post(
    "/auth/login",
    response_model=TokenOut,
    dependencies=[Depends(rate_limited(5, 60))],
)
async def login(
    data: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    ip = client_ip(request)
    if _login_locked(data.username, ip):
        log.warning("login terkunci username=%s ip=%s", data.username, ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="terlalu banyak percobaan login, coba lagi nanti",
        )
    user = await _get_active_user(db, data.username)
    # User tidak ada / nonaktif tetap diverifikasi terhadap hash dummy:
    # tanpa ini, login username salah kembali jauh lebih cepat daripada
    # login password salah, dan penyerang bisa mengenumerasi username.
    ok = verify_password(data.password, user.password_hash) if user is not None else verify_password(data.password, _DUMMY_HASH)
    if user is None or not ok:
        _login_failed(data.username, ip)
        # 4.15: kegagalan login dicatat (tanpa password, tanpa
        # membedakan user ada/tidak di pesan maupun log).
        log.warning("login gagal username=%s ip=%s", data.username, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="username/password salah"
        )
    _login_succeeded(data.username, ip)
    pair = _token_pair(user)
    await db.commit()
    # T-2: token juga diterbitkan sebagai cookie HttpOnly; body TokenOut
    # dipertahankan supaya klien API (non-browser) tetap bisa memakai
    # header Authorization seperti sebelumnya. Klien browser yang
    # mengirim X-Cookie-Only-Auth: 1 tidak menerima token di body
    # (lihat _token_out_for_request).
    _set_auth_cookies(response, request, pair.access_token, pair.refresh_token, pair.expires_in)
    return _token_out_for_request(request, pair)


@router.post(
    "/auth/refresh",
    response_model=TokenOut,
    # 20 -> 120/menit (perintah user 2026-11-20): refresh dipanggil
    # tiap tab, tiap reconnect WebSocket, dan tiap 401; batas 20/menit
    # per IP kena 429 di pemakaian normal (banyak tab / reconnect).
    # Refresh token acak panjang, bukan target brute-force seperti
    # login (tetap 5/menit), jadi batas longgar aman. Frontend tetap
    # punya backoff saat 429 (tryRefresh di lib/api.ts).
    dependencies=[Depends(rate_limited(120, 60))],
)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    """Rotasi refresh token. Token dibaca dari body JSON
    {"refresh_token": ...} bila ada (klien API dan tes lama), bila tidak
    dari cookie HttpOnly (browser). Body sengaja dibaca manual (bukan
    lewat skema RefreshIn) agar body kosong {} dari browser yang memakai
    cookie tidak ditolak validasi 422. Urutan ini penting: token body
    yang eksplisit harus menang atas cookie, supaya pemakaian ulang
    token lama tetap terdeteksi walau klien juga menyimpan cookie baru.
    """
    settings = get_settings()
    raw_token = None
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        raw_token = body.get("refresh_token")
    if not raw_token:
        raw_token = request.cookies.get(REFRESH_COOKIE)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh ditolak"
        )
    try:
        payload = decode_token(raw_token, settings)
    except ValueError as e:
        # Pesan generik: detail decode tidak boleh bocor ke klien.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh ditolak") from e
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token salah tipe")

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token tidak valid")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    presented = hash_token(raw_token)
    presented_jti = payload.get("jti")
    # 4.2: token aktif harus cocok hash-nya DAN jti-nya (bila jti
    # tersimpan; token terbitan sebelum migrasi 0026 tidak punya jti
    # tersimpan dan lolos lewat hash saja sampai dirotasi sekali).
    jti_ok = (
        user is not None
        and (
            getattr(user, "refresh_token_jti", None) is None
            or user.refresh_token_jti == presented_jti
        )
    )
    current_ok = (
        user is not None
        and user.is_active
        and user.refresh_token_hash is not None
        and hmac.compare_digest(user.refresh_token_hash, presented)
        and jti_ok
    )
    # A-S13: terima juga hash yang baru saja dirotasi selama grace window.
    grace_ok = (
        user is not None
        and user.is_active
        and _grace_accept(user.id, presented, presented_jti)
    )
    if not (current_ok or grace_ok):
        # 4.2: token yang SUDAH dirotasi keluar dan dipakai lagi di luar
        # grace window = pemakaian ulang (reuse), kemungkinan token
        # curian. Cabut SELURUH keluarga token user itu: penyerang yang
        # sedang memegang token hasil rotasi ikut terkunci keluar, dan
        # pemilik harus login ulang. Token asing yang tidak pernah sah
        # hanya ditolak biasa tanpa pencabutan.
        if user is not None and _rotated_contains(user.id, presented):
            revoke_refresh_sessions(user)
            await db.commit()
            log.warning(
                "refresh dipakai ulang user_id=%s: seluruh sesi dicabut", user.id
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="refresh dipakai ulang, semua sesi dicabut",
            )
        # 4.15: refresh ditolak dicatat (tanpa token).
        log.warning("refresh ditolak user_id=%s", user_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh ditolak")

    # Rotation: token lama hangus, terbit pasangan baru. Hash lama
    # disimpan di grace window supaya refresh bersamaan tidak gagal,
    # dan dicatat sebagai token terotasi supaya pemakaian ulang di
    # luar grace bisa dideteksi dan mencabut keluarga token.
    old_hash = user.refresh_token_hash
    old_jti = getattr(user, "refresh_token_jti", None)
    pair = _token_pair(user)
    _grace_remember(user.id, old_hash, old_jti)
    _rotated_remember(user.id, old_hash)
    await db.commit()
    _set_auth_cookies(response, request, pair.access_token, pair.refresh_token, pair.expires_in)
    return _token_out_for_request(request, pair)


@router.post("/auth/logout", dependencies=[Depends(rate_limited(20, 60))])
async def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # 2026-11-18: cabut JUGA access token yang dipresentasikan (jti
    # masuk denylist), bukan hanya refresh token. Sebelumnya access
    # token tetap sah sampai kedaluwarsa setelah logout.
    _revoke_presented_access(request)
    if user.id:  # guest ephemeral tidak punya baris DB
        result = await db.execute(select(User).where(User.id == user.id))
        db_user = result.scalars().first()
        if db_user is not None:
            revoke_refresh_sessions(db_user)
            await db.commit()
    # T-2: hapus cookie auth di browser, walau sesi sudah mati.
    _clear_auth_cookies(response)
    return {"ok": True}


@router.get("/auth/guest-enabled", dependencies=[Depends(rate_limited(30, 60))])
async def guest_enabled(db: AsyncSession = Depends(get_db)) -> dict:
    """Apakah login guest sedang aktif (dipakai halaman login untuk
    menampilkan atau menyembunyikan tombol Guest)."""
    return {"enabled": await _guest_login_enabled(db)}


async def _guest_login_enabled(db: AsyncSession) -> bool:
    """Login guest aktif bila baris guest di DB aktif.

    Bila baris guest belum ada (DB lama sebelum migrasi 0011),
    pakai env GUEST_ENABLED sebagai cadangan.
    """
    result = await db.execute(select(User).where(User.username == "guest"))
    row = result.scalars().first()
    if row is not None:
        return bool(row.is_active)
    return get_settings().guest_enabled


@router.post(
    "/auth/guest",
    response_model=TokenOut,
    dependencies=[Depends(rate_limited(5, 60))],
)
async def guest(
    data: GuestIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    """Login tamu untuk semua pengunjung, tanpa password, tanpa
    autentikasi apapun (2026-11-06). Nonaktif bila baris guest di DB
    is_active False (diatur superadmin lewat web); bila baris belum
    ada, nonaktif bila GUEST_ENABLED false."""
    if not await _guest_login_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="login tamu nonaktif"
        )
    settings = get_settings()
    access = create_access_token("guest", "guest", "guest", settings, expires_minutes=60)
    out = TokenOut(access_token=access, refresh_token=None, expires_in=3600)
    # T-2: access token tamu sebagai cookie HttpOnly; refresh tidak ada,
    # jadi cookie refresh basi ikut dihapus oleh _set_auth_cookies.
    _set_auth_cookies(response, request, access, None, 3600)
    return _token_out_for_request(request, out)


@router.get("/auth/me", dependencies=[Depends(rate_limited(60, 60))])
async def me(user: User = Depends(get_current_user)) -> dict:
    """Profil user dari token saat ini (dipakai web saat boot)."""
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "admin_group": user.admin_group,
    }


# Helper internal (dipakai skrip seed Fase 1, bukan endpoint publik).
def _make_password_hash(password: str) -> str:  # pragma: no cover
    return hash_password(password)
