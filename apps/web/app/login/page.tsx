"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ErrorBox } from "../../components/ui";

/* Marka lensa — digambar murni SVG. */
function LensMark({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="1.5" y="1.5" width="21" height="21" rx="6" fill="url(#lensGrad)" />
      <defs>
        <linearGradient id="lensGrad" x1="1.5" y1="1.5" x2="22.5" y2="22.5">
          <stop stopColor="var(--nv-accent-500)" />
          <stop offset="1" stopColor="var(--nv-accent-600)" />
        </linearGradient>
      </defs>
      <circle cx="12" cy="12" r="5.5" stroke="#fff" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="1.8" fill="#fff" />
    </svg>
  );
}

/* Input modern: radius 14px, 16px (anti-zoom iOS), focus glow. */
const inputCls =
  "w-full rounded-xl bg-ink-800 px-4 py-3 text-[16px] text-slate-100 placeholder:text-slate-400 shadow-sm outline-none transition-all duration-150 ease-out focus:ring-2 focus:ring-accent-500/30";

export default function LoginPage() {
  const { user, loading, login, loginGuest } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  /* Jangan memanggil router saat render (side effect di body render). */
  useEffect(() => {
    if (!loading && user) router.replace("/live");
  }, [loading, user, router]);
  if (!loading && user) return null;

  async function onLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username.trim(), password);
      router.push("/live");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal masuk. Coba lagi.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function onGuest() {
    setError("");
    setBusy(true);
    try {
      await loginGuest();
      router.push("/live");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal masuk. Coba lagi.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-ink-950 px-5 py-8">
      {/* Kartu login terpusat: logo di dalam, tanpa pita, tanpa copy marketing */}
      <div className="w-full max-w-sm">
        <div className="nv-panel-modern p-6 sm:p-8">
          <div className="mb-7 flex flex-col items-center gap-3">
            <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-b from-accent-500 to-accent-600 shadow-[0_8px_24px_-6px_var(--nv-accent-500)]">
              <LensMark className="h-10 w-10" />
            </span>
            <p className="text-[22px] font-extrabold tracking-tight text-slate-100">
              NetraVision
            </p>
          </div>
          {error && (
            <div className="mb-4">
              <ErrorBox message={error} />
            </div>
          )}

          <form onSubmit={onLogin} className="space-y-4">
            <div>
              <label
                htmlFor="username"
                className="mb-1.5 block text-sm font-medium text-slate-300"
              >
                Nama pengguna
              </label>
              <input
                id="username"
                autoComplete="username"
                placeholder="nama pengguna"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                className={inputCls}
              />
            </div>
            <div>
              <label
                htmlFor="password"
                className="mb-1.5 block text-sm font-medium text-slate-300"
              >
                Kata sandi
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className={inputCls}
              />
            </div>
            <div className="space-y-3 pt-2">
              <button
                type="submit"
                disabled={busy}
                className="min-h-[48px] w-full cursor-pointer rounded-xl bg-gradient-to-b from-accent-500 to-accent-600 px-4 text-[16px] font-semibold text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-500),inset_0_1px_0_rgba(255,255,255,0.2)] transition-all duration-150 ease-out hover:from-accent-400 hover:to-accent-500 hover:shadow-[0_6px_20px_-4px_var(--nv-accent-500),inset_0_1px_0_rgba(255,255,255,0.25)] disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
              >
                {busy ? "Memeriksa…" : "Masuk"}
              </button>
              <button
                type="button"
                onClick={onGuest}
                disabled={busy}
                className="min-h-[48px] w-full cursor-pointer rounded-xl bg-ink-800 px-4 text-sm font-semibold text-slate-300 shadow-sm transition-all duration-150 ease-out hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
              >
                Guest login
              </button>
            </div>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          © 2026 NetraVision
        </p>
      </div>
    </main>
  );
}
