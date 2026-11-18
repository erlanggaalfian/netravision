"use client";

import { useEffect, useState } from "react";
import { isGuestSession, tryGuestLogin, tryRefresh, type RefreshFailure } from "../lib/api";
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
   ditolak server (kode 4401). Mengembalikan kegagalan refresh (null
   bila pulih): hanya 401 yang berarti sesi benar-benar mati. */
async function healSession(): Promise<RefreshFailure> {
  if (isGuestSession()) {
    return (await tryGuestLogin()) ? null : 401;
  }
  const r = await tryRefresh();
  return r.ok ? null : r.failure;
}

/* F5.2: satu WebSocket bersama per tab (singleton module-level).
   AppShell dan semua halaman memanggil useCameraStatus, tapi hanya
   ada 1 koneksi /ws: subscriber pertama membuka, subscriber terakhir
   menutup. Semua subscriber menerima snapshot dan update status yang
   sama, perilaku status kamera tidak berubah. Logika F3.5 (hitung
   4401 berturut-turut, hentikan reconnect dan arahkan ke login)
   dipertahankan, hanya dipindah ke level modul. */
type StatusListener = (status: Map<number, boolean>, connected: boolean) => void;

let sharedStatus = new Map<number, boolean>();
let sharedConnected = false;
const listeners = new Set<StatusListener>();
let sharedWs: WebSocket | null = null;
let sharedRetry = 0;
let sharedPing: ReturnType<typeof setInterval> | undefined;
let sharedTimer: ReturnType<typeof setTimeout> | undefined;
let sharedStarted = false;
/* F3.5 di level modul: kegagalan healSession 401 berturut-turut. */
let sharedAuthFailures = 0;
let sharedStopped = false;
let sharedLogout: (() => Promise<void>) | null = null;

function notifyShared() {
  const snap = new Map(sharedStatus);
  listeners.forEach((l) => l(snap, sharedConnected));
}

function scheduleSharedReconnect() {
  if (listeners.size === 0 || sharedStopped) return;
  const delay = Math.min(1000 * 2 ** sharedRetry, 15000);
  sharedRetry += 1;
  sharedTimer = setTimeout(connectShared, delay);
}

/* F3.5: sesi berakhir, hentikan reconnect dan arahkan ke login
   dengan pesan sesi berakhir. */
async function endSharedSession() {
  if (sharedStopped) return;
  sharedStopped = true;
  try {
    await sharedLogout?.();
  } catch {
    /* abaikan: tetap arahkan ke login */
  }
  if (typeof window !== "undefined") {
    try {
      sessionStorage.setItem("nv_session_expired", "1");
    } catch {
      /* abaikan */
    }
    window.location.href = "/login?session=expired";
  }
}

async function connectShared() {
  if (listeners.size === 0 || sharedWs || sharedStopped) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  // Cookie HttpOnly ikut otomatis pada handshake same-origin.
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  sharedWs = ws;
  let opened = false;

  ws.onopen = () => {
    opened = true;
    sharedConnected = true;
    sharedRetry = 0;
    sharedAuthFailures = 0;
    notifyShared();
  };
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "snapshot" && Array.isArray(msg.streams)) {
        const m = new Map<number, boolean>();
        for (const s of msg.streams as Stream[]) m.set(s.id, s.is_online);
        sharedStatus = m;
        notifyShared();
      } else if (msg.type === "status" && Array.isArray(msg.changes)) {
        const next = new Map(sharedStatus);
        for (const c of msg.changes as StatusChange[])
          next.set(c.stream_id, c.is_online);
        sharedStatus = next;
        notifyShared();
      } else if (msg.type === "pong") {
        /* abaikan */
      }
    } catch {
      /* abaikan */
    }
  };
  ws.onclose = async (ev) => {
    sharedWs = null;
    sharedConnected = false;
    notifyShared();
    if (listeners.size === 0 || sharedStopped) return;
    // Ditolak server (kode 4401 = token tidak sah/kedaluwarsa) atau
    // ditolak sebelum terbuka = token basi. Pulihkan dulu lewat
    // jalur self-healing yang sama seperti HTTP, supaya reconnect
    // tidak memakai token basi yang sama dan ditolak selamanya.
    if (ev.code === 4401 || !opened) {
      const failure = await healSession();
      if (listeners.size === 0 || sharedStopped) return;
      if (failure === null) {
        sharedAuthFailures = 0;
      } else if (ev.code === 4401 && failure === 401) {
        sharedAuthFailures += 1;
        if (sharedAuthFailures >= MAX_AUTH_FAILURES) {
          await endSharedSession();
          return;
        }
      }
      /* Kegagalan jaringan/5xx tidak dihitung: sesi mungkin
         pulih sendiri, jadi reconnect tetap berjalan. */
    }
    if (listeners.size === 0) return;
    scheduleSharedReconnect();
  };
  ws.onerror = () => ws.close();
}

function startShared() {
  if (sharedStarted) return;
  sharedStarted = true;
  sharedRetry = 0;
  void connectShared();
  sharedPing = setInterval(() => {
    if (sharedWs?.readyState === WebSocket.OPEN)
      sharedWs.send(JSON.stringify({ type: "ping" }));
  }, 25000);
}

function stopShared() {
  sharedStarted = false;
  clearTimeout(sharedTimer);
  clearInterval(sharedPing);
  sharedTimer = undefined;
  sharedPing = undefined;
  sharedWs?.close();
  sharedWs = null;
  sharedConnected = false;
  /* Subscriber terakhir pergi (mis. logout): reset penanda sesi
     berakhir supaya login berikutnya bisa menyambung lagi. */
  sharedStopped = false;
  sharedAuthFailures = 0;
}

/* F3.5: berapa kali 4401 berturut-turut dengan refresh gagal 401
   sebelum reconnect dihentikan dan pengguna diarahkan ke login. */
const MAX_AUTH_FAILURES = 3;

export function useCameraStatus() {
  const [status, setStatus] = useState<Map<number, boolean>>(
    () => new Map(sharedStatus),
  );
  const [connected, setConnected] = useState(sharedConnected);
  /* Tunggu AuthProvider selesai boot (termasuk re-login guest diam-diam)
     sebelum membuka WS, agar token belum ada saat mount tidak membuat
     WS mati tanpa pernah dimulai. */
  const { loading: authLoading, logout } = useAuth();

  /* Simpan logout terbaru untuk endSharedSession di level modul.
     P0 code-review 2026-11-18: dependency [logout], sebelumnya tanpa
     array, effect berjalan di setiap render setiap komponen pemakai. */
  useEffect(() => {
    sharedLogout = logout;
  }, [logout]);

  useEffect(() => {
    if (authLoading) return;
    const listener: StatusListener = (s, c) => {
      setStatus(s);
      setConnected(c);
    };
    listeners.add(listener);
    /* Subscriber baru langsung menerima status terakhir, tanpa
       menunggu snapshot berikutnya. */
    listener(new Map(sharedStatus), sharedConnected);
    startShared();
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) stopShared();
    };
  }, [authLoading]);

  return { status, connected };
}
