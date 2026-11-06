"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, clearTokens, getAccessToken, getRefreshToken, isGuestSession, setGuestSession, setTokens } from "./api";
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

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

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
    // Sesi guest lama (sebelum flag nv_guest ada) ditandai refresh token "null".
    const wasGuest = () =>
      isGuestSession() || getRefreshToken() === "null";
    const boot = async () => {
      try {
        if (!getAccessToken()) {
          // Tanpa token tapi sebelumnya sesi guest: login ulang diam-diam
          // (guest tanpa autentikasi; jangan lempar ke halaman login).
          if (wasGuest() && !window.location.pathname.startsWith("/login")) {
            try {
              await loginGuest();
            } catch {
              /* gagal (mis. guest nonaktif / jaringan mati): biarkan login manual */
            }
          }
          return;
        }
        const u = await fetchMe();
        if (u) {
          setUser(u);
        } else if (wasGuest() && !window.location.pathname.startsWith("/login")) {
          // Token mati/kedaluwarsa tapi sebelumnya sesi guest: pulihkan diam-diam.
          try {
            await loginGuest();
          } catch {
            /* gagal: biarkan login manual */
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
    const data = await api.post<TokenPair & { user: User }>("/auth/login", {
      username,
      password,
    });
    setTokens(data.access_token, data.refresh_token);
    setGuestSession(false);
    setUser(data.user ?? (await fetchMe()));
  }, []);

  const loginGuest = useCallback(async () => {
    const data = await api.post<TokenPair & { user: User }>("/auth/guest", {});
    setTokens(data.access_token, data.refresh_token);
    setGuestSession(true);
    setUser(data.user ?? (await fetchMe()));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout", {});
    } catch {
      /* abaikan */
    }
    clearTokens();
    setGuestSession(false);
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
