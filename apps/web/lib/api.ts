/* Klien API — fetch wrapper dengan auto refresh token. */

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
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

/* Penanda sesi guest: dipakai agar sesi guest yang mati (token kedaluwarsa
   / network blip / reload) bisa login ulang sendiri tanpa dilempar ke
   halaman login — guest memang tanpa autentikasi apapun. */
export function setGuestSession(isGuest: boolean) {
  if (typeof window === "undefined") return;
  if (isGuest) localStorage.setItem(GUEST_KEY, "1");
  else localStorage.removeItem(GUEST_KEY);
}

export function isGuestSession(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(GUEST_KEY) === "1";
}

/* Single-flight: refresh yang sedang berjalan dipakai bersama agar
   dua request 401 bersamaan tidak saling menginvalidasi token. */
let refreshPromise: Promise<boolean> | null = null;

export async function tryRefresh(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const rt = getRefreshToken();
    if (!rt) return false;
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) {
        // Refresh token mati/kedaluwarsa: bersihkan sesi agar user login ulang.
        if (res.status === 401) clearTokens();
        return false;
      }
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
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
    // guest lalu ulangi sekali — guest tanpa autentikasi, jangan lempar
    // pengguna ke halaman login. Sesi guest lama ditandai refresh "null".
    if (isGuestSession() || getRefreshToken() === "null") {
      try {
        const g = await fetch(`${BASE}/auth/guest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (g.ok) {
          const data = await g.json();
          setTokens(data.access_token, data.refresh_token);
          return apiFetch(path, init, true);
        }
      } catch {
        /* abaikan, lanjut ke refresh biasa */
      }
    }
    if (await tryRefresh()) {
      return apiFetch(path, init, true);
    }
  }
  if (
    res.status === 401 &&
    typeof window !== "undefined" &&
    !getRefreshToken() &&
    !window.location.pathname.startsWith("/login") &&
    !window.location.pathname.startsWith("/embed")
  ) {
    // Sesi benar-benar mati: kembali ke halaman login.
    window.location.href = "/login";
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
    throw new ApiError(res.status, msg);
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

/* URL ber-token untuk <img> (poster) yang tidak bisa mengirim header Authorization. */
export function withToken(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  const t = getAccessToken();
  if (!t) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t);
}

/* Normalisasi URL upload lama: /uploads/... -> /api/uploads/... agar lewat
   reverse-proxy. Upload baru sudah memakai /api/uploads/... langsung. */
export function normalizeUploadUrl(url: string): string {
  if (url.startsWith("/uploads/")) return "/api" + url;
  return url;
}
