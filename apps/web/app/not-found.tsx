"use client";

import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "../lib/auth";

/* Halaman 404 sungguhan: tampilkan alamat yang diminta dan tombol
   kembali, jangan diam-diam mengalihkan ke /live atau /login. */
export default function NotFound() {
  const router = useRouter();
  const pathname = usePathname();
  const { user } = useAuth();

  return (
    <div className="flex min-h-dvh items-center justify-center bg-ink-950 px-5">
      <div className="text-center">
        <p className="text-6xl font-extrabold tracking-tight text-white">404</p>
        <p className="mt-3 text-lg font-semibold text-white">
          Halaman tidak ditemukan
        </p>
        <p className="mx-auto mt-2 max-w-sm break-all text-sm leading-relaxed text-slate-400">
          {pathname
            ? `Alamat ${pathname} tidak ada di NetraVision.`
            : "Alamat yang diminta tidak ada di NetraVision."}
        </p>
        <div className="mx-auto mt-6 flex w-full max-w-xs flex-col gap-2.5">
          <button
            type="button"
            onClick={() => router.replace(user ? "/live" : "/login")}
            className="min-h-[48px] w-full cursor-pointer rounded-xl bg-gradient-to-b from-accent-500 to-accent-600 px-4 text-[16px] font-semibold text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-500),inset_0_1px_0_rgba(255,255,255,0.2)] transition-all duration-150 ease-out hover:from-accent-400 hover:to-accent-500 active:scale-[0.98]"
          >
            {user ? "Kembali ke Live" : "Kembali ke Login"}
          </button>
          <button
            type="button"
            onClick={() => router.back()}
            className="min-h-[48px] w-full cursor-pointer rounded-xl bg-ink-800 px-4 text-sm font-semibold text-slate-300 shadow-sm transition-all duration-150 ease-out hover:bg-ink-700 active:scale-[0.98]"
          >
            Kembali ke halaman sebelumnya
          </button>
        </div>
      </div>
    </div>
  );
}
