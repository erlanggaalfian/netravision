"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "../../components/AppShell";
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

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

/* Shell UI playback. API rekaman = Fase 3: struktur siap disambung tanpa refactor. */
export default function PlaybackPage() {
  const router = useRouter();
  const { user, loading } = useAuth();

  const [streams, setStreams] = useState<Stream[]>([]);
  const [streamId, setStreamId] = useState<string>("");
  const [date, setDate] = useState(todayStr());
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [active, setActive] = useState<TimelineEntry | null>(null);
  const [videoSrc, setVideoSrc] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

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
          if (s.length > 0) setStreamId(String(s[0].id));
        })
        .catch(() => {
          /* daftar kamera opsional di sini; error tampil saat Muat */
        });
    }
  }, [loading, user, router]);

  const load = useCallback(async () => {
    if (!streamId) return;
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
        /* Endpoint belum ada — Fase 3. Tampilkan jujur, bukan data palsu. */
        setPhase("not-implemented");
      } else {
        setError(e instanceof ApiError ? e.message : "Gagal memuat linimasa");
        setPhase("error");
      }
    }
  }, [streamId, date]);

  /* Klik segmen → minta playback-url → putar. (Aktif penuh saat Fase 3.) */
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

  /* Unduh potongan segmen aktif. (Aktif penuh saat Fase 3.) */
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

  if (loading || (!user && !loading)) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-ink-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/15 border-t-accent-400" />
      </div>
    );
  }

  const streamName = streams.find((s) => String(s.id) === streamId)?.name;

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl px-4 py-4 md:px-6 md:py-6">
        <h1 className="mb-1 text-lg font-bold text-white md:text-xl">
          Putar Ulang
        </h1>
        <p className="mb-4 text-xs text-neutral-400">
          Pilih kamera dan tanggal, lalu muat linimasa rekaman.
        </p>

        {/* Kontrol */}
        <div className="mb-4 flex flex-col gap-3 rounded-xl bg-ink-900 p-4 ring-1 ring-white/10 sm:flex-row sm:items-end">
          <label className="flex flex-1 flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-neutral-500">
              Kamera
            </span>
            <select
              value={streamId}
              onChange={(e) => setStreamId(e.target.value)}
              className="h-10 rounded-lg bg-ink-800 px-3 text-sm text-white ring-1 ring-white/10 focus:outline-none focus:ring-2 focus:ring-accent-500"
            >
              {streams.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-neutral-500">
              Tanggal
            </span>
            <input
              type="date"
              value={date}
              max={todayStr()}
              onChange={(e) => setDate(e.target.value)}
              className="h-10 rounded-lg bg-ink-800 px-3 text-sm text-white ring-1 ring-white/10 focus:outline-none focus:ring-2 focus:ring-accent-500 [color-scheme:dark]"
            />
          </label>
          <button
            onClick={load}
            disabled={!streamId || phase === "loading"}
            className="h-10 shrink-0 rounded-lg bg-accent-600 px-5 text-sm font-medium text-white transition hover:bg-accent-500 active:scale-95 disabled:opacity-50"
          >
            {phase === "loading" ? "Memuat…" : "Muat"}
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-bad-400/10 px-4 py-3 text-xs text-bad-400 ring-1 ring-bad-400/30">
            {error}
          </div>
        )}

        {/* Status */}
        {phase === "idle" && (
          <div className="rounded-xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <p className="text-sm text-neutral-400">
              Pilih kamera dan tanggal, lalu tekan{" "}
              <span className="font-medium text-neutral-200">Muat</span>.
            </p>
          </div>
        )}

        {phase === "loading" && (
          <div className="animate-pulse rounded-xl bg-ink-900 p-4 ring-1 ring-white/10">
            <div className="mb-3 h-4 w-40 rounded bg-ink-700" />
            <div className="h-10 rounded bg-ink-800" />
            <div className="mt-4 aspect-video rounded bg-ink-800" />
          </div>
        )}

        {phase === "not-implemented" && (
          <div className="flex flex-col items-center gap-2 rounded-xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <svg width="40" height="40" viewBox="0 0 20 20" fill="none" className="text-neutral-600">
              <path
                d="M6 4.5v11l9-5.5-9-5.5z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <p className="text-sm font-medium text-neutral-300">
              Linimasa rekaman tersedia mulai Fase 3
            </p>
            <p className="max-w-sm text-xs text-neutral-500">
              API <span className="font-mono">/api/recordings</span> belum
              diimplementasikan. Halaman ini sudah siap disambung tanpa
              perubahan besar — tidak ada data palsu yang ditampilkan.
            </p>
          </div>
        )}

        {phase === "error" && !error && (
          <div className="rounded-xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <p className="text-sm text-neutral-400">
              Terjadi kesalahan. Coba muat ulang.
            </p>
          </div>
        )}

        {/* Linimasa + player (aktif saat Fase 3) */}
        {phase === "ready" && timeline && (
          <div className="flex flex-col gap-4">
            <div className="rounded-xl bg-ink-900 p-4 ring-1 ring-white/10">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-neutral-300">
                  {streamName} · {timeline.date}
                </span>
                <span className="text-[11px] text-neutral-500">
                  {timeline.entries.length} segmen
                </span>
              </div>
              {/* Bilah 24 jam */}
              <div className="relative h-10 overflow-hidden rounded-md bg-ink-800">
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
                      className={`absolute top-1 h-8 rounded-sm transition ${
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
              <div className="mt-1 flex justify-between text-[10px] text-neutral-600">
                <span>00:00</span>
                <span>06:00</span>
                <span>12:00</span>
                <span>18:00</span>
                <span>24:00</span>
              </div>
            </div>

            <div className="overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/10">
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
                <div className="flex aspect-video items-center justify-center px-6 text-center">
                  <p className="text-xs text-neutral-500">
                    {active
                      ? "Memuat video…"
                      : "Klik salah satu segmen pada linimasa untuk memutar."}
                  </p>
                </div>
              )}
              {active && (
                <div className="flex items-center justify-between gap-3 px-4 py-3">
                  <span className="text-xs text-neutral-400">
                    {fmtTime(active.start)} – {fmtTime(active.end)}
                    {active.has_event && (
                      <span className="ml-2 rounded-full bg-warn-400/15 px-2 py-0.5 text-[10px] text-warn-400">
                        Event
                      </span>
                    )}
                  </span>
                  <button
                    onClick={downloadActive}
                    disabled={downloading}
                    className="rounded-lg bg-ink-800 px-3 py-2 text-xs font-medium text-neutral-200 ring-1 ring-white/10 transition hover:bg-ink-700 active:scale-95 disabled:opacity-50"
                  >
                    {downloading ? "Mengunduh…" : "Unduh potongan"}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
