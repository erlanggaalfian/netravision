"use client";

import { useEffect, useRef, useState } from "react";
import { getAccessToken, isGuestSession, tryGuestLogin, tryRefresh } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { StatusChange, Stream } from "../lib/types";

/* Hook status kamera real-time via WebSocket /ws. */

const TOKEN_REFRESH_MARGIN_MS = 60_000;

/* Kedaluwarsa access token (ms sejak epoch) dari klaim exp JWT, tanpa
   pustaka: token yang tidak bisa dibaca dianggap tidak kedaluwarsa agar
   server yang memutuskan (tutup 4401 -> refresh). */
function getTokenExpiryMs(token: string): number | null {
  try {
    const payload = JSON.parse(
      atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
    ) as { exp?: number };
    return typeof payload.exp === "number" ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

/* Pulihkan sesi lewat jalur yang sama seperti HTTP: sesi guest login
   ulang sebagai guest (refresh token guest memang null), sesi biasa
   lewat refresh. Dipakai sebelum menyambung (token basi) dan sesudah
   ditolak server (kode 4401). */
async function healSession(): Promise<void> {
  if (isGuestSession()) await tryGuestLogin();
  else await tryRefresh();
}

export function useCameraStatus() {
  const [status, setStatus] = useState<Map<number, boolean>>(new Map());
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  /* Tunggu AuthProvider selesai boot (termasuk re-login guest diam-diam)
     sebelum membuka WS, agar token belum ada saat mount tidak membuat
     WS mati tanpa pernah dimulai. */
  const { loading: authLoading } = useAuth();

  useEffect(() => {
    if (authLoading) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const scheduleReconnect = () => {
      if (cancelled) return;
      const delay = Math.min(1000 * 2 ** retryRef.current, 15000);
      retryRef.current += 1;
      timer = setTimeout(connect, delay);
    };

    const connect = async () => {
      let token = getAccessToken();
      /* Jangan menyambung dengan token yang sudah kedaluwarsa atau
         tinggal <60 detik: server akan menutup (4401) dan hook akan
         berputar memakai token basi yang sama. Refresh dulu. */
      const exp = token ? getTokenExpiryMs(token) : null;
      if (token && exp !== null && exp - Date.now() < TOKEN_REFRESH_MARGIN_MS) {
        await healSession();
        if (cancelled) return;
        token = getAccessToken();
      }
      if (!token) {
        // Token belum ada (mis. re-login guest AuthProvider masih jalan):
        // jangan return mati, jadwalkan percobaan ulang.
        scheduleReconnect();
        return;
      }
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(
        `${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`,
      );
      wsRef.current = ws;
      let opened = false;

      ws.onopen = () => {
        opened = true;
        setConnected(true);
        retryRef.current = 0;
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "snapshot" && Array.isArray(msg.streams)) {
            const m = new Map<number, boolean>();
            for (const s of msg.streams as Stream[]) m.set(s.id, s.is_online);
            setStatus(m);
          } else if (msg.type === "status" && Array.isArray(msg.changes)) {
            setStatus((prev) => {
              const next = new Map(prev);
              for (const c of msg.changes as StatusChange[])
                next.set(c.stream_id, c.is_online);
              return next;
            });
          } else if (msg.type === "pong") {
            /* abaikan */
          }
        } catch {
          /* abaikan */
        }
      };
      ws.onclose = async (ev) => {
        setConnected(false);
        if (cancelled) return;
        // Ditolak server (kode 4401 = token tidak sah/kedaluwarsa) atau
        // ditolak sebelum terbuka = token basi. Pulihkan dulu lewat
        // jalur self-healing yang sama seperti HTTP, supaya reconnect
        // tidak memakai token basi yang sama dan ditolak selamanya.
        // Tanpa ini reconnect memakai token basi dan berputar.
        if (ev.code === 4401 || !opened) {
          await healSession();
        }
        if (cancelled) return;
        scheduleReconnect();
      };
      ws.onerror = () => ws.close();
    };

    connect();
    const ping = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN)
        wsRef.current.send(JSON.stringify({ type: "ping" }));
    }, 25000);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearInterval(ping);
      wsRef.current?.close();
    };
  }, [authLoading]);

  return { status, connected };
}
