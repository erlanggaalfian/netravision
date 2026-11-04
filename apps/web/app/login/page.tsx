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
      <rect x="1.5" y="1.5" width="21" height="21" rx="6" fill="var(--nv-accent-600)" />
      <circle cx="12" cy="12" r="5.5" stroke="#fff" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="1.8" fill="#fff" />
    </svg>
  );
}

/* Input gaya NetBackup: border jelas, radius 8px, 16px (anti-zoom iOS).
   Token ink dan accent adaptif di kedua tema via globals.css. */
const inputCls =
  "w-full rounded-lg border border-ink-700 bg-ink-950 px-4 py-3 text-[16px] text-white placeholder:text-slate-400 outline-none transition-all duration-150 ease-out focus:border-accent-400 focus:ring-4 focus:ring-accent-500/15";

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
      await loginGuest("");
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
    <main className="flex min-h-dvh flex-col bg-ink-950">
      {/* Pita biru di atas ala header NetBackup */}
      <div className="bg-gradient-to-b from-accent-400 to-accent-600">
        <div className="h-32 sm:h-40" aria-hidden />
      </div>

      <div className="mx-auto w-full max-w-sm flex-1 px-5">
        {/* Kartu login putih: radius 16px, border + shadow jelas */}
        <div className="-mt-16 rounded-2xl border border-ink-700 bg-ink-900 p-6 shadow-[0_16px_40px_rgba(2,132,199,0.18)] sm:-mt-20 sm:p-8">
          <div className="mb-6 flex flex-col items-center gap-3">
            <LensMark className="h-14 w-14" />
            <p className="text-xl font-bold tracking-tight text-white">
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
            <div className="space-y-3 pt-1">
              <button
                type="submit"
                disabled={busy}
                className="min-h-[48px] w-full cursor-pointer rounded-lg bg-accent-500 px-4 text-[16px] font-semibold text-onaccent transition-all duration-150 ease-out hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
              >
                {busy ? "Memeriksa…" : "Masuk"}
              </button>
              <button
                type="button"
                onClick={onGuest}
                disabled={busy}
                className="min-h-[48px] w-full cursor-pointer rounded-lg border border-ink-700 bg-transparent px-4 text-sm font-semibold text-slate-300 transition-all duration-150 ease-out hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
              >
                Guest login
              </button>
            </div>
          </form>
        </div>

        <p className="mt-8 text-center text-xs text-slate-400">
          © 2026 NetraVision
        </p>
      </div>
    </main>
  );
}
