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
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="aspect-video animate-pulse rounded-lg bg-ink-800"
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

  if (loading || (!user && !loading)) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-ink-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/15 border-t-accent-400" />
      </div>
    );
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-4 py-4 md:px-6 md:py-6">
        {/* Header */}
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-bold text-white md:text-xl">Live</h1>
            <p className="text-xs text-neutral-400">
              {merged.length} kamera · {onlineCount} online
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className="flex items-center gap-1.5 rounded-full bg-ink-800 px-3 py-1.5 text-[11px] text-neutral-300"
              title={connected ? "WebSocket terhubung" : "Menghubungkan…"}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-ok-400" : "bg-warn-400"}`}
              />
              {connected ? "Real-time" : "Menghubungkan…"}
            </span>
            <button
              onClick={load}
              disabled={fetching}
              className="flex h-9 items-center gap-2 rounded-lg bg-ink-800 px-3 text-xs font-medium text-neutral-200 ring-1 ring-white/10 transition hover:bg-ink-700 active:scale-95 disabled:opacity-50"
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 16 16"
                fill="none"
                className={fetching ? "animate-spin" : ""}
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

        {/* Filter */}
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Cari kamera…"
            className="h-10 w-full rounded-lg bg-ink-800 px-3 text-sm text-white ring-1 ring-white/10 placeholder:text-neutral-500 focus:outline-none focus:ring-2 focus:ring-accent-500 sm:max-w-64"
          />
          <div className="flex gap-2">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={`h-9 rounded-full px-4 text-xs font-medium transition active:scale-95 ${
                  filter === f.id
                    ? "bg-accent-600 text-white"
                    : "bg-ink-800 text-neutral-400 ring-1 ring-white/10 hover:text-white"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* Konten */}
        {fetching ? (
          <SkeletonGrid />
        ) : error ? (
          <div className="flex flex-col items-center gap-3 rounded-xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <p className="text-sm text-neutral-300">{error}</p>
            <button
              onClick={load}
              className="rounded-lg bg-accent-600 px-4 py-2 text-xs font-medium text-white transition hover:bg-accent-500 active:scale-95"
            >
              Coba lagi
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <svg width="40" height="40" viewBox="0 0 20 20" fill="none" className="text-neutral-600">
              <path
                d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <p className="text-sm font-medium text-neutral-300">
              {merged.length === 0
                ? "Belum ada kamera"
                : "Tidak ada kamera yang cocok"}
            </p>
            <p className="max-w-xs text-xs text-neutral-500">
              {merged.length === 0
                ? "Tambahkan kamera lewat halaman Admin untuk mulai memantau."
                : "Coba ubah kata kunci atau filter status."}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
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
