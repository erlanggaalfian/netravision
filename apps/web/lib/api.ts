/* Klien API, fetch wrapper dengan auto refresh token. */

import { useEffect, useState } from "react";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

const ACCESS_KEY = "nv_access";
const REFRESH_KEY = "nv_refresh";
const GUEST_KEY = "nv_guest";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  const v = localStorage.getItem(REFRESH_KEY);
  // Sesi guest lama menyimpan refresh token sebagai string literal "null".
  // Jangan pernah mengembalikan string itu sebagai token yang sah.
  if (v === "null") return null;
  return v;
}

/* Jangan pernah menyimpan refresh_token guest (null dari backend) sebagai
   string literal "null" di localStorage. Bila refresh null/kosong/"null",
   hapus kunci refresh agar sesi dikenali sebagai tanpa refresh token. */
export function setTokens(access: string, refresh?: string | null) {
  localStorage.setItem(ACCESS_KEY, access);
  if (refresh && refresh !== "null") localStorage.setItem(REFRESH_KEY, refresh);
  else localStorage.removeItem(REFRESH_KEY);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

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
  // Penanda lama: refresh token tersimpan sebagai string literal "null"
  // (sebelum flag nv_guest ada) tetap dikenali sebagai sesi guest.
  return (
    localStorage.getItem(GUEST_KEY) === "1" ||
    localStorage.getItem(REFRESH_KEY) === "null"
  );
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

/* Single-flight: refresh yang sedang berjalan dipakai bersama agar
   dua request 401 bersamaan tidak saling menginvalidasi token. */
let refreshPromise: Promise<boolean> | null = null;
/* Hasil kegagalan refresh terakhir: status HTTP, "network" bila fetch
   gagal total (jaringan mati), atau null bila tidak ada refresh token /
   refresh belum pernah gagal. Dipakai apiFetch (F-R6) untuk membedakan
   401 (token mati, sudah dibersihkan) dari jaringan/500. */
let lastRefreshFailure: number | "network" | null = null;

export function getLastRefreshFailure(): number | "network" | null {
  return lastRefreshFailure;
}

export async function tryRefresh(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const rt = getRefreshToken();
    if (!rt) {
      lastRefreshFailure = null;
      return false;
    }
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) {
        lastRefreshFailure = res.status;
        // Refresh token mati/kedaluwarsa: bersihkan sesi agar user login ulang.
        if (res.status === 401) clearTokens();
        return false;
      }
      const data = await res.json();
      lastRefreshFailure = null;
      setTokens(data.access_token, data.refresh_token);
      return true;
    } catch {
      lastRefreshFailure = "network";
      return false;
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
      const g = await fetch(`${BASE}/auth/guest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!g.ok) return false;
      const data = await g.json();
      setTokens(data.access_token, data.refresh_token ?? null);
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

export class ApiError extends Error {
  status: number;
  retryAfter: number | null;
  constructor(status: number, message: string, retryAfter: number | null = null) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  retried = false,
): Promise<Response> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init.body && typeof init.body === "string") {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
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
    if (await tryRefresh()) {
      return apiFetch(path, init, true);
    }
  }
  if (
    res.status === 401 &&
    typeof window !== "undefined" &&
    !window.location.pathname.startsWith("/login") &&
    !window.location.pathname.startsWith("/embed")
  ) {
    // Sesi benar-benar mati: kembali ke halaman login. Bukan hanya bila
    // refresh token sudah hilang, tapi juga bila refresh gagal karena
    // jaringan/500 (bukan 401): token mati yang tersimpan tidak akan
    // pernah pulih sendiri, jadi bersihkan lalu antar ke /login.
    const hardFailure =
      getLastRefreshFailure() === "network" ||
      (typeof getLastRefreshFailure() === "number" &&
        (getLastRefreshFailure() as number) !== 401);
    if (!getRefreshToken() || hardFailure) {
      if (hardFailure) clearTokens();
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

/* Poster diambil lewat apiFetch (header Authorization) sebagai blob lalu
   dipakai sebagai object URL, jadi JWT tidak pernah muncul di URL gambar
   (tidak bocor ke log/histori/cache). Pemakai wajib revoke object URL
   saat tidak dipakai lagi, lihat usePosterUrl. */
export async function fetchPosterObjectUrl(
  url: string | null | undefined,
): Promise<string | undefined> {
  if (!url) return undefined;
  let path: string;
  if (/^https?:\/\//i.test(url)) {
    // URL absolut: fetch langsung dengan header Authorization.
    const token = getAccessToken();
    const res = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) return undefined;
    return URL.createObjectURL(await res.blob());
  }
  path = url.startsWith("/api/") ? url.slice(4) : url;
  const res = await apiFetch(path);
  if (!res.ok) return undefined;
  return URL.createObjectURL(await res.blob());
}

export function usePosterUrl(url: string | null | undefined): string | undefined {
  const [src, setSrc] = useState<string | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    let obj: string | undefined;
    if (!url) {
      setSrc(undefined);
      return;
    }
    fetchPosterObjectUrl(url)
      .then((u) => {
        if (!alive) {
          if (u) URL.revokeObjectURL(u);
          return;
        }
        obj = u;
        setSrc(u);
      })
      .catch(() => {
        /* poster gagal dimuat: pemakai menampilkan fallback */
      });
    return () => {
      alive = false;
      if (obj) URL.revokeObjectURL(obj);
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
