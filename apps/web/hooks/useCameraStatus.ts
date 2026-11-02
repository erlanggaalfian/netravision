"use client";

import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "../lib/api";
import type { StatusChange, Stream } from "../lib/types";

/* Hook status kamera real-time via WebSocket /ws. */

export function useCameraStatus() {
  const [status, setStatus] = useState<Map<number, boolean>>(new Map());
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const connect = () => {
      const token = getAccessToken();
      if (!token) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(
        `${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`,
      );
      wsRef.current = ws;

      ws.onopen = () => {
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
      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) {
          const delay = Math.min(1000 * 2 ** retryRef.current, 15000);
          retryRef.current += 1;
          timer = setTimeout(connect, delay);
        }
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
  }, []);

  return { status, connected };
}
