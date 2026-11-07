"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "../../components/AppShell";
import { CameraTile } from "../../components/CameraTile";
import { FocusModal } from "../../components/FocusModal";
import { Button, GridIcon, Spinner } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import type { AdConfig, Stream } from "../../lib/types";

type StatusFilter = "all" | "online" | "offline";

const FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "all", label: "Semua" },
  { id: "online", label: "Online" },
  { id: "offline", label: "Offline" },
];

/* PC: bentuk grid (jumlah kolom). HP: jumlah kamera yang ditampilkan
   (grid HP selalu 1 kolom). Label menjelaskan arti angka. */
interface GridOpt {
  key: string;
  label: string;
  cols?: number;
  count?: number;
}
const GRID_OPTS_PC: GridOpt[] = [
  { key: "1x1", label: "1×1", cols: 1 },
  { key: "2x2", label: "2×2", cols: 2 },
  { key: "3x3", label: "3×3", cols: 3 },
  { key: "4x4", label: "4×4", cols: 4 },
];
const GRID_OPTS_MOBILE: GridOpt[] = [
  { key: "2", label: "2", count: 2 },
  { key: "4", label: "4", count: 4 },
  { key: "6", label: "6", count: 6 },
  { key: "9", label: "9", count: 9 },
];

const GRID_CLASS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-1 sm:grid-cols-2",
  3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
  4: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
};

/* Desktop = sidebar tampil (md, 768px), sama seperti AppShell. */
function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 768px)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return isDesktop;
}

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
  const [ad, setAd] = useState<AdConfig | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [gridKey, setGridKey] = useState("2x2");
  const isDesktop = useIsDesktop();
  /* Panel kontrol dilipat di HP (tombol filter), selalu tampil di desktop. */
  const [filterOpen, setFilterOpen] = useState(false);
  const gridOpts = isDesktop ? GRID_OPTS_PC : GRID_OPTS_MOBILE;
  /* Kunci dari perangkat lain tidak cocok: pakai default perangkat ini. */
  const activeOpt = gridOpts.find((g) => g.key === gridKey) ?? gridOpts[1];
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

  /* Config iklan: sekali per halaman, dipakai semua tile. */
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    api
      .get<AdConfig>("/ad-config")
      .then((c) => {
        if (!cancelled) setAd(c);
      })
      .catch(() => {
        /* iklan opsional; abaikan bila gagal */
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

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

  const gridCols = isDesktop ? (activeOpt.cols ?? 2) : 1;
  const visibleStreams = isDesktop
    ? filtered
    : filtered.slice(0, activeOpt.count ?? 4);

  const onlineCount = merged.filter((s) => s.is_online).length;
  const counts: Record<StatusFilter, number> = {
    all: merged.length,
    online: onlineCount,
    offline: merged.length - onlineCount,
  };

  if (loading || (!user && !loading)) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-ink-950">
        <Spinner />
      </div>
    );
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-4 py-5 md:px-6 md:py-7">
        {/* Header: judul + status, lalu pencarian, lalu kontrol (dilipat di HP) */}
        <div className="nv-panel-modern mb-5 p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-extrabold tracking-tight text-white sm:text-[26px]">
                Live
              </h1>
              <p className="mt-1.5 text-sm text-slate-400">
                {isDesktop
                  ? `${merged.length} kamera · ${onlineCount} online`
                  : `Menampilkan ${visibleStreams.length} dari ${filtered.length} kamera · ${onlineCount} online`}
              </p>
            </div>
            {/* HP: titik kecil beranimasi lampu di kanan atas panel. */}
            <span
              className="flex h-8 shrink-0 items-center md:hidden"
              title={connected ? "Terhubung" : "Menghubungkan…"}
            >
              <span
                className={`nv-lamp h-2.5 w-2.5 rounded-full ${connected ? "bg-ok-400 text-ok-400" : "bg-warn-400 text-warn-400"}`}
              />
              <span className="sr-only">
                {connected ? "Terhubung" : "Menghubungkan…"}
              </span>
            </span>
            {/* Status koneksi: desktop saja (dot + teks). */}
            <span
              className="hidden h-11 w-11 shrink-0 items-center justify-center rounded-full bg-ink-800 shadow-sm md:flex md:h-11 md:w-auto md:gap-2 md:px-4 md:text-xs md:font-semibold md:text-neutral-300"
              title={connected ? "WebSocket terhubung" : "Menghubungkan…"}
            >
              <span
                className={`h-2 w-2 rounded-full ${connected ? "bg-ok-400" : "bg-warn-400"}`}
              />
              <span className="sr-only md:not-sr-only">
                {connected ? "Real-time" : "Menghubungkan…"}
              </span>
            </span>
          </div>

          {/* Kontrol: satu baris di PC lebar (search + grid + refresh +
              status), bertumpuk di HP/tablet; dilipat di HP */}
          <div className="mt-4 flex flex-col gap-4 border-t border-ink-800 pt-4 xl:flex-row xl:items-center xl:gap-3">
            <div className="flex items-center gap-2 xl:min-w-0 xl:flex-1">
              <div className="relative min-w-0 flex-1 xl:max-w-xs">
              <svg
                width="17"
                height="17"
                viewBox="0 0 16 16"
                fill="none"
                className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-400"
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
                className="h-11 w-full rounded-full bg-ink-800 pl-10 pr-4 text-base text-white shadow-sm placeholder:text-neutral-500 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-accent-500/30"
              />
            </div>
            <button
              onClick={() => setFilterOpen((v) => !v)}
              aria-expanded={filterOpen}
              aria-label={filterOpen ? "Sembunyikan filter" : "Tampilkan filter"}
              className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-ink-800 text-slate-300 shadow-sm transition active:scale-95 md:hidden"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                aria-hidden
              >
                <line x1="4" y1="21" x2="4" y2="14" />
                <line x1="4" y1="10" x2="4" y2="3" />
                <line x1="12" y1="21" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12" y2="3" />
                <line x1="20" y1="21" x2="20" y2="16" />
                <line x1="20" y1="12" x2="20" y2="3" />
                <line x1="1" y1="14" x2="7" y2="14" />
                <line x1="9" y1="8" x2="15" y2="8" />
                <line x1="17" y1="16" x2="23" y2="16" />
              </svg>
              {filter !== "all" && (
                <span className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-accent-500" />
              )}
            </button>
          </div>

          {/* Kontrol grid + refresh + status: dilipat di HP, tampil di desktop */}
          <div
            className={`${filterOpen ? "nv-pop block" : "hidden"} md:block`}
          >
            <div className="flex flex-wrap items-center gap-3 xl:flex-nowrap">
              <div className="flex min-w-0 items-center gap-2 max-md:flex-1">
                {isDesktop && (
                  <span className="text-xs font-semibold text-slate-400">
                    Grid:
                  </span>
                )}
                <div
                  className="flex min-w-0 items-center gap-1 rounded-full bg-ink-800 p-1 shadow-sm max-md:flex-1"
                  role="tablist"
                  aria-label={
                    isDesktop
                      ? "Tata letak grid"
                      : "Jumlah kamera yang ditampilkan"
                  }
                >
                  {gridOpts.map((g) => (
                    <button
                      key={g.key}
                      role="tab"
                      aria-selected={activeOpt.key === g.key}
                      aria-label={
                        isDesktop
                          ? `Grid ${g.label}`
                          : `Tampilkan ${g.label} kamera`
                      }
                      title={
                        isDesktop
                          ? `Grid ${g.label} (${g.cols} kolom)`
                          : `Tampilkan ${g.label} kamera`
                      }
                      onClick={() => setGridKey(g.key)}
                      className={`flex h-10 min-w-[48px] items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-3 text-xs font-bold transition-all duration-200 active:scale-95 max-md:flex-1 ${
                        activeOpt.key === g.key
                          ? "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                          : "text-neutral-400 hover:bg-ink-700 hover:text-slate-200"
                      }`}
                    >
                      {isDesktop ? (
                        <GridIcon cols={g.cols ?? 1} />
                      ) : (
                        <>
                          <svg
                            width="14"
                            height="14"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden
                          >
                            <path d="M23 7l-7 5 7 5V7z" />
                            <rect x="1" y="5" width="15" height="14" rx="2" />
                          </svg>
                          {g.label}
                        </>
                      )}
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={load}
                disabled={fetching}
                aria-label="Muat ulang"
                className="flex h-11 items-center gap-2 rounded-full bg-ink-800 px-4 text-sm font-semibold text-neutral-200 shadow-sm transition-all duration-200 hover:bg-ink-700 active:scale-95 disabled:opacity-50"
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
                <span className="hidden min-[420px]:inline">Muat ulang</span>
              </button>
              <div
                className="nv-scroll-x flex w-full items-center gap-1 overflow-x-auto rounded-full bg-ink-800 p-1 shadow-sm sm:w-auto"
                role="tablist"
                aria-label="Filter status kamera"
              >
                {FILTERS.map((f) => (
                  <button
                    key={f.id}
                    role="tab"
                    aria-selected={filter === f.id}
                    onClick={() => setFilter(f.id)}
                    className={`flex h-10 flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-3 text-sm font-semibold transition-all duration-200 active:scale-95 sm:px-5 lg:flex-none ${
                      filter === f.id
                        ? "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                        : "text-neutral-400 hover:bg-ink-700 hover:text-slate-200"
                    }`}
                  >
                    {f.label}
                    <span
                      className={`rounded-full px-1.5 py-0.5 text-xs font-bold leading-none ${
                        filter === f.id
                          ? "bg-black/20 text-onaccent"
                          : "bg-ink-500/25 text-neutral-300"
                      }`}
                    >
                      {counts[f.id]}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
          </div>
        </div>

        {/* Konten */}
        {fetching ? (
          <SkeletonGrid />
        ) : error ? (
          <div className="nv-panel-modern flex flex-col items-center gap-4 px-6 py-16 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-bad-500/10">
              <svg
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                className="text-bad-400"
                aria-hidden
              >
                <path
                  d="M12 8v5M12 16.5v.01M4.9 4.9l14.2 14.2M10.3 3.9A9 9 0 0121 12a9 9 0 01-1.5 5M3.1 6.5A9 9 0 003 12a9 9 0 0013.7 7.7"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <div>
              <p className="text-base font-bold tracking-tight text-white">
                Gagal memuat kamera
              </p>
              <p className="mt-1.5 text-sm text-neutral-400">{error}</p>
            </div>
            <Button onClick={load}>
              Coba lagi
            </Button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="nv-panel-modern flex flex-col items-center gap-4 px-6 py-16 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-500/10">
              <svg
                width="32"
                height="32"
                viewBox="0 0 20 20"
                fill="none"
                className="text-accent-400"
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
            </div>
            <p className="text-base font-bold tracking-tight text-white">
              {merged.length === 0
                ? "Belum ada kamera"
                : "Tidak ada kamera yang cocok"}
            </p>
            <p className="max-w-xs text-sm leading-relaxed text-neutral-400">
              {merged.length === 0
                ? "Tambahkan kamera lewat halaman Admin untuk mulai memantau."
                : "Coba ubah kata kunci atau filter status."}
            </p>
          </div>
        ) : (
          <div className={`grid gap-4 ${GRID_CLASS[gridCols] ?? GRID_CLASS[2]}`}>
            {visibleStreams.map((s) => (
              <CameraTile key={s.id} stream={s} onExpand={setFocus} ad={ad} />
            ))}
          </div>
        )}
      </div>

      <FocusModal stream={focus} onClose={() => setFocus(null)} />
    </AppShell>
  );
}
