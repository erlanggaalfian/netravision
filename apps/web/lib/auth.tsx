"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, clearSession, isGuestSession, setGuestSession } from "./api";
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

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

  const login = useCallback(async (username: string, password: string) => {
    // T-2: backend mengatur cookie HttpOnly; respons login tidak
    // disimpan ke mana pun, profil dibaca lewat /auth/me.
    await api.post("/auth/login", { username, password });
    setGuestSession(false);
    setUser(await fetchMe());
  }, []);

  const loginGuest = useCallback(async () => {
    await api.post("/auth/guest", {});
    setGuestSession(true);
    setUser(await fetchMe());
  }, []);

  const logout = useCallback(async () => {
    try {
      // Server menghapus cookie HttpOnly.
      await api.post("/auth/logout", {});
    } catch {
      /* abaikan */
    }
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
