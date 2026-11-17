"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "../lib/auth";
import { isGuestSession } from "../lib/api";

/* Batas diam sebelum sesi dianggap selesai dan pengguna diminta login
   lagi: 1 jam tanpa gerakan. Aktivitas apa pun (gerak mouse, klik,
   ketik, sentuh, scroll) mengatur ulang hitungan. Selama masih ada
   pengoperasian, sesi tidak pernah putus karena diam. Aktivitas di
   tab lain ikut dihitung lewat localStorage supaya pengguna yang
   aktif di tab sebelah tidak tiba-tiba dikeluarkan di tab ini. */
const IDLE_TIMEOUT_MS = 60 * 60 * 1000; // 1 jam
/* F3.6: peringatan sebelum logout paksa, dengan tombol "Tetap masuk".
   90 detik, di tengah rentang 60-120 detik yang diminta audit. */
const WARNING_MS = 90 * 1000;
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
/* Video yang sedang diputar diperiksa berkala sebagai aktivitas. */
const PLAYING_CHECK_MS = 60 * 1000;

export function useIdleLogout() {
  const { user, loading, logout, loginGuest } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const loggedOutRef = useRef(false);
  /* F3.6: status peringatan, dirender AppShell sebagai banner dengan
     tombol "Tetap masuk". */
  const [idleWarning, setIdleWarning] = useState(false);
  const [idleSecondsLeft, setIdleSecondsLeft] = useState(0);
  const warningRef = useRef(false);
  const rescheduleRef = useRef<(() => void) | null>(null);

  /* Tombol "Tetap masuk": sembunyikan peringatan dan mulai hitungan
     diam dari awal. */
  const stayLoggedIn = useCallback(() => {
    setIdleWarning(false);
    warningRef.current = false;
    rescheduleRef.current?.();
  }, []);

  useEffect(() => {
    if (loading || !user) return;
    /* Tidak ada sesi di halaman login; jangan pasang pengawas di sana. */
    if (pathname === "/login") return;
    loggedOutRef.current = false;

    let warningTimer: ReturnType<typeof setTimeout> | null = null;
    let logoutTimer: ReturnType<typeof setTimeout> | null = null;
    let countdown: ReturnType<typeof setInterval> | null = null;
    let lastReset = 0;
    /* F3.6: sesi guest tidak pernah dikeluarkan paksa ke /login.
       Saat batas diam tercapai, guest login ulang diam-diam dan
       hitungan dimulai lagi; hanya bila itu gagal, logout paksa. */
    const isGuest = isGuestSession() || user.role === "guest";

    const clearTimers = () => {
      if (warningTimer) clearTimeout(warningTimer);
      if (logoutTimer) clearTimeout(logoutTimer);
      if (countdown) clearInterval(countdown);
      warningTimer = null;
      logoutTimer = null;
      countdown = null;
    };

    const markActivity = (ts: number) => {
      try {
        localStorage.setItem(LAST_ACTIVITY_KEY, String(ts));
      } catch {
        /* abaikan: penyimpanan lokal tidak tersedia */
      }
    };

    const doLogout = async () => {
      if (loggedOutRef.current) return;
      loggedOutRef.current = true;
      setIdleWarning(false);
      warningRef.current = false;
      await logout();
      if (window.location.pathname !== "/login") {
        router.push("/login");
      }
    };

    const doGuestRenewal = async () => {
      if (loggedOutRef.current) return;
      try {
        await loginGuest();
        schedule();
      } catch {
        await doLogout();
      }
    };

    const showWarning = () => {
      setIdleSecondsLeft(Math.ceil(WARNING_MS / 1000));
      setIdleWarning(true);
      warningRef.current = true;
      countdown = setInterval(() => {
        setIdleSecondsLeft((s) => Math.max(0, s - 1));
      }, 1000);
      logoutTimer = setTimeout(() => {
        void doLogout();
      }, WARNING_MS);
    };

    const schedule = (delay: number = IDLE_TIMEOUT_MS) => {
      clearTimers();
      setIdleWarning(false);
      warningRef.current = false;
      if (isGuest) {
        warningTimer = setTimeout(() => {
          void doGuestRenewal();
        }, delay);
        return;
      }
      const warnIn = Math.max(0, delay - WARNING_MS);
      warningTimer = setTimeout(showWarning, warnIn);
    };
    rescheduleRef.current = () => {
      const now = Date.now();
      lastReset = now;
      markActivity(now);
      schedule();
    };

    const onActivity = () => {
      /* Selama peringatan tampil, aktivitas apa pun langsung dihitung
         sebagai "Tetap masuk", tanpa menunggu throttle. */
      if (warningRef.current) {
        stayLoggedIn();
        return;
      }
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

    /* F3.6: video yang sedang diputar dihitung sebagai aktivitas,
       supaya menonton pasif (mis. Live fullscreen) tidak dihitung
       diam. Event play/playing ditangkap di fase capture karena
       event itu tidak bubble. */
    const onVideoPlay = () => {
      onActivity();
    };
    const checkPlayingVideos = () => {
      try {
        const videos = document.querySelectorAll("video");
        for (const v of Array.from(videos)) {
          if (!v.paused && !v.ended && v.readyState >= 2) {
            onActivity();
            return;
          }
        }
      } catch {
        /* abaikan */
      }
    };
    const playingCheck = setInterval(checkPlayingVideos, PLAYING_CHECK_MS);

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
    schedule(initialDelay);

    for (const evt of ACTIVITY_EVENTS) {
      window.addEventListener(evt, onActivity, { passive: true });
    }
    window.addEventListener("play", onVideoPlay, true);
    window.addEventListener("playing", onVideoPlay, true);
    window.addEventListener("storage", onStorage);
    return () => {
      clearTimers();
      clearInterval(playingCheck);
      rescheduleRef.current = null;
      for (const evt of ACTIVITY_EVENTS) {
        window.removeEventListener(evt, onActivity);
      }
      window.removeEventListener("play", onVideoPlay, true);
      window.removeEventListener("playing", onVideoPlay, true);
      window.removeEventListener("storage", onStorage);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, loading, logout, loginGuest, router, pathname]);

  return { idleWarning, idleSecondsLeft, stayLoggedIn };
}
