"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "../../lib/api";
import { playWhep, stopWhep } from "../../lib/whep";
import { AdBanner } from "../../components/AdBanner";
import { Button } from "../../components/ui";
import type { AdConfig } from "../../lib/types";

/* Halaman embed PUBLIK (tanpa login) untuk pihak ketiga.
   Kunci via ?key=, kamera tunggal opsional via ?camera=<id>. */

type Phase = "loading" | "unavailable" | "error" | "ready";

interface EmbedCamera {
  id: number;
  name: string;
  is_online: boolean;
}

interface StreamSession {
  url: string;
  expires_at: string | null;
}

function msLeft(expiresAt: string | null): number | null {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - Date.now();
  return ms > 0 ? ms : 0;
}

function fmtCountdown(ms: number): string {
  const s = Math.ceil(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/* Satu pemutar embed: sesi WHEP + keep-alive + banner iklan. */
function EmbedPlayer({
  apiKey,
  camera,
  ad,
}: {
  apiKey: string;
  camera: EmbedCamera;
  ad: AdConfig | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [session, setSession] = useState<StreamSession | null>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [loadingSession, setLoadingSession] = useState(false);
  const [negotiating, setNegotiating] = useState(false);
  const [left, setLeft] = useState<number | null>(null);
  const [tileHovered, setTileHovered] = useState(false);
  const [adClickTick, setAdClickTick] = useState(0);
  const [toastDismissed, setToastDismissed] = useState(false);

  /* Toast keep-alive yang ditutup manual muncul lagi di sesi berikutnya. */
  useEffect(() => {
    if (left === null || left >= 90_000) setToastDismissed(false);
  }, [left]);

  const clearTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const stop = useCallback(() => {
    clearTimer();
    stopWhep(pcRef.current);
    pcRef.current = null;
    setPlaying(false);
    setNegotiating(false);
    setLeft(null);
  }, []);

  /* Ambil sesi baru (dipakai saat mulai & perpanjang). */
  const fetchSession = useCallback(async (): Promise<StreamSession | null> => {
    setLoadingSession(true);
    setFailed(null);
    try {
      const s = await api.get<StreamSession>(
        `/external/stream?key=${encodeURIComponent(apiKey)}&camera=${camera.id}`,
      );
      setSession(s);
      return s;
    } catch (e) {
      setFailed(e instanceof ApiError ? e.message : "Gagal memulai sesi");
      return null;
    } finally {
      setLoadingSession(false);
    }
  }, [apiKey, camera.id]);

  const start = useCallback(
    async (sess?: StreamSession | null) => {
      const s = sess ?? (await fetchSession());
      const video = videoRef.current;
      if (!s || !video) return;
      stop();
      try {
        setNegotiating(true);
        const pc = await playWhep(video, s.url);
        pcRef.current = pc;
        setPlaying(true);
        /* Hitung mundur keep-alive dari expires_at. */
        clearTimer();
        const tick = () => {
          const ms = msLeft(s.expires_at);
          setLeft(ms);
          if (ms === 0) {
            clearTimer();
            stop();
            setFailed("Sesi berakhir, tekan Coba lagi untuk lanjut.");
          }
        };
        tick();
        timerRef.current = setInterval(tick, 1000);
      } catch {
        setFailed("Gagal memutar stream.");
      } finally {
        setNegotiating(false);
      }
    },
    [fetchSession, stop],
  );

  /* Perpanjang: sesi baru lalu lanjutkan putar. */
  const extend = useCallback(async () => {
    const s = await fetchSession();
    if (s) start(s);
  }, [fetchSession, start]);

  useEffect(() => () => stop(), [stop]);

  const showKeepAlive = left !== null && left < 90_000 && playing && !toastDismissed;

  return (
    <div
      onClick={() => setAdClickTick((t) => t + 1)}
      onMouseEnter={() => setTileHovered(true)}
      onMouseLeave={() => setTileHovered(false)}
      className="overflow-hidden rounded-2xl bg-ink-900 shadow-[0_8px_24px_-8px_rgba(0,0,0,0.35)]"
    >
      {/* Area video saja yang nv-stage (selalu gelap), kartu pemain
          mengikuti tema seperti CameraTile. */}
      <div className="nv-stage relative aspect-video bg-black">
        {/* Video SELALU terpasang, start() membaca videoRef saat tombol
            ditekan, saat itu playing masih false. */}
        <video
          ref={videoRef}
          playsInline
          muted
          className={`h-full w-full object-contain ${playing ? "" : "invisible"}`}
        />
        {!playing && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            {negotiating ? (
              <>
                <span
                  className="h-6 w-6 animate-spin rounded-full border-2 border-white/30 border-t-white motion-reduce:animate-none"
                  aria-hidden
                />
                <span className="text-xs text-neutral-400" role="status">
                  Menghubungkan video…
                </span>
              </>
            ) : failed ? (
              <>
                <p
                  role="alert"
                  className="max-w-xs text-xs leading-relaxed text-bad-400"
                >
                  {failed}
                </p>
                <Button onClick={() => start()} disabled={loadingSession}>
                  {loadingSession ? "Memuat…" : "Coba lagi"}
                </Button>
              </>
            ) : (
              <>
                <button
                  onClick={() => start()}
                  disabled={loadingSession}
                  className="flex h-16 w-16 items-center justify-center rounded-full bg-accent-600 text-onaccent transition hover:bg-accent-500 active:scale-95 disabled:opacity-40"
                  aria-label={`Putar ${camera.name}`}
                >
                  {loadingSession ? (
                    <span className="h-6 w-6 animate-spin rounded-full border-2 border-white/30 border-t-white motion-reduce:animate-none" />
                  ) : (
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                      <path d="M8 5v14l11-7-11-7z" />
                    </svg>
                  )}
                </button>
                <span className="text-xs text-neutral-400">
                  {loadingSession
                    ? "Menyiapkan sesi…"
                    : camera.is_online
                      ? "Klik untuk memutar"
                      : "Kamera terdeteksi offline, klik untuk mencoba"}
                </span>
              </>
            )}
          </div>
        )}

        {/* Toast keep-alive */}
        {showKeepAlive && (
          <div
            role="status"
            aria-live="polite"
            className="absolute left-3 top-3 z-30 flex max-w-[calc(100%-24px)] items-center gap-2.5 rounded-xl bg-ink-900/95 px-3.5 py-2.5"
          >
            <span className="min-w-0 truncate text-xs font-medium text-neutral-200">
              Sesi berakhir dalam
            </span>
            <span className="shrink-0 text-xs font-bold text-warn-400">
              {fmtCountdown(left)}
            </span>
            <Button
              onClick={extend}
              disabled={loadingSession}
              className="h-11 shrink-0 px-3 text-xs"
            >
              {loadingSession ? "Memuat…" : "Perpanjang"}
            </Button>
            <button
              type="button"
              onClick={() => setToastDismissed(true)}
              aria-label="Tutup pemberitahuan"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-neutral-400 transition hover:bg-ink-800 hover:text-white"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
                <path
                  d="M2 2l10 10M12 2L2 12"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        )}
      </div>

      {/* Iklan di bawah video (di luar area 16:9), bukan overlay. */}
      {ad?.is_active && (
        <AdBanner
          config={ad}
          placement="below"
          hovered={tileHovered}
          clickTick={adClickTick}
        />
      )}

      <div className="flex items-center justify-between gap-3 border-t border-ink-800 px-4 py-3.5">
        <span className="flex min-w-0 items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${camera.is_online ? "bg-ok-400" : "bg-bad-400"}`}
            role="img"
            aria-label={camera.is_online ? "Online" : "Offline"}
            title={camera.is_online ? "Online" : "Offline"}
          />
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-white">
            {camera.name}
          </span>
          {!camera.is_online && (
            <span className="shrink-0 rounded-full bg-bad-400/15 px-2 py-0.5 text-[11px] font-medium text-bad-400">
              Offline
            </span>
          )}
        </span>
        {playing && (
          <Button
            variant="danger"
            onClick={stop}
            className="h-11 shrink-0 gap-1.5 px-3 text-xs"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden>
              <rect x="2" y="2" width="8" height="8" rx="1.5" />
            </svg>
            Berhenti
          </Button>
        )}
      </div>
    </div>
  );
}

/* Panel state terpadu (loading / error / tidak tersedia / kosong):
   ikon + judul + teks, satu bentuk untuk semua kondisi. */
function EmbedStatePanel({
  title,
  text,
  tone = "info",
}: {
  title: string;
  text: string;
  tone?: "info" | "loading";
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col items-center gap-2 rounded-2xl bg-ink-900 px-6 py-14 text-center"
    >
      {tone === "loading" ? (
        <span
          className="h-9 w-9 animate-spin rounded-full border-2 border-neutral-600 border-t-white motion-reduce:animate-none"
          aria-hidden
        />
      ) : (
        <svg
          width="36"
          height="36"
          viewBox="0 0 24 24"
          fill="none"
          className="text-neutral-400"
          aria-hidden
        >
          <path
            d="M12 8v5M12 16.5v.01M10.3 3.9A9 9 0 0121 12a9 9 0 01-1.5 5M3.1 6.5A9 9 0 003 12a9 9 0 0013.7 7.7M4.9 4.9l14.2 14.2"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      )}
      <div className="text-sm font-semibold text-white">{title}</div>
      <p className="max-w-xs text-xs leading-relaxed text-neutral-400">
        {text}
      </p>
    </div>
  );
}

function EmbedInner() {
  const params = useSearchParams();
  const key = params.get("key");
  const cameraParam = params.get("camera");
  const [phase, setPhase] = useState<Phase>("loading");
  const [cameras, setCameras] = useState<EmbedCamera[]>([]);
  const [ad, setAd] = useState<AdConfig | null>(null);
  const [cameraState, setCameraState] = useState<{
    title: string;
    text: string;
  } | null>(null);

  useEffect(() => {
    if (!key) {
      setPhase("error");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get<EmbedCamera[]>(
          `/external/cameras?key=${encodeURIComponent(key)}`,
        );
        /* Banner iklan: publik, backend menonaktifkan bila tak diizinkan. */
        api
          .get<AdConfig>("/ad-config")
          .then((c) => {
            if (!cancelled) setAd(c);
          })
          .catch(() => {});
        if (cancelled) return;
        /* Embed hanya untuk SATU kamera: ?camera wajib dan harus valid.
           Tanpa ?camera, atau bila id tidak cocok, tampilkan pesan dan
           jangan render semua kamera bertumpuk. */
        let list = data;
        if (cameraParam) {
          const wanted = Number(cameraParam);
          list = data.filter((c) => c.id === wanted);
          if (list.length === 0) {
            setCameraState({
              title: "Kamera tidak tersedia",
              text: `Kamera ?camera=${cameraParam} tidak tersedia untuk kunci ini.`,
            });
            list = [];
          }
        } else {
          setCameraState({
            title: "Kamera belum dipilih",
            text: "Tambahkan ?camera=<id> pada tautan embed.",
          });
          list = [];
        }
        setCameras(list);
        setPhase("ready");
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setPhase("unavailable");
        } else {
          setPhase("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key, cameraParam]);

  return (
    <div className="flex min-h-dvh flex-col bg-ink-950">
      <header className="flex items-center justify-between px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-600 text-xs font-bold text-onaccent">
            N
          </span>
          <span className="text-sm font-bold text-white">NetraVision</span>
        </div>
        <span className="rounded-full bg-ink-800 px-3 py-1 text-[11px] font-medium text-neutral-400">
          Siaran publik
        </span>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-10 sm:px-6">
        {phase === "loading" && (
          <EmbedStatePanel
            tone="loading"
            title="Memuat"
            text="Menyiapkan siaran publik…"
          />
        )}

        {phase === "error" && (
          <EmbedStatePanel
            title="Tautan embed tidak valid"
            text="Parameter ?key= tidak ditemukan atau tidak dikenal."
          />
        )}

        {phase === "unavailable" && (
          <EmbedStatePanel
            title="Kunci API tidak dikenal"
            text="Kunci API pada tautan ini tidak dikenal."
          />
        )}

        {phase === "ready" && (
          <div className="flex flex-col gap-4">
            {cameraState ? (
              <EmbedStatePanel
                title={cameraState.title}
                text={cameraState.text}
              />
            ) : (
              <>
                {key &&
                  cameras.map((c) => (
                    <EmbedPlayer key={c.id} apiKey={key} camera={c} ad={ad} />
                  ))}
                {cameras.length === 0 && (
                  <EmbedStatePanel
                    title="Tidak ada kamera"
                    text="Tidak ada kamera untuk kunci ini."
                  />
                )}
              </>
            )}
          </div>
        )}
      </main>

      <footer className="px-4 pb-6 text-center text-[11px] text-neutral-400 sm:px-6">
        NetraVision · Siaran publik pihak ketiga
      </footer>
    </div>
  );
}

/* useSearchParams wajib di dalam Suspense untuk static export. */
export default function EmbedPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-dvh items-center justify-center bg-ink-950">
          <span className="text-sm text-neutral-400">Memuat…</span>
        </div>
      }
    >
      <EmbedInner />
    </Suspense>
  );
}
