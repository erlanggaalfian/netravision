"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button, ErrorBox, TextInput } from "../../components/ui";

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={`flex items-center justify-center rounded-xl bg-gradient-to-br from-accent-400 to-accent-600 font-bold text-white shadow-lg shadow-accent-600/30 ${
          compact ? "h-9 w-9 text-lg" : "h-12 w-12 text-2xl"
        }`}
      >
        ◉
      </div>
      <div>
        <p className="font-bold tracking-tight text-white">NetraVision</p>
        {!compact && (
          <p className="text-xs text-slate-400">Sistem Pemantauan CCTV</p>
        )}
      </div>
    </div>
  );
}

export default function LoginPage() {
  const { user, loading, login, loginGuest } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<"masuk" | "tamu">("masuk");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!loading && user) {
    router.replace("/live");
    return null;
  }

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

  async function onGuest(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await loginGuest(code.trim());
      router.push("/live");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Kode tamu tidak valid.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen bg-ink-950">
      {/* Panel kiri — desktop */}
      <aside className="relative hidden w-[44%] flex-col justify-between overflow-hidden bg-ink-900 p-10 lg:flex">
        <div
          className="pointer-events-none absolute inset-0"
          aria-hidden
          style={{
            background:
              "radial-gradient(60% 50% at 20% 10%, rgba(59,130,246,0.25), transparent 70%), radial-gradient(50% 40% at 90% 90%, rgba(37,99,235,0.18), transparent 70%)",
          }}
        />
        <div className="relative">
          <Logo />
        </div>
        <div className="relative">
          <h1 className="max-w-md text-3xl font-bold leading-tight tracking-tight text-white">
            Semua kamera, satu layar kendali.
          </h1>
          <p className="mt-3 max-w-md text-sm leading-relaxed text-slate-400">
            Pantau siaran langsung, putar ulang rekaman, dan kelola ratusan
            kamera dari berbagai merek — dari ponsel maupun desktop.
          </p>
          <div className="mt-8 flex gap-6 text-sm">
            <div>
              <p className="text-lg font-bold text-accent-300">WebRTC</p>
              <p className="text-xs text-slate-500">Jeda sub-detik</p>
            </div>
            <div>
              <p className="text-lg font-bold text-accent-300">12 merek</p>
              <p className="text-xs text-slate-500">Resolver cerdas</p>
            </div>
            <div>
              <p className="text-lg font-bold text-accent-300">PWA</p>
              <p className="text-xs text-slate-500">Install di HP</p>
            </div>
          </div>
        </div>
        <p className="relative text-xs text-slate-600">
          © 2026 NetraVision
        </p>
      </aside>

      {/* Panel kanan — form */}
      <section className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo compact />
          </div>

          <div className="mb-6 grid grid-cols-2 rounded-xl border border-ink-700 bg-ink-900 p-1">
            {(["masuk", "tamu"] as const).map((t) => (
              <button
                key={t}
                onClick={() => {
                  setTab(t);
                  setError("");
                }}
                className={`min-h-[44px] rounded-lg text-sm font-medium transition-colors ${
                  tab === t
                    ? "bg-ink-700 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {t === "masuk" ? "Masuk" : "Tamu"}
              </button>
            ))}
          </div>

          {error && (
            <div className="mb-4">
              <ErrorBox message={error} />
            </div>
          )}

          {tab === "masuk" ? (
            <form onSubmit={onLogin} className="space-y-4">
              <div>
                <label
                  htmlFor="username"
                  className="mb-1 block text-sm font-medium text-slate-300"
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
                  className="mb-1 block text-sm font-medium text-slate-300"
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
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "Memeriksa…" : "Masuk"}
              </Button>
            </form>
          ) : (
            <form onSubmit={onGuest} className="space-y-4">
              <div>
                <label
                  htmlFor="guest-code"
                  className="mb-1 block text-sm font-medium text-slate-300"
                >
                  Kode tamu
                </label>
                <TextInput
                  id="guest-code"
                  autoComplete="off"
                  placeholder="kode akses tamu"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  required
                />
                <p className="mt-1 text-xs text-slate-500">
                  Minta kode akses tamu kepada administrator.
                </p>
              </div>
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "Memeriksa…" : "Masuk sebagai Tamu"}
              </Button>
            </form>
          )}
        </div>
      </section>
    </main>
  );
}
