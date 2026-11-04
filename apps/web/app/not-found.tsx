"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "../lib/auth";

/* Halaman 404: link salah/typo langsung diarahkan.
   - Belum login -> /login
   - Sudah login -> /live (halaman utama) */
export default function NotFound() {
  const router = useRouter();
  const { user, loading } = useAuth();

  useEffect(() => {
    if (loading) return;
    if (user) {
      router.replace("/live");
    } else {
      router.replace("/login");
    }
  }, [user, loading, router]);

  return (
    <div className="flex min-h-dvh items-center justify-center bg-ink-950">
      <div className="text-center">
        <p className="text-lg font-semibold text-white">Mengalihkan…</p>
        <p className="mt-2 text-sm text-slate-400">
          Halaman tidak ditemukan.
        </p>
      </div>
    </div>
  );
}
