"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "../../lib/api";

/* Halaman embed PUBLIK (tanpa login) untuk pihak ketiga.
   Kunci via ?key=. Kontrak /api/external/* BARU ADA di Fase 3 —
   sampai saat itu tampilkan placeholder jujur, dengan struktur
   yang siap disambung (EmbedPlayer). */

type Phase = "loading" | "unavailable" | "error" | "ready";

interface EmbedCamera {
  id: number;
  name: string;
  whep_url: string | null;
  click_to_play: boolean;
}

/* Siap disambung Fase 3: pemutar click-to-play untuk satu kamera embed. */
function EmbedPlayer({ camera }: { camera: EmbedCamera }) {
  const [playing, setPlaying] = useState(false);
  return (
    <div className="overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/10">
      <div className="relative aspect-video bg-black">
        {playing && camera.whep_url ? (
          <div className="flex h-full w-full items-center justify-center text-xs text-neutral-400">
            {/* TODO Fase 3: playWhep(camera.whep_url) */}
            Memutar…
          </div>
        ) : (
          <button
            onClick={() => setPlaying(true)}
            className="flex h-full w-full flex-col items-center justify-center gap-3 transition hover:bg-white/5 active:scale-[0.99]"
            aria-label={`Putar ${camera.name}`}
          >
            <span className="flex h-16 w-16 items-center justify-center rounded-full bg-accent-600 text-white shadow-lg transition hover:bg-accent-500">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7-11-7z" />
              </svg>
            </span>
            <span className="text-xs text-neutral-400">
              Klik untuk memutar
            </span>
          </button>
        )}
      </div>
      <div className="flex items-center justify-between px-4 py-3">
        <span className="truncate text-sm font-medium text-white">
          {camera.name}
        </span>
        <span className="text-[11px] text-neutral-500">NetraVision</span>
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
        // Endpoint ini baru ada di Fase 3.
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
      <header className="flex items-center gap-2 px-4 py-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-600 text-xs font-bold text-white">
          N
        </span>
        <span className="text-sm font-bold text-white">NetraVision</span>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-8">
        {phase === "loading" && (
          <div className="aspect-video animate-pulse rounded-xl bg-ink-800" />
        )}

        {phase === "error" && (
          <div className="rounded-xl bg-ink-900 p-8 text-center ring-1 ring-white/10">
            <div className="mb-1 text-sm font-semibold text-white">
              Tautan embed tidak valid
            </div>
            <p className="text-xs text-neutral-400">
              Parameter <code className="text-neutral-300">?key=</code> tidak
              ditemukan atau tidak dikenal.
            </p>
          </div>
        )}

        {phase === "unavailable" && (
          <div>
            <div className="relative mb-3 aspect-video overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/10">
              <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-6 text-center">
                <span className="flex h-16 w-16 items-center justify-center rounded-full bg-white/5 text-neutral-400 ring-1 ring-white/10">
                  <svg
                    width="24"
                    height="24"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
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
          <div className="flex flex-col gap-3">
            {cameras.map((c) => (
              <EmbedPlayer key={c.id} camera={c} />
            ))}
            {cameras.length === 0 && (
              <div className="rounded-xl bg-ink-900 p-8 text-center text-sm text-neutral-400 ring-1 ring-white/10">
                Tidak ada kamera untuk kunci ini.
              </div>
            )}
          </div>
        )}
      </main>
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
