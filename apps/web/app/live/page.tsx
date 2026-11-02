"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "../../components/AppShell";
import { CameraTile } from "../../components/CameraTile";
import { FocusModal } from "../../components/FocusModal";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import type { Stream } from "../../lib/types";

type StatusFilter = "all" | "online" | "offline";

const FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "all", label: "Semua" },
  { id: "online", label: "Online" },
  { id: "offline", label: "Offline" },
];

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="aspect-video animate-pulse rounded-2xl bg-ink-800 motion-reduce:animate-none"
        />
      ))}
    </div>
  );
}

/* Halaman utama: grid live semua kamera (sub stream, lazy-load per tile). */
export default function LivePage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const { status, connected } = useCameraStatus();

  const [streams, setStreams] = useState<Stream[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [focus, setFocus] = useState<Stream | null>(null);

  const load = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const data = await api.get<Stream[]>("/streams");
      setStreams(data);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Gagal memuat daftar kamera",
      );
    } finally {
      setFetching(false);
    }
  }, []);

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
      return;
    }
    if (user) load();
  }, [loading, user, router, load]);

  /* Override status dari WebSocket bila tersedia. */
  const merged = useMemo(
    () =>
      streams.map((s) =>
        status.has(s.id) ? { ...s, is_online: status.get(s.id)! } : s,
      ),
    [streams, status],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return merged.filter((s) => {
      if (filter === "online" && !s.is_online) return false;
      if (filter === "offline" && s.is_online) return false;
      if (q && !s.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [merged, query, filter]);

  const onlineCount = merged.filter((s) => s.is_online).length;
  const counts: Record<StatusFilter, number> = {
    all: merged.length,
    online: onlineCount,
    offline: merged.length - onlineCount,
  };

  if (loading || (!user && !loading)) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-ink-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/15 border-t-accent-400 motion-reduce:animate-none" />
      </div>
    );
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-4 py-5 md:px-6 md:py-7">
        {/* Header */}
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Live
            </h1>
            <p className="mt-1 flex items-center gap-2 text-sm text-neutral-400">
              <span>{merged.length} kamera</span>
              <span className="font-medium text-ok-400">
                {onlineCount} online
              </span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className="flex h-11 items-center gap-2 rounded-full bg-ink-900 px-4 text-xs font-medium text-neutral-300 ring-1 ring-white/10"
              title={connected ? "WebSocket terhubung" : "Menghubungkan…"}
            >
              <span
                className={`h-2 w-2 rounded-full ${connected ? "bg-ok-400" : "bg-warn-400"}`}
              />
              {connected ? "Real-time" : "Menghubungkan…"}
            </span>
            <button
              onClick={load}
              disabled={fetching}
              className="flex h-11 items-center gap-2 rounded-full bg-ink-900 px-4 text-sm font-medium text-neutral-200 ring-1 ring-white/10 transition hover:bg-ink-800 active:scale-95 disabled:opacity-50"
            >
              <svg
                width="15"
                height="15"
                viewBox="0 0 16 16"
                fill="none"
                className={fetching ? "animate-spin motion-reduce:animate-none" : ""}
                aria-hidden
              >
                <path
                  d="M13.5 8a5.5 5.5 0 11-1.6-3.9M13.5 1.5v3h-3"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              Muat ulang
            </button>
          </div>
        </div>

        {/* Search + filter segmented */}
        <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full lg:max-w-xs">
            <svg
              width="17"
              height="17"
              viewBox="0 0 16 16"
              fill="none"
              className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-500"
              aria-hidden
            >
              <path
                d="M7.5 12.5a5 5 0 100-10 5 5 0 000 10zM11.5 11.5L14 14"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Cari kamera…"
              aria-label="Cari kamera"
              className="h-11 w-full rounded-full bg-ink-900 pl-10 pr-4 text-base text-white ring-1 ring-white/10 placeholder:text-neutral-500 focus:outline-none focus:ring-2 focus:ring-accent-500"
            />
          </div>
          <div
            className="flex w-full items-center gap-1 overflow-x-auto rounded-full bg-ink-900 p-1 ring-1 ring-white/10 lg:w-auto"
            role="tablist"
            aria-label="Filter status kamera"
          >
            {FILTERS.map((f) => (
              <button
                key={f.id}
                role="tab"
                aria-selected={filter === f.id}
                onClick={() => setFilter(f.id)}
                className={`flex h-10 flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-5 text-sm font-medium transition active:scale-95 lg:flex-none ${
                  filter === f.id
                    ? "bg-accent-600 text-onaccent"
                    : "text-neutral-400 hover:text-white"
                }`}
              >
                {f.label}
                <span
                  className={`text-xs ${filter === f.id ? "text-white/80" : "text-neutral-600"}`}
                >
                  {counts[f.id]}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Konten */}
        {fetching ? (
          <SkeletonGrid />
        ) : error ? (
          <div className="flex flex-col items-center gap-4 rounded-2xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <svg
              width="36"
              height="36"
              viewBox="0 0 24 24"
              fill="none"
              className="text-neutral-600"
              aria-hidden
            >
              <path
                d="M12 8v5M12 16.5v.01M4.9 4.9l14.2 14.2M10.3 3.9A9 9 0 0121 12a9 9 0 01-1.5 5M3.1 6.5A9 9 0 003 12a9 9 0 0013.7 7.7"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
            <div>
              <p className="text-sm font-medium text-neutral-200">
                Gagal memuat kamera
              </p>
              <p className="mt-1 text-xs text-neutral-500">{error}</p>
            </div>
            <button
              onClick={load}
              className="h-11 rounded-full bg-accent-600 px-6 text-sm font-medium text-onaccent transition hover:bg-accent-500 active:scale-95"
            >
              Coba lagi
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-2xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <svg
              width="40"
              height="40"
              viewBox="0 0 20 20"
              fill="none"
              className="text-neutral-600"
              aria-hidden
            >
              <path
                d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <p className="text-sm font-medium text-neutral-200">
              {merged.length === 0
                ? "Belum ada kamera"
                : "Tidak ada kamera yang cocok"}
            </p>
            <p className="max-w-xs text-xs leading-relaxed text-neutral-500">
              {merged.length === 0
                ? "Tambahkan kamera lewat halaman Admin untuk mulai memantau."
                : "Coba ubah kata kunci atau filter status."}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filtered.map((s) => (
              <CameraTile key={s.id} stream={s} onExpand={setFocus} />
            ))}
          </div>
        )}
      </div>

      <FocusModal stream={focus} onClose={() => setFocus(null)} />
    </AppShell>
  );
}
