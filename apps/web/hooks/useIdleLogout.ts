"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "../lib/auth";

/* Batas diam sebelum sesi dianggap selesai dan pengguna diminta login
   lagi: 1 jam tanpa gerakan. Aktivitas apa pun (gerak mouse, klik,
   ketik, sentuh, scroll) mengatur ulang hitungan. Selama masih ada
   pengoperasian, sesi tidak pernah putus karena diam. Aktivitas di
   tab lain ikut dihitung lewat localStorage supaya pengguna yang
   aktif di tab sebelah tidak tiba-tiba dikeluarkan di tab ini. */
const IDLE_TIMEOUT_MS = 60 * 60 * 1000; // 1 jam
const LAST_ACTIVITY_KEY = "nv_last_activity";
const ACTIVITY_EVENTS = [
  "mousemove",
  "mousedown",
  "keydown",
  "scroll",
  "touchstart",
  "wheel",
  "pointerdown",
] as const;
/* Atur ulang timer paling sering tiap 30 detik supaya mousemove yang
   deras tidak membuat timer baru terus-menerus. */
const RESET_THROTTLE_MS = 30 * 1000;

export function useIdleLogout() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const loggedOutRef = useRef(false);

  useEffect(() => {
    if (loading || !user) return;
    /* Tidak ada sesi di halaman login; jangan pasang pengawas di sana. */
    if (pathname === "/login") return;
    loggedOutRef.current = false;

    let timer: ReturnType<typeof setTimeout> | null = null;
    let lastReset = 0;

    const markActivity = (ts: number) => {
      try {
        localStorage.setItem(LAST_ACTIVITY_KEY, String(ts));
      } catch {
        /* abaikan: penyimpanan lokal tidak tersedia */
      }
    };

    const schedule = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        if (loggedOutRef.current) return;
        loggedOutRef.current = true;
        await logout();
        if (window.location.pathname !== "/login") {
          router.push("/login");
        }
      }, IDLE_TIMEOUT_MS);
    };

    const onActivity = () => {
      const now = Date.now();
      if (now - lastReset < RESET_THROTTLE_MS) return;
      lastReset = now;
      markActivity(now);
      schedule();
    };

    /* Aktivitas di tab lain (storage event) ikut mengatur ulang timer
       di tab ini. */
    const onStorage = (e: StorageEvent) => {
      if (e.key !== LAST_ACTIVITY_KEY || !e.newValue) return;
      const ts = Number(e.newValue);
      if (!Number.isFinite(ts)) return;
      lastReset = ts;
      schedule();
    };

    /* Mulai hitungan dari aktivitas terakhir yang tercatat (bila ada),
       supaya tab yang baru dibuka tidak langsung menghitung dari nol
       padahal pengguna baru saja aktif di tab lain. */
    let initialDelay = IDLE_TIMEOUT_MS;
    try {
      const prev = Number(localStorage.getItem(LAST_ACTIVITY_KEY) ?? "");
      if (Number.isFinite(prev) && prev > 0) {
        initialDelay = Math.max(
          0,
          IDLE_TIMEOUT_MS - (Date.now() - prev),
        );
      }
    } catch {
      /* abaikan */
    }
    markActivity(Date.now());
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      if (loggedOutRef.current) return;
      loggedOutRef.current = true;
      await logout();
      if (window.location.pathname !== "/login") {
        router.push("/login");
      }
    }, initialDelay);

    for (const evt of ACTIVITY_EVENTS) {
      window.addEventListener(evt, onActivity, { passive: true });
    }
    window.addEventListener("storage", onStorage);
    return () => {
      if (timer) clearTimeout(timer);
      for (const evt of ACTIVITY_EVENTS) {
        window.removeEventListener(evt, onActivity);
      }
      window.removeEventListener("storage", onStorage);
    };
  }, [user, loading, logout, router, pathname]);
}
