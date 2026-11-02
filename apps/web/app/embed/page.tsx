"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "../../lib/api";
import { playWhep, stopWhep } from "../../lib/whep";
import { AdBanner } from "../../components/AdBanner";
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
  const [left, setLeft] = useState<number | null>(null);

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
            setFailed("Sesi berakhir — tekan Perpanjang untuk lanjut.");
          }
        };
        tick();
        timerRef.current = setInterval(tick, 1000);
      } catch {
        setFailed("Gagal memutar stream.");
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

  const showKeepAlive = left !== null && left < 90_000 && playing;

  return (
    <div className="nv-stage overflow-hidden rounded-2xl bg-ink-900 ring-1 ring-white/10">
      <div className="relative aspect-video bg-black">
        {ad?.is_active && <AdBanner config={ad} />}
        {playing ? (
          <video
            ref={videoRef}
            playsInline
            muted
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-6 text-center">
            {failed ? (
              <>
                <p className="max-w-xs text-xs leading-relaxed text-bad-400">
                  {failed}
                </p>
                <button
                  onClick={() => start()}
                  disabled={loadingSession}
                  className="flex h-11 items-center gap-2 rounded-xl bg-accent-600 px-5 text-sm font-semibold text-onaccent transition hover:bg-accent-500 active:scale-95 disabled:opacity-50"
                >
                  {loadingSession ? "Memuat…" : "Coba lagi"}
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => start()}
                  disabled={loadingSession || !camera.is_online}
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
                      : "Kamera offline"}
                </span>
              </>
            )}
          </div>
        )}

        {/* Toast keep-alive */}
        {showKeepAlive && (
          <div className="absolute left-3 top-3 z-30 flex items-center gap-2.5 rounded-xl bg-ink-900/95 px-3.5 py-2.5 ring-1 ring-white/15">
            <span className="text-xs font-medium text-neutral-200">
              Sesi berakhir dalam{" "}
              <span className="font-bold text-warn-400">
                {fmtCountdown(left)}
              </span>
            </span>
            <button
              onClick={extend}
              disabled={loadingSession}
              className="flex h-9 items-center rounded-lg bg-accent-600 px-3 text-xs font-semibold text-onaccent transition hover:bg-accent-500 active:scale-95 disabled:opacity-50"
            >
              {loadingSession ? "…" : "Perpanjang"}
            </button>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 px-4 py-3.5">
        <span className="flex min-w-0 items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${camera.is_online ? "bg-ok-400" : "bg-bad-400"}`}
          />
          <span className="truncate text-sm font-medium text-white">
            {camera.name}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {playing && (
            <button
              onClick={stop}
              className="flex h-9 items-center gap-1.5 rounded-lg bg-bad-400/15 px-3 text-xs font-semibold text-bad-400 ring-1 ring-bad-400/30 transition hover:bg-bad-400/25 active:scale-95"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden>
                <rect x="2" y="2" width="8" height="8" rx="1.5" />
              </svg>
              Stop
            </button>
          )}
          <span className="flex items-center gap-1.5 text-[11px] text-neutral-500">
            <span className="flex h-5 w-5 items-center justify-center rounded-md bg-accent-600 text-[9px] font-bold text-onaccent">
              N
            </span>
            NetraVision
          </span>
        </span>
      </div>
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
  const [notice, setNotice] = useState<string | null>(null);

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
        let list = data;
        if (cameraParam) {
          const wanted = Number(cameraParam);
          list = data.filter((c) => c.id === wanted);
          if (list.length === 0) {
            setNotice(
              `Kamera ?camera=${cameraParam} tidak tersedia untuk kunci ini — menampilkan semua kamera.`,
            );
            list = data;
          }
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
          <div className="aspect-video animate-pulse rounded-2xl bg-ink-800 motion-reduce:animate-none" />
        )}

        {phase === "error" && (
          <div className="flex flex-col items-center gap-2 rounded-2xl bg-ink-900 px-6 py-14 text-center ring-1 ring-white/10">
            <svg
              width="36"
              height="36"
              viewBox="0 0 24 24"
              fill="none"
              className="text-neutral-600"
              aria-hidden
            >
              <path
                d="M12 8v5M12 16.5v.01M10.3 3.9A9 9 0 0121 12a9 9 0 01-1.5 5M3.1 6.5A9 9 0 003 12a9 9 0 0013.7 7.7M4.9 4.9l14.2 14.2"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
            <div className="text-sm font-semibold text-white">
              Tautan embed tidak valid
            </div>
            <p className="max-w-xs text-xs leading-relaxed text-neutral-400">
              Parameter <code className="text-neutral-300">?key=</code> tidak
              ditemukan atau tidak dikenal.
            </p>
          </div>
        )}

        {phase === "unavailable" && (
          <div className="rounded-2xl bg-ink-900 px-6 py-14 text-center text-sm text-neutral-400 ring-1 ring-white/10">
            Kunci API tidak dikenal.
          </div>
        )}

        {phase === "ready" && (
          <div className="flex flex-col gap-4">
            {notice && (
              <div className="rounded-xl border border-warn-400/30 bg-warn-400/10 px-4 py-3 text-xs text-warn-400">
                {notice}
              </div>
            )}
            {key &&
              cameras.map((c) => (
                <EmbedPlayer key={c.id} apiKey={key} camera={c} ad={ad} />
              ))}
            {cameras.length === 0 && (
              <div className="rounded-2xl bg-ink-900 px-6 py-14 text-center text-sm text-neutral-400 ring-1 ring-white/10">
                Tidak ada kamera untuk kunci ini.
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="px-4 pb-6 text-center text-[11px] text-neutral-600 sm:px-6">
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
