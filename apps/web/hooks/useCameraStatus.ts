"use client";

import { useEffect, useRef, useState } from "react";
import { isGuestSession, tryGuestLogin, tryRefresh } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { StatusChange, Stream } from "../lib/types";

/* Hook status kamera real-time via WebSocket /ws.
   T-2: token TIDAK LAGI dikirim lewat ?token= (tidak ada token di
   localStorage). Browser mengirim cookie HttpOnly otomatis saat
   handshake WebSocket same-origin; server membaca cookie itu
   (lihat routers/ws.py, perubahan koordinator). */

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
      const proto = location.protocol === "https:" ? "wss" : "ws";
      // Cookie HttpOnly ikut otomatis pada handshake same-origin.
      const ws = new WebSocket(`${proto}://${location.host}/ws`);
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
