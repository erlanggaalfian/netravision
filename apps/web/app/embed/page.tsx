"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "../../lib/api";

/* Halaman embed PUBLIK (tanpa login) untuk pihak ketiga.
   Kunci via ?key=. */

type Phase = "loading" | "unavailable" | "error" | "ready";

interface EmbedCamera {
  id: number;
  name: string;
  whep_url: string | null;
  click_to_play: boolean;
}

/* Pemutar click-to-play untuk satu kamera embed. */
function EmbedPlayer({ camera }: { camera: EmbedCamera }) {
  const [playing, setPlaying] = useState(false);
  return (
    <div className="nv-stage overflow-hidden rounded-2xl bg-ink-900 ring-1 ring-white/10">
      <div className="relative aspect-video bg-black">
        {playing && camera.whep_url ? (
          <div className="flex h-full w-full items-center justify-center text-xs text-neutral-400">
            {/* TODO: playWhep(camera.whep_url) */}
            Memutar…
          </div>
        ) : (
          <button
            onClick={() => setPlaying(true)}
            className="flex h-full w-full flex-col items-center justify-center gap-3 transition hover:bg-white/5 active:scale-[0.99]"
            aria-label={`Putar ${camera.name}`}
          >
            <span className="flex h-16 w-16 items-center justify-center rounded-full bg-accent-600 text-onaccent transition hover:bg-accent-500">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                <path d="M8 5v14l11-7-11-7z" />
              </svg>
            </span>
            <span className="text-xs text-neutral-400">Klik untuk memutar</span>
          </button>
        )}
      </div>
      <div className="flex items-center justify-between gap-3 px-4 py-3.5">
        <span className="truncate text-sm font-medium text-white">
          {camera.name}
        </span>
        <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-neutral-500">
          <span className="flex h-5 w-5 items-center justify-center rounded-md bg-accent-600 text-[9px] font-bold text-onaccent">
            N
          </span>
          NetraVision
        </span>
      </div>
    </div>
  );
}

function EmbedInner() {
  const params = useSearchParams();
  const key = params.get("key");
  const [phase, setPhase] = useState<Phase>("loading");
  const [cameras, setCameras] = useState<EmbedCamera[]>([]);

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
        if (!cancelled) {
          setCameras(data);
          setPhase("ready");
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setPhase("unavailable"); // jujur: belum ada di backend
        } else {
          setPhase("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key]);

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
          <div>
            <div className="nv-stage relative mb-4 aspect-video overflow-hidden rounded-2xl bg-ink-900 ring-1 ring-white/10">
              <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-6 text-center">
                <span className="flex h-16 w-16 items-center justify-center rounded-full bg-ink-800 text-neutral-400 ring-1 ring-white/10">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path
                      d="M8 5v14l11-7-11-7z"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <div className="text-sm font-semibold text-white">
                  Embed tersedia mulai Fase 3
                </div>
                <p className="max-w-sm text-xs leading-relaxed text-neutral-400">
                  Pratinjau embed pihak ketiga. Setelah backend Fase 3 aktif,
                  area ini akan menampilkan video kamera sesuai kunci API.
                </p>
              </div>
            </div>
            <div className="flex items-center justify-between px-1">
              <span className="text-xs text-neutral-500">
                Kunci: <code className="text-neutral-400">{key}</code>
              </span>
              <span className="text-[11px] text-neutral-600">
                NetraVision Embed
              </span>
            </div>
          </div>
        )}

        {phase === "ready" && (
          <div className="flex flex-col gap-4">
            {cameras.map((c) => (
              <EmbedPlayer key={c.id} camera={c} />
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
