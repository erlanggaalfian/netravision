"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "../../components/AppShell";
import { Card } from "../../components/ui";
import { api, apiFetch, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import type { Stream } from "../../lib/types";

/* Kontrak Fase 3 (packages/contracts/openapi.yaml):
   GET /recordings/{id}/timeline?date=YYYY-MM-DD → { date, entries: [{start, end, has_event?}] }
   GET /recordings/{id}/playback-url?time=ISO → { url, expires_at }
   GET /recordings/{id}/file?start=ISO&end=ISO → unduhan potongan */
interface TimelineEntry {
  start: string;
  end: string;
  has_event?: boolean;
}
interface TimelineData {
  date: string;
  entries: TimelineEntry[];
}
interface PlaybackUrl {
  url: string;
  expires_at: string | null;
}

type Phase = "idle" | "loading" | "ready" | "not-implemented" | "error";

const DAY_MS = 86_400_000;

const GRID_OPTS = [
  { cols: 2, label: "2×2" },
  { cols: 3, label: "3×3" },
  { cols: 4, label: "4×4" },
];

const GRID_CLASS: Record<number, string> = {
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-2 lg:grid-cols-3",
  4: "sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
};

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

/* Satu panel playback mandiri: satu kamera, tanggal dari induk. */
function PlaybackPanel({
  streamId,
  streamName,
  date,
}: {
  streamId: number;
  streamName: string;
  date: string;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [active, setActive] = useState<TimelineEntry | null>(null);
  const [videoSrc, setVideoSrc] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  const load = useCallback(async () => {
    setPhase("loading");
    setError(null);
    setTimeline(null);
    setActive(null);
    setVideoSrc(null);
    try {
      const t = await api.get<TimelineData>(
        `/recordings/${streamId}/timeline?date=${date}`,
      );
      setTimeline(t);
      setPhase("ready");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setPhase("not-implemented");
      } else {
        setError(e instanceof ApiError ? e.message : "Gagal memuat linimasa");
        setPhase("error");
      }
    }
  }, [streamId, date]);

  useEffect(() => {
    load();
  }, [load]);

  const playEntry = useCallback(
    async (entry: TimelineEntry) => {
      setActive(entry);
      setVideoSrc(null);
      try {
        const p = await api.get<PlaybackUrl>(
          `/recordings/${streamId}/playback-url?time=${encodeURIComponent(entry.start)}`,
        );
        setVideoSrc(p.url);
      } catch (e) {
        setError(
          e instanceof ApiError ? e.message : "Gagal memuat URL playback",
        );
      }
    },
    [streamId],
  );

  const downloadActive = useCallback(async () => {
    if (!active) return;
    setDownloading(true);
    try {
      const res = await apiFetch(
        `/recordings/${streamId}/file?start=${encodeURIComponent(active.start)}&end=${encodeURIComponent(active.end)}`,
      );
      if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `rekaman-${streamId}-${active.start.replace(/[:.]/g, "-")}.mp4`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal mengunduh");
    } finally {
      setDownloading(false);
    }
  }, [active, streamId]);

  const dayStart = useMemo(() => new Date(`${date}T00:00:00`).getTime(), [date]);
  const frac = useCallback(
    (iso: string) => {
      const t = new Date(iso).getTime();
      return Math.min(1, Math.max(0, (t - dayStart) / DAY_MS));
    },
    [dayStart],
  );

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-white">
          {streamName}
        </span>
        <button
          onClick={load}
          disabled={phase === "loading"}
          className="h-9 shrink-0 rounded-lg bg-ink-800 px-3 text-xs font-medium text-neutral-200 ring-1 ring-white/10 transition hover:bg-ink-700 active:scale-95 disabled:opacity-50"
        >
          {phase === "loading" ? "Memuat…" : "Muat"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-bad-400">
          {error}
        </div>
      )}

      {phase === "idle" && (
        <div className="rounded-2xl bg-ink-900 px-6 py-10 text-center text-xs text-neutral-500 ring-1 ring-white/10">
          Menyiapkan linimasa…
        </div>
      )}

      {phase === "loading" && (
        <div className="animate-pulse rounded-2xl bg-ink-900 p-4 ring-1 ring-white/10 motion-reduce:animate-none">
          <div className="h-10 rounded-xl bg-ink-800" />
          <div className="mt-3 aspect-video rounded-xl bg-ink-800" />
        </div>
      )}

      {phase === "not-implemented" && (
        <div className="rounded-2xl bg-ink-900 px-6 py-10 text-center text-xs text-neutral-500 ring-1 ring-white/10">
          Linimasa rekaman tersedia mulai Fase 3.
        </div>
      )}

      {phase === "error" && !error && (
        <div className="rounded-2xl bg-ink-900 px-6 py-10 text-center text-xs text-neutral-500 ring-1 ring-white/10">
          Terjadi kesalahan. Coba muat ulang.
        </div>
      )}

      {phase === "ready" && timeline && (
        <div className="flex flex-col gap-3">
          <Card className="!p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-400">
                {timeline.date}
              </span>
              <span className="rounded-full bg-ink-800 px-2 py-0.5 text-[10px] font-medium text-neutral-400">
                {timeline.entries.length} segmen
              </span>
            </div>
            <div className="relative h-11 overflow-hidden rounded-xl bg-ink-950 ring-1 ring-white/5">
              {Array.from({ length: 25 }).map((_, h) => (
                <span
                  key={h}
                  className="absolute top-0 h-full w-px bg-white/5"
                  style={{ left: `${(h / 24) * 100}%` }}
                />
              ))}
              {timeline.entries.map((e, i) => {
                const left = frac(e.start) * 100;
                const width = Math.max(0.4, (frac(e.end) - frac(e.start)) * 100);
                const isActive = active?.start === e.start;
                return (
                  <button
                    key={i}
                    onClick={() => playEntry(e)}
                    title={`${fmtTime(e.start)} – ${fmtTime(e.end)}${e.has_event ? " · ada event" : ""}`}
                    aria-label={`Putar segmen ${fmtTime(e.start)}`}
                    className={`absolute top-1.5 h-8 rounded-md transition ${
                      isActive
                        ? "bg-accent-400"
                        : e.has_event
                          ? "bg-warn-400/80 hover:bg-warn-400"
                          : "bg-accent-600/60 hover:bg-accent-500"
                    }`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                  />
                );
              })}
              {timeline.entries.length === 0 && (
                <div className="flex h-full items-center justify-center text-[11px] text-neutral-500">
                  Tidak ada rekaman pada tanggal ini
                </div>
              )}
            </div>
          </Card>

          <div className="nv-stage overflow-hidden rounded-2xl bg-ink-900 ring-1 ring-white/10">
            {videoSrc ? (
              <video
                ref={videoRef}
                key={videoSrc}
                src={videoSrc}
                controls
                playsInline
                className="aspect-video w-full bg-black"
              />
            ) : (
              <div className="flex aspect-video flex-col items-center justify-center gap-2 px-6 text-center">
                <svg
                  width="28"
                  height="28"
                  viewBox="0 0 20 20"
                  fill="none"
                  className="text-neutral-700"
                  aria-hidden
                >
                  <path
                    d="M6 4.5v11l9-5.5-9-5.5z"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <p className="text-xs text-neutral-500">
                  {active
                    ? "Memuat video…"
                    : "Klik salah satu segmen pada linimasa untuk memutar."}
                </p>
              </div>
            )}
            {active && (
              <div className="flex items-center justify-between gap-2 border-t border-white/10 px-3 py-2.5">
                <span className="truncate text-xs text-neutral-300">
                  {fmtTime(active.start)} – {fmtTime(active.end)}
                  {active.has_event && (
                    <span className="ml-2 rounded-full bg-warn-400/15 px-2 py-0.5 text-[10px] font-medium text-warn-400">
                      Event
                    </span>
                  )}
                </span>
                <button
                  onClick={downloadActive}
                  disabled={downloading}
                  className="flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-ink-800 px-3 text-xs font-medium text-neutral-200 ring-1 ring-white/10 transition hover:bg-ink-700 active:scale-95 disabled:opacity-50"
                >
                  {downloading ? "Mengunduh…" : "Unduh"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* Halaman Putar Ulang: satu kamera (default) atau multi-kamera 2×2/3×3/4×4. */
export default function PlaybackPage() {
  const router = useRouter();
  const { user, loading } = useAuth();

  const [streams, setStreams] = useState<Stream[]>([]);
  const [multi, setMulti] = useState(false);
  const [streamId, setStreamId] = useState<string>("");
  const [multiIds, setMultiIds] = useState<number[]>([]);
  const [gridCols, setGridCols] = useState(2);
  const [date, setDate] = useState(todayStr());

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
      return;
    }
    if (user) {
      api
        .get<Stream[]>("/streams")
        .then((s) => {
          setStreams(s);
          if (s.length > 0) {
            setStreamId(String(s[0].id));
            setMultiIds([s[0].id]);
          }
        })
        .catch(() => {
          /* daftar kamera opsional */
        });
    }
  }, [loading, user, router]);

  const toggleMultiId = (id: number) => {
    setMultiIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const byId = useMemo(() => new Map(streams.map((s) => [s.id, s])), [streams]);

  if (loading || (!user && !loading)) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-ink-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/15 border-t-accent-400 motion-reduce:animate-none" />
      </div>
    );
  }

  const selectedStreams = multi
    ? multiIds
        .map((id) => byId.get(id))
        .filter((s): s is Stream => !!s)
    : byId.get(Number(streamId))
      ? [byId.get(Number(streamId)) as Stream]
      : [];

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-4 py-5 md:px-6 md:py-7">
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Putar Ulang
        </h1>
        <p className="mb-5 mt-1 text-sm text-neutral-400">
          Pilih kamera dan tanggal, lalu muat linimasa rekaman.
        </p>

        {/* Kontrol */}
        <Card className="mb-4">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
              {!multi ? (
                <label className="flex flex-1 flex-col gap-1.5">
                  <span className="text-xs font-medium text-neutral-400">
                    Kamera
                  </span>
                  <select
                    value={streamId}
                    onChange={(e) => setStreamId(e.target.value)}
                    className="h-11 rounded-xl border border-ink-700 bg-ink-950 px-3 text-base text-white outline-none transition-colors focus:border-accent-500"
                  >
                    {streams.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <div className="flex flex-1 flex-col gap-1.5">
                  <span className="text-xs font-medium text-neutral-400">
                    Kamera ({multiIds.length} dipilih)
                  </span>
                  <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto rounded-xl bg-ink-950/60 p-2 ring-1 ring-white/5">
                    {streams.map((s) => {
                      const on = multiIds.includes(s.id);
                      return (
                        <button
                          key={s.id}
                          onClick={() => toggleMultiId(s.id)}
                          aria-pressed={on}
                          className={`flex h-10 items-center gap-2 rounded-full px-3.5 text-xs font-medium transition active:scale-95 ${
                            on
                              ? "bg-accent-600 text-onaccent"
                              : "bg-ink-800 text-neutral-300 ring-1 ring-white/10 hover:bg-ink-700"
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                          />
                          {s.name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-neutral-400">
                  Tanggal
                </span>
                <input
                  type="date"
                  value={date}
                  max={todayStr()}
                  onChange={(e) => setDate(e.target.value)}
                  className="h-11 rounded-xl border border-ink-700 bg-ink-950 px-3 text-base text-white outline-none transition-colors focus:border-accent-500"
                />
              </label>
              <button
                onClick={() => setMulti((v) => !v)}
                aria-pressed={multi}
                className={`h-11 shrink-0 rounded-xl px-5 text-sm font-semibold transition active:scale-95 ${
                  multi
                    ? "bg-accent-600 text-onaccent hover:bg-accent-500"
                    : "bg-ink-800 text-neutral-200 ring-1 ring-white/10 hover:bg-ink-700"
                }`}
              >
                {multi ? "Multi aktif" : "Multi kamera"}
              </button>
            </div>
            {multi && (
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-neutral-400">
                  Grid:
                </span>
                <div
                  className="flex items-center gap-1 rounded-full bg-ink-950 p-1 ring-1 ring-white/10"
                  role="tablist"
                  aria-label="Tata letak grid playback"
                >
                  {GRID_OPTS.map((g) => (
                    <button
                      key={g.cols}
                      role="tab"
                      aria-selected={gridCols === g.cols}
                      onClick={() => setGridCols(g.cols)}
                      className={`flex h-9 min-w-[52px] items-center justify-center rounded-full px-3 text-xs font-semibold transition active:scale-95 ${
                        gridCols === g.cols
                          ? "bg-accent-600 text-onaccent"
                          : "text-neutral-400 hover:text-white"
                      }`}
                    >
                      {g.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* Panel-panel playback */}
        {selectedStreams.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-2xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <p className="text-sm text-neutral-400">
              {multi
                ? "Pilih minimal satu kamera untuk memutar ulang."
                : "Belum ada kamera."}
            </p>
          </div>
        ) : (
          <div
            className={`grid grid-cols-1 gap-5 ${multi ? (GRID_CLASS[gridCols] ?? GRID_CLASS[2]) : "mx-auto max-w-3xl"}`}
          >
            {selectedStreams.map((s) => (
              <PlaybackPanel
                key={s.id}
                streamId={s.id}
                streamName={s.name}
                date={date}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
