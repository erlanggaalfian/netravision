"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button, ErrorBox, TextInput } from "../../components/ui";

/* Marka lensa — motif produk, digambar murni SVG. */
function LensMark({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="1.5" y="1.5" width="21" height="21" rx="6" fill="#2563eb" />
      <circle cx="12" cy="12" r="5.5" stroke="#fff" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="1.8" fill="#fff" />
    </svg>
  );
}

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <LensMark className={compact ? "h-9 w-9" : "h-11 w-11"} />
      <div>
        <p className="font-bold tracking-tight text-white">NetraVision</p>
        {!compact && (
          <p className="text-xs text-slate-400">Sistem Pemantauan CCTV</p>
        )}
      </div>
    </div>
  );
}

/* Motif grid tile kamera — abstrak, murni CSS. Satu tile "live". */
function TileMotif() {
  const tiles = [0, 1, 2, 3, 4, 5];
  return (
    <div
      className="grid grid-cols-3 gap-2.5"
      aria-hidden
      role="presentation"
    >
      {tiles.map((i) => (
        <div
          key={i}
          className={`relative aspect-[4/3] rounded-xl border border-white/8 ${
            i === 1 ? "bg-ink-700" : "bg-ink-850"
          }`}
        >
          {i === 1 && (
            <span className="absolute left-2 top-2 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-bad-400" />
              <span className="text-[9px] font-bold tracking-widest text-slate-300">
                LIVE
              </span>
            </span>
          )}
          {i === 4 && (
            <span className="absolute bottom-2 left-2 right-2 h-1 rounded-full bg-white/10">
              <span className="block h-full w-2/3 rounded-full bg-accent-400" />
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

const SPECS: Array<[string, string]> = [
  ["Latensi siaran", "WebRTC sub-detik"],
  ["Merek kamera", "12 — resolver cerdas"],
  ["Instalasi", "PWA, di HP maupun desktop"],
];

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
    <main className="flex min-h-dvh bg-ink-950">
      {/* Panel kiri — desktop */}
      <aside className="hidden w-[44%] flex-col justify-between border-r border-white/8 bg-ink-900 p-10 lg:flex xl:p-14">
        <Logo />
        <div>
          <h1 className="max-w-md text-[34px] font-bold leading-[1.1] tracking-tight text-white">
            Semua kamera, satu layar kendali.
          </h1>
          <p className="mt-3 max-w-md text-[15px] leading-relaxed text-slate-400">
            Pantau siaran langsung, putar ulang rekaman, dan kelola ratusan
            kamera dari berbagai merek — dari ponsel maupun desktop.
          </p>
          <div className="mt-8 max-w-md">
            <TileMotif />
          </div>
          <dl className="mt-8 max-w-md">
            {SPECS.map(([k, v]) => (
              <div
                key={k}
                className="flex items-baseline justify-between gap-4 border-t border-white/8 py-2.5"
              >
                <dt className="text-sm text-slate-500">{k}</dt>
                <dd className="text-sm font-semibold text-slate-100">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        <p className="text-xs text-slate-600">© 2026 NetraVision</p>
      </aside>

      {/* Panel kanan — form */}
      <section className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo compact />
          </div>

          <div className="rounded-2xl border border-white/8 bg-ink-900 p-6 shadow-[0_2px_8px_rgba(0,0,0,0.4)] sm:p-7">
            <div className="mb-6 grid grid-cols-2 rounded-xl bg-ink-950 p-1">
              {(["masuk", "tamu"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    setTab(t);
                    setError("");
                  }}
                  className={`min-h-[44px] cursor-pointer rounded-lg text-sm font-semibold transition-all duration-150 ease-out ${
                    tab === t
                      ? "bg-ink-700 text-white shadow-[0_1px_2px_rgba(0,0,0,0.4)]"
                      : "text-slate-500 hover:text-slate-200"
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
                <div className="pt-1">
                  <Button type="submit" disabled={busy} className="w-full">
                    {busy ? "Memeriksa…" : "Masuk"}
                  </Button>
                </div>
              </form>
            ) : (
              <form onSubmit={onGuest} className="space-y-4">
                <div>
                  <label
                    htmlFor="guest-code"
                    className="mb-1.5 block text-sm font-medium text-slate-300"
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
                  <p className="mt-1.5 text-xs text-slate-500">
                    Minta kode akses tamu kepada administrator.
                  </p>
                </div>
                <div className="pt-1">
                  <Button type="submit" disabled={busy} className="w-full">
                    {busy ? "Memeriksa…" : "Masuk sebagai Tamu"}
                  </Button>
                </div>
              </form>
            )}
          </div>

          <p className="mt-6 text-center text-xs text-slate-600">
            Akses konsol ini tercatat untuk keamanan.
          </p>
        </div>
      </section>
    </main>
  );
}
