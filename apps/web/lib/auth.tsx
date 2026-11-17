"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, clearSession, isGuestSession, setGuestSession } from "./api";
import { clearMediaTokenCache } from "./media-token";
import type { User } from "./types";

/* Peran dengan hak admin penuh di UI (paritas v2.0: super_admin = kuasa penuh). */
export function isAdminRole(role?: string | null): boolean {
  return role === "admin" || role === "super_admin";
}

interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  loginGuest: () => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

async function fetchMe(): Promise<User | null> {
  try {
    return await api.get<User>("/auth/me");
  } catch {
    return null;
  }
}

/* Jeda sebelum mencoba /auth/me sekali lagi setelah login berhasil. */
const ME_RETRY_DELAY_MS = 800;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  /* F3.4: id pengguna terakhir, untuk mendeteksi pergantian pengguna
     di tab yang sama tanpa reload (cache token media milik pengguna
     lama tidak boleh dipakai sesi pengguna baru). */
  const lastUserIdRef = useRef<number | null>(null);

  useEffect(() => {
    // T-2: sesi dikenali lewat cookie HttpOnly, bukan token di
    // localStorage. Boot selalu mencoba /auth/me (cookie ikut otomatis);
    // bila gagal dan sebelumnya sesi guest, login ulang diam-diam.
    const boot = async () => {
      try {
        const u = await fetchMe();
        if (u) {
          setUser(u);
        } else if (
          isGuestSession() &&
          !window.location.pathname.startsWith("/login")
        ) {
          try {
            await loginGuest();
          } catch {
            /* gagal (mis. guest nonaktif / jaringan mati): biarkan login manual */
          }
        }
      } finally {
        setLoading(false);
      }
    };
    boot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* F3.4: bila user id berganti selagi provider hidup, kosongkan cache
     token media sebelum sesi baru memakai tile atau modal. */
  useEffect(() => {
    if (!user) return;
    if (lastUserIdRef.current !== null && lastUserIdRef.current !== user.id) {
      clearMediaTokenCache();
    }
    lastUserIdRef.current = user.id;
  }, [user]);

  /* F3.8: /auth/me setelah login berhasil. Bila gagal sesaat (blip
     jaringan), coba sekali lagi dengan jeda singkat; bila tetap gagal,
     lempar error supaya halaman login menampilkan pesan yang jelas,
     bukan membiarkan user null lalu ditendang balik ke /login tanpa
     penjelasan. */
  const fetchMeOrThrow = useCallback(async (): Promise<User> => {
    const first = await fetchMe();
    if (first) return first;
    await new Promise((r) => setTimeout(r, ME_RETRY_DELAY_MS));
    const second = await fetchMe();
    if (second) return second;
    throw new Error("Login berhasil, tetapi profil tidak dapat dimuat. Coba masuk lagi.");
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    // T-2: backend mengatur cookie HttpOnly; respons login tidak
    // disimpan ke mana pun, profil dibaca lewat /auth/me.
    // F3.4: kosongkan cache token media pengguna sebelumnya di awal
    // login, sebelum sesi baru terbentuk.
    clearMediaTokenCache();
    await api.post("/auth/login", { username, password });
    setGuestSession(false);
    setUser(await fetchMeOrThrow());
  }, [fetchMeOrThrow]);

  const loginGuest = useCallback(async () => {
    // F3.4: sama seperti login biasa, cache token sesi sebelumnya
    // tidak boleh terbawa ke sesi guest baru.
    clearMediaTokenCache();
    await api.post("/auth/guest", {});
    setGuestSession(true);
    setUser(await fetchMeOrThrow());
  }, [fetchMeOrThrow]);

  const logout = useCallback(async () => {
    try {
      // Server menghapus cookie HttpOnly.
      await api.post("/auth/logout", {});
    } catch {
      /* abaikan */
    }
    // F3.4: token media milik pengguna yang keluar tidak boleh
    // bertahan di memori tab untuk pengguna berikutnya.
    clearMediaTokenCache();
    clearSession();
    setUser(null);
  }, []);

  return (
    <Ctx.Provider value={{ user, loading, login, loginGuest, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth harus di dalam AuthProvider");
  return ctx;
}
