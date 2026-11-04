"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button, ErrorBox, TextInput } from "../../components/ui";

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
    <main className="flex min-h-dvh flex-col items-center justify-center bg-ink-950 px-5 py-10">
      <div className="w-full max-w-sm">
        <div className="rounded-2xl border border-white/8 bg-ink-900 p-6 shadow-[0_2px_12px_rgba(0,0,0,0.18)] sm:p-7">
          <div className="mb-6 flex flex-col items-center gap-3">
            <LensMark className="h-12 w-12" />
            <p className="text-lg font-bold tracking-tight text-white">
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
              <TextInput
                id="username"
                autoComplete="username"
                placeholder="nama pengguna"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div>
              <label
                htmlFor="password"
                className="mb-1.5 block text-sm font-medium text-slate-300"
              >
                Kata sandi
              </label>
              <TextInput
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <div className="pt-1 space-y-3">
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "Memeriksa…" : "Masuk"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={onGuest}
                disabled={busy}
                className="w-full"
              >
                Guest login
              </Button>
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
