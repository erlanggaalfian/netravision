"use client";

import { useEffect } from "react";

/* P0 code-review 2026-11-18: error boundary per-route (App Router).
   Sebelumnya tidak ada error.tsx di seluruh app/: bila satu komponen
   (mis. CameraTile atau halaman admin) melempar, seluruh route unmount
   dan pengguna melihat layar putih. File ini menampilkan fallback
   dengan tombol coba lagi (reset) — bukan layar putih. */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    /* Catat untuk diagnosis; jangan tampilkan detail teknis ke pengguna. */
    // eslint-disable-next-line no-console
    console.error("NetraVision error boundary:", error);
  }, [error]);

  return (
    <div className="flex min-h-dvh items-center justify-center bg-ink-950 px-5">
      <div className="text-center">
        <p className="text-6xl font-extrabold tracking-tight text-white">!</p>
        <p className="mt-3 text-lg font-semibold text-white">
          Terjadi kesalahan
        </p>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate-400">
          Halaman ini gagal dimuat. Coba muat ulang — data kamera dan
          pengaturan Anda tidak hilang.
        </p>
        <div className="mx-auto mt-6 flex w-full max-w-xs flex-col gap-2.5">
          <button
            type="button"
            onClick={reset}
            className="min-h-[48px] w-full cursor-pointer rounded-xl bg-gradient-to-b from-accent-500 to-accent-600 px-4 text-[16px] font-semibold text-onaccent shadow-sm transition-all duration-150 ease-out hover:from-accent-400 hover:to-accent-500 active:scale-[0.98]"
          >
            Coba lagi
          </button>
          <button
            type="button"
            onClick={() => {
              window.location.href = "/live";
            }}
            className="min-h-[48px] w-full cursor-pointer rounded-xl bg-ink-800 px-4 text-sm font-semibold text-slate-300 shadow-sm transition-all duration-150 ease-out hover:bg-ink-700 active:scale-[0.98]"
          >
            Kembali ke Live
          </button>
        </div>
      </div>
    </div>
  );
}
