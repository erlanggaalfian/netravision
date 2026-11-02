"use client";

import { useEffect } from "react";

/* Daftarkan service worker PWA (diabaikan diam-diam bila tak didukung). */
export function SWRegister() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* abaikan — PWA opsional */
      });
    }
  }, []);
  return null;
}
