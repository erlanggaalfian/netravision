/* Klien API, fetch wrapper dengan auto refresh token.
   T-2: token JWT TIDAK LAGI disimpan di localStorage. Browser
   menerima token sebagai cookie HttpOnly dari backend (login, refresh,
   guest) dan mengirimnya otomatis lewat credentials: "include".
   localStorage hanya menyimpan penanda JENIS sesi (guest atau bukan),
   bukan token. */

import { useEffect, useState } from "react";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

const GUEST_KEY = "nv_guest";

/* Batas tunggu respons API (F3.2): timer hanya menunggu respons awal
   (header) dari server, lalu dibersihkan begitu fetch resolve, jadi
   unduhan body yang panjang (mis. segmen rekaman di Playback) tidak
   ikut dibatalkan. Request API biasa 15 detik, refresh 30 detik. */
const API_TIMEOUT_MS = 15_000;
const REFRESH_TIMEOUT_MS = 30_000;
const GUEST_TIMEOUT_MS = 15_000;

/* Penanda sesi guest: dipakai agar sesi guest yang mati (token kedaluwarsa
   / network blip / reload) bisa login ulang sendiri tanpa dilempar ke
   halaman login, guest memang tanpa autentikasi apapun. */
export function setGuestSession(isGuest: boolean) {
  if (typeof window === "undefined") return;
  if (isGuest) localStorage.setItem(GUEST_KEY, "1");
  else localStorage.removeItem(GUEST_KEY);
}

export function isGuestSession(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(GUEST_KEY) === "1";
}

/* Sesi berakhir: hapus penanda jenis sesi. Cookie HttpOnly dihapus
   server lewat POST /auth/logout; di sini hanya penanda lokal. */
export function clearSession() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(GUEST_KEY);
}

/* Parse header Retry-After (detik, atau tanggal HTTP) menjadi detik tunggu.
   Mengembalikan null bila header tidak ada / tidak bisa dibaca. */
export function parseRetryAfter(res: Response): number | null {
  const raw = res.headers.get("Retry-After");
  if (!raw) return null;
  const secs = Number(raw.trim());
  if (Number.isFinite(secs)) return Math.max(0, Math.min(300, Math.floor(secs)));
  const dateMs = Date.parse(raw.trim());
  if (Number.isFinite(dateMs)) {
    return Math.max(0, Math.min(300, Math.floor((dateMs - Date.now()) / 1000)));
  }
  return null;
}

export class ApiError extends Error {
  status: number;
  retryAfter: number | null;
  /* Kode yang bisa dibedakan pemanggil: "timeout" bila server tidak
     merespons dalam batas waktu, "network" bila fetch gagal total,
     null untuk error HTTP biasa. Pesan sudah berbahasa Indonesia
     supaya halaman bisa menampilkannya langsung dengan tombol coba lagi. */
  code: "timeout" | "network" | null;
  constructor(
    status: number,
    message: string,
    retryAfter: number | null = null,
    code: "timeout" | "network" | null = null,
  ) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
    this.code = code;
  }
}

/* Fetch dengan batas waktu (F3.2): AbortController membatalkan request
   bila server tidak memberi respons awal dalam timeoutMs. Sinyal dari
   pemanggil (bila ada) tetap dihormati dan diteruskan. */
async function fetchWithTimeout(
  input: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const onOuterAbort = () => ctrl.abort();
  const outer = init.signal;
  if (outer) {
    if (outer.aborted) ctrl.abort();
    else outer.addEventListener("abort", onOuterAbort, { once: true });
  }
  try {
    return await fetch(input, { ...init, signal: ctrl.signal });
  } catch (e) {
    if (e instanceof ApiError) throw e;
    /* Pembatalan dari pemanggil sendiri: teruskan error aslinya,
       jangan disamarkan jadi error jaringan. */
    if (outer?.aborted) throw e;
    if (ctrl.signal.aborted) {
      throw new ApiError(0, "Server tidak merespons, coba lagi", null, "timeout");
    }
    throw new ApiError(0, "Jaringan tidak tersedia, coba lagi", null, "network");
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener("abort", onOuterAbort);
  }
}

/* Hasil kegagalan refresh terakhir: status HTTP, "network" bila fetch
   gagal total (jaringan mati), "timeout" bila server tidak merespons,
   atau null bila refresh belum pernah gagal / terakhir berhasil. */
export type RefreshFailure = number | "network" | "timeout" | null;

export interface RefreshResult {
  ok: boolean;
  failure: RefreshFailure;
}

/* Single-flight: refresh yang sedang berjalan dipakai bersama agar
   dua request 401 bersamaan tidak saling menginvalidasi token. */
let refreshPromise: Promise<RefreshResult> | null = null;
/* Hasil kegagalan refresh terakhir, dipertahankan untuk kompatibilitas
   pembaca lama (getLastRefreshFailure). Nilai ini DITULIS oleh
   tryRefresh dan DIRESET di awal tiap apiFetch (F3.12), supaya jalur
   retried atau guest tidak membaca hasil percobaan sebelumnya.
   Jalur utama apiFetch memakai nilai kembalian lokal tryRefresh,
   bukan global ini. */
let lastRefreshFailure: RefreshFailure = null;

export function getLastRefreshFailure(): RefreshFailure {
  return lastRefreshFailure;
}

export async function tryRefresh(): Promise<RefreshResult> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async (): Promise<RefreshResult> => {
    try {
      // T-2: refresh token dibaca server dari cookie HttpOnly, jadi
      // body dikirim kosong dan cookie ikut lewat credentials.
      const res = await fetchWithTimeout(
        `${BASE}/auth/refresh`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
          credentials: "include",
        },
        REFRESH_TIMEOUT_MS,
      );
      if (!res.ok) {
        lastRefreshFailure = res.status;
        // Refresh token mati/kedaluwarsa: sesi berakhir, hapus penanda.
        if (res.status === 401) clearSession();
        return { ok: false, failure: res.status };
      }
      lastRefreshFailure = null;
      return { ok: true, failure: null };
    } catch (e) {
      const failure: RefreshFailure =
        e instanceof ApiError && e.code === "timeout" ? "timeout" : "network";
      lastRefreshFailure = failure;
      return { ok: false, failure };
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

/* Single-flight re-login guest: satu promise dipakai bersama semua 401
   bersamaan, agar tidak masing-masing menembak POST /auth/guest dan
   kena rate limit 429 (sama seperti refreshPromise pada tryRefresh). */
let guestLoginPromise: Promise<boolean> | null = null;

export async function tryGuestLogin(): Promise<boolean> {
  if (guestLoginPromise) return guestLoginPromise;
  guestLoginPromise = (async () => {
    try {
      const g = await fetchWithTimeout(
        `${BASE}/auth/guest`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
          credentials: "include",
        },
        GUEST_TIMEOUT_MS,
      );
      if (!g.ok) return false;
      setGuestSession(true);
      return true;
    } catch {
      return false;
    } finally {
      guestLoginPromise = null;
    }
  })();
  return guestLoginPromise;
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  retried = false,
): Promise<Response> {
  /* F3.12: reset penanda kegagalan refresh di awal tiap percobaan
     (bukan retried), supaya tidak ada yang membaca hasil percobaan
     refresh sebelumnya. */
  if (!retried) lastRefreshFailure = null;
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (init.body && typeof init.body === "string") {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
  // T-2: tanpa header Authorization; cookie HttpOnly ikut otomatis
  // lewat credentials: "include" (same-origin lewat proxy /api/*).
  const res = await fetchWithTimeout(
    `${BASE}${path}`,
    {
      ...init,
      headers,
      credentials: "include",
    },
    API_TIMEOUT_MS,
  );
  if (res.status === 401 && !retried) {
    // Sesi guest mati (token kedaluwarsa): login ulang diam-diam sebagai
    // guest lalu ulangi sekali, guest tanpa autentikasi, jangan lempar
    // pengguna ke halaman login. Single-flight (tryGuestLogin) agar
    // 401 bersamaan tidak masing-masing menembak POST /auth/guest.
    if (isGuestSession()) {
      if (await tryGuestLogin()) {
        return apiFetch(path, init, true);
      }
    }
    const refresh = await tryRefresh();
    if (refresh.ok) {
      return apiFetch(path, init, true);
    }
    /* F3.1: hanya redirect ke /login bila refresh gagal 401 (token
       benar-benar mati). Bila refresh gagal karena jaringan, timeout,
       atau 5xx, sesi mungkin masih bisa pulih: JANGAN clearSession
       dan JANGAN redirect, kembalikan respons 401 supaya pemanggil
       menampilkan pesan error dengan tombol coba lagi. */
    if (
      refresh.failure === 401 &&
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/login") &&
      !window.location.pathname.startsWith("/embed")
    ) {
      window.location.href = "/login";
    }
  }
  return res;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      msg = data.detail || data.message || msg;
    } catch {
      /* abaikan */
    }
    throw new ApiError(res.status, msg, parseRetryAfter(res));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => apiFetch(path).then(handle<T>),
  post: <T>(path: string, body?: unknown) =>
    apiFetch(path, { method: "POST", body: JSON.stringify(body ?? {}) }).then(
      handle<T>,
    ),
  put: <T>(path: string, body?: unknown) =>
    apiFetch(path, { method: "PUT", body: JSON.stringify(body ?? {}) }).then(
      handle<T>,
    ),
  patch: <T>(path: string, body?: unknown) =>
    apiFetch(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }).then(
      handle<T>,
    ),
  del: <T>(path: string) =>
    apiFetch(path, { method: "DELETE" }).then(handle<T>),
};

/* Ambil daftar berpaginasi: kembalikan { items, total, hasMore } dengan
   total dibaca dari header X-Total-Count yang dikirim backend. Dipakai
   halaman yang menampilkan Pagination bernomor (perintah user
   2026-11-17).
   F3.11: bila backend tidak mengirim header (total 0) tetapi halaman
   penuh, hasMore true supaya pemanggil tetap menampilkan halaman
   berikut atau tombol "Muat lagi" sebagai cadangan, bukan terkunci
   di 1 halaman. */
export async function apiGetPage<T>(
  path: string,
): Promise<{ items: T[]; total: number; hasMore: boolean }> {
  const res = await apiFetch(path);
  const total = Number(res.headers.get("X-Total-Count") ?? "0") || 0;
  const items = await handle<T[]>(res);
  let hasMore: boolean;
  if (total > 0) {
    hasMore = items.length > 0;
    try {
      const q = new URL(path, "http://localhost").searchParams;
      const offset = Number(q.get("offset") ?? "0") || 0;
      hasMore = offset + items.length < total;
    } catch {
      /* abaikan: pakai hasMore dari panjang items */
    }
  } else {
    /* Tanpa header total: halaman penuh berarti mungkin masih ada
       halaman berikut. Ukuran halaman dibaca dari param limit. */
    let limit = 0;
    try {
      limit = Number(new URL(path, "http://localhost").searchParams.get("limit") ?? "0") || 0;
    } catch {
      limit = 0;
    }
    hasMore = limit > 0 ? items.length >= limit : items.length > 0;
  }
  return { items, total, hasMore };
}

/* Poster diambil lewat apiFetch sebagai blob lalu dipakai sebagai object
   URL, jadi JWT tidak pernah muncul di URL gambar (tidak bocor ke
   log/histori/cache). Pemakai wajib revoke object URL saat tidak dipakai
   lagi, lihat usePosterUrl. Cookie HttpOnly ikut otomatis (credentials)
   untuk URL satu origin; URL absolut ke origin lain diambil tanpa
   kredensial. */
/* F5.8: cache bersama poster per URL (modul-level). Satu poster_url
   hanya di-fetch sekali per tab, bukan sekali per mount tile/panel.
   Object URL hasil cache sengaja TIDAK di-revoke oleh pemakai
   (usePosterUrl tidak lagi revoke): URL itu dipakai bersama banyak
   tile, revoke oleh satu tile akan merusak tile lain. Jumlah entri
   terbatas pada jumlah poster kamera, jadi kebocoran terkendali. */
const posterCache = new Map<string, Promise<string | undefined>>();
/* P0 code-review 2026-11-18: batas atas entri cache poster. Entri yang
   dikeluarkan dari map TIDAK di-revoke (object URL masih dipakai tile
   lain, lihat F5.8), yang hilang hanya dedup untuk URL itu, jadi
   fetch berikutnya mengunduh ulang posternya. */
const POSTER_CACHE_MAX_ENTRIES = 500;

export async function fetchPosterObjectUrl(
  url: string | null | undefined,
): Promise<string | undefined> {
  if (!url) return undefined;
  const cached = posterCache.get(url);
  if (cached) return cached;
  const promise = fetchPosterObjectUrlUncached(url).then((u) => {
    if (!u) posterCache.delete(url);
    return u;
  });
  if (posterCache.size >= POSTER_CACHE_MAX_ENTRIES) {
    const oldest = posterCache.keys().next();
    if (!oldest.done) posterCache.delete(oldest.value);
  }
  posterCache.set(url, promise);
  return promise;
}

async function fetchPosterObjectUrlUncached(
  url: string | null | undefined,
): Promise<string | undefined> {
  if (!url) return undefined;
  if (/^https?:\/\//i.test(url)) {
    // URL absolut: kredensial hanya untuk origin yang dipercaya
    // (halaman / API base); origin lain diambil tanpa kredensial
    // (gambar publik).
    let sameOrigin = false;
    try {
      const origin = new URL(url).origin;
      sameOrigin =
        (typeof window !== "undefined" && origin === window.location.origin) ||
        origin === new URL(BASE, window.location.origin).origin;
    } catch {
      sameOrigin = false;
    }
    if (!sameOrigin) {
      const res = await fetch(url);
      if (!res.ok) return undefined;
      return URL.createObjectURL(await res.blob());
    }
    /* F3.10: URL absolut satu origin lewat apiFetch, supaya 401 ikut
       jalur refresh token, bukan fetch mentah yang diam-diam gagal.
       apiFetch menambah BASE di depan path, jadi potong origin dulu
       menjadi path relatif. */
    const u = new URL(url);
    const res = await apiFetch(u.pathname + u.search);
    if (!res.ok) return undefined;
    return URL.createObjectURL(await res.blob());
  }
  const path = url.startsWith("/api/") ? url.slice(4) : url;
  const res = await apiFetch(path);
  if (!res.ok) return undefined;
  return URL.createObjectURL(await res.blob());
}

export function usePosterUrl(url: string | null | undefined): string | undefined {
  const [src, setSrc] = useState<string | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    /* F3.10: kosongkan poster lama di awal effect saat url berubah,
       supaya tile tidak menampilkan poster kamera lama sampai poster
       baru tiba. */
    setSrc(undefined);
    if (!url) {
      return;
    }
    fetchPosterObjectUrl(url)
      .then((u) => {
        if (!alive) return;
        setSrc(u);
      })
      .catch(() => {
        /* poster gagal dimuat: pemakai menampilkan fallback */
      });
    return () => {
      alive = false;
      /* F5.8: object URL dari cache bersama tidak di-revoke di sini,
         supaya tile lain yang memakai poster yang sama tidak rusak. */
    };
  }, [url]);
  return src;
}

/* Normalisasi URL upload lama: /uploads/... -> /api/uploads/... agar lewat
   reverse-proxy. Upload baru sudah memakai /api/uploads/... langsung. */
export function normalizeUploadUrl(url: string): string {
  if (url.startsWith("/uploads/")) return "/api" + url;
  return url;
}
