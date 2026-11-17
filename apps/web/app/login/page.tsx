"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ErrorBox, Spinner } from "../../components/ui";

/* Input modern: radius 14px, 16px (anti-zoom iOS), focus glow. */
const inputCls =
  "w-full rounded-xl bg-ink-800 px-4 py-3 text-[16px] text-slate-100 placeholder:text-slate-400 shadow-sm outline-none transition-all duration-150 ease-out focus:ring-2 focus:ring-accent-500/30";

/* Versi APK terbaru yang tersedia di /netravision.apk. Perbarui tiap
   kali APK baru dirilis. Aplikasi Android menyisipkan versinya di
   User-Agent ("NetraVision/<versi>") supaya halaman ini bisa tahu
   apakah pengunjung memakai aplikasi dan versinya sudah terbaru. */
const LATEST_APK_VERSION = "1.0.2";
const LATEST_APK_SIZE = "275 KB";

/* Bandingkan dua versi "x.y.z": -1 bila a<b, 0 bila sama, 1 bila a>b. */
function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((n) => parseInt(n, 10) || 0);
  const pb = b.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}

export default function LoginPage() {
  const { user, loading, login, loginGuest } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /* F3.5: pesan bila pengguna diarahkan ke sini karena sesi berakhir
     (WebSocket ditolak berulang karena refresh token mati). Dibaca
     dari query ?session=expired dan penanda sessionStorage, supaya
     pesan tetap tampil bila query hilang saat navigasi. */
  const [sessionExpired, setSessionExpired] = useState(false);
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const flagged =
        params.get("session") === "expired" ||
        sessionStorage.getItem("nv_session_expired") === "1";
      if (flagged) {
        setSessionExpired(true);
        sessionStorage.removeItem("nv_session_expired");
      }
    } catch {
      /* abaikan */
    }
  }, []);
  /* Tombol Download APK: tampil bila pengunjung memakai browser (belum
     pasang aplikasi) atau memakai aplikasi yang versinya lebih lama dari
     terbaru. Sembunyi bila aplikasi sudah versi terbaru. Default tampil
     (browser), dikoreksi setelah baca User-Agent di sisi klien. */
  const [showApk, setShowApk] = useState(true);
  const [apkInApp, setApkInApp] = useState(false);

  useEffect(() => {
    const m = navigator.userAgent.match(/NetraVision\/([0-9]+\.[0-9]+\.[0-9]+)/);
    if (!m) return;
    setApkInApp(true);
    if (compareVersions(m[1], LATEST_APK_VERSION) >= 0) setShowApk(false);
  }, []);
  /* Blokir 429: timestamp (ms) kapan blokir berakhir, dari header
     Retry-After. Selama blokir, tombol Masuk/Guest dinonaktifkan dan
     menampilkan hitung mundur. */
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const retryIn = blockedUntil
    ? Math.max(0, Math.ceil((blockedUntil - now) / 1000))
    : 0;
  const blocked = retryIn > 0;

  useEffect(() => {
    if (!blockedUntil) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [blockedUntil]);

  useEffect(() => {
    if (blockedUntil && Date.now() >= blockedUntil) setBlockedUntil(null);
  }, [now, blockedUntil]);
  /* Tombol Guest tampil bila login guest aktif. null = belum tahu,
     tampilkan dulu (perilaku lama) sampai jawaban API datang. */
  const [guestEnabled, setGuestEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .get<{ enabled: boolean }>("/auth/guest-enabled")
      .then((d) => {
        if (alive) setGuestEnabled(d.enabled);
      })
      .catch(() => {
        /* gagal baca: biarkan tombol tampil, percobaan login yang
           akan memberi tahu bila guest memang nonaktif. */
      });
    return () => {
      alive = false;
    };
  }, []);

  /* Jangan memanggil router saat render (side effect di body render). */
  useEffect(() => {
    if (!loading && user) router.replace("/live");
  }, [loading, user, router]);
  /* Selama status auth masih dimuat, tampilkan Spinner saja: formulir
     tidak boleh sempat tampil dan ditekan sebelum redirect. */
  if (loading) {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center bg-ink-950 px-5 py-8">
        <Spinner />
      </main>
    );
  }
  if (user) return null;

  async function onLogin(e: React.FormEvent) {
    e.preventDefault();
    if (blocked) return;
    setError("");
    setBusy(true);
    try {
      await login(username.trim(), password);
      router.push("/live");
    } catch (err) {
      if (err instanceof ApiError && err.retryAfter != null) {
        setBlockedUntil(Date.now() + err.retryAfter * 1000);
        setError(`${err.message} Coba lagi dalam ${err.retryAfter} detik.`);
      } else {
        setError(
          err instanceof ApiError ? err.message : "Gagal masuk. Coba lagi.",
        );
      }
    } finally {
      setBusy(false);
    }
  }

  async function onGuest() {
    if (blocked) return;
    setError("");
    setBusy(true);
    try {
      await loginGuest();
      router.push("/live");
    } catch (err) {
      if (err instanceof ApiError && err.retryAfter != null) {
        setBlockedUntil(Date.now() + err.retryAfter * 1000);
        setError(`${err.message} Coba lagi dalam ${err.retryAfter} detik.`);
      } else {
        setError(
          err instanceof ApiError ? err.message : "Gagal masuk. Coba lagi.",
        );
      }
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
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {/* F5.11: turunan kecil logo-96.webp (4,1 KB), bukan logo.png 174 KB. */}
            <img
              src="/icons/logo-96.webp"
              alt="Logo NetraVision"
              width={80}
              height={80}
              className="h-20 w-20 object-contain"
            />
            <p className="text-[22px] font-extrabold tracking-tight text-slate-100">
              NetraVision
            </p>
          </div>
          {sessionExpired && (
            <div className="mb-4 rounded-xl bg-warn-500/10 px-4 py-3 text-sm text-warn-200 ring-1 ring-warn-500/30">
              Sesi Anda telah berakhir. Silakan masuk lagi.
            </div>
          )}
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
                disabled={busy || blocked}
                className="min-h-[48px] w-full cursor-pointer rounded-xl bg-gradient-to-b from-accent-500 to-accent-600 px-4 text-[16px] font-semibold text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-500),inset_0_1px_0_rgba(255,255,255,0.2)] transition-all duration-150 ease-out hover:from-accent-400 hover:to-accent-500 hover:shadow-[0_6px_20px_-4px_var(--nv-accent-500),inset_0_1px_0_rgba(255,255,255,0.25)] disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
              >
                {busy ? "Memeriksa…" : blocked ? `Tunggu ${retryIn} detik` : "Masuk"}
              </button>
              {/* Tombol Guest hanya bila login guest aktif. */}
              {guestEnabled !== false && (
                <button
                  type="button"
                  onClick={onGuest}
                  disabled={busy || blocked}
                  className="min-h-[48px] w-full cursor-pointer rounded-xl bg-ink-800 px-4 text-sm font-semibold text-slate-300 shadow-sm transition-all duration-150 ease-out hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
                >
                  Guest login
                </button>
              )}
              {/* Unduh aplikasi Android (APK). Hanya tampil di HP, dan
                  hanya bila ada update (atau belum pasang aplikasi). */}
              {showApk && (
              <a
                href="/netravision.apk"
                download="netravision.apk"
                className="flex min-h-[48px] w-full cursor-pointer flex-col items-center justify-center rounded-xl bg-gradient-to-b from-accent-500 to-accent-600 px-4 py-2 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-500),inset_0_1px_0_rgba(255,255,255,0.2)] transition-all duration-150 ease-out hover:from-accent-400 hover:to-accent-500 hover:shadow-[0_6px_20px_-4px_var(--nv-accent-500),inset_0_1px_0_rgba(255,255,255,0.25)] active:scale-[0.98] md:hidden"
              >
                <span className="flex items-center gap-2 text-[16px] font-semibold">
                  <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2.2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                  {apkInApp ? "Update APK" : "Download APK"}
                </span>
                <span className="text-xs font-medium opacity-80">
                  v{LATEST_APK_VERSION} • {LATEST_APK_SIZE} • Android
                </span>
              </a>
              )}
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
