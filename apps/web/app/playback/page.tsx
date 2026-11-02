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
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/15 border-t-accent-400 motion-reduce:animate-none" />
      </div>
    );
  }

  const streamName = streams.find((s) => String(s.id) === streamId)?.name;

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl px-4 py-5 md:px-6 md:py-7">
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Putar Ulang
        </h1>
        <p className="mb-5 mt-1 text-sm text-neutral-400">
          Pilih kamera dan tanggal, lalu muat linimasa rekaman.
        </p>

        {/* Kontrol */}
        <Card className="mb-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
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
              onClick={load}
              disabled={!streamId || phase === "loading"}
              className="h-11 shrink-0 rounded-xl bg-accent-600 px-6 text-sm font-semibold text-onaccent transition hover:bg-accent-500 active:scale-95 disabled:opacity-50"
            >
              {phase === "loading" ? "Memuat…" : "Muat linimasa"}
            </button>
          </div>
        </Card>

        {error && (
          <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-bad-400">
            {error}
          </div>
        )}

        {/* Status */}
        {phase === "idle" && (
          <div className="flex flex-col items-center gap-3 rounded-2xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <svg
              width="36"
              height="36"
              viewBox="0 0 24 24"
              fill="none"
              className="text-neutral-600"
              aria-hidden
            >
              <path
                d="M12 8v4l2.5 2.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <p className="text-sm text-neutral-400">
              Pilih kamera dan tanggal, lalu tekan{" "}
              <span className="font-medium text-neutral-200">Muat linimasa</span>.
            </p>
          </div>
        )}

        {phase === "loading" && (
          <div className="animate-pulse rounded-2xl bg-ink-900 p-5 ring-1 ring-white/10 motion-reduce:animate-none">
            <div className="mb-3 h-4 w-40 rounded bg-ink-700" />
            <div className="h-12 rounded-xl bg-ink-800" />
            <div className="mt-4 aspect-video rounded-xl bg-ink-800" />
          </div>
        )}

        {phase === "not-implemented" && (
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
                d="M6 4.5v11l9-5.5-9-5.5z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <p className="text-sm font-medium text-neutral-200">
              Linimasa rekaman tersedia mulai Fase 3
            </p>
            <p className="max-w-sm text-xs leading-relaxed text-neutral-500">
              API <span className="font-mono">/api/recordings</span> belum
              diimplementasikan. Halaman ini sudah siap disambung tanpa
              perubahan besar — tidak ada data palsu yang ditampilkan.
            </p>
          </div>
        )}

        {phase === "error" && !error && (
          <div className="rounded-2xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
            <p className="text-sm text-neutral-400">
              Terjadi kesalahan. Coba muat ulang.
            </p>
          </div>
        )}

        {/* Linimasa + player (aktif saat Fase 3) */}
        {phase === "ready" && timeline && (
          <div className="flex flex-col gap-4">
            <Card className="!p-4">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-medium text-neutral-200">
                  {streamName} · {timeline.date}
                </span>
                <span className="rounded-full bg-ink-800 px-2.5 py-1 text-[11px] font-medium text-neutral-400">
                  {timeline.entries.length} segmen
                </span>
              </div>
              {/* Bilah 24 jam */}
              <div className="relative h-12 overflow-hidden rounded-xl bg-ink-950 ring-1 ring-white/5">
                {Array.from({ length: 25 }).map((_, h) => (
                  <span
                    key={h}
                    className="absolute top-0 h-full w-px bg-white/5"
                    style={{ left: `${(h / 24) * 100}%` }}
                  />
                ))}
                {timeline.entries.map((e, i) => {
                  const left = frac(e.start) * 100;
                  const width = Math.max(
                    0.4,
                    (frac(e.end) - frac(e.start)) * 100,
                  );
                  const isActive = active?.start === e.start;
                  return (
                    <button
                      key={i}
                      onClick={() => playEntry(e)}
                      title={`${fmtTime(e.start)} – ${fmtTime(e.end)}${e.has_event ? " · ada event" : ""}`}
                      aria-label={`Putar segmen ${fmtTime(e.start)}`}
                      className={`absolute top-1.5 h-9 rounded-md transition ${
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
                  <div className="flex h-full items-center justify-center text-xs text-neutral-500">
                    Tidak ada rekaman pada tanggal ini
                  </div>
                )}
              </div>
              <div className="mt-1.5 flex justify-between text-[10px] text-neutral-600">
                <span>00:00</span>
                <span>06:00</span>
                <span>12:00</span>
                <span>18:00</span>
                <span>24:00</span>
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
                    width="32"
                    height="32"
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
                <div className="flex items-center justify-between gap-3 border-t border-white/10 px-4 py-3">
                  <span className="text-sm text-neutral-300">
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
                    className="flex h-11 items-center gap-2 rounded-xl bg-ink-800 px-4 text-sm font-medium text-neutral-200 ring-1 ring-white/10 transition hover:bg-ink-700 active:scale-95 disabled:opacity-50"
                  >
                    <svg
                      width="15"
                      height="15"
                      viewBox="0 0 16 16"
                      fill="none"
                      aria-hidden
                    >
                      <path
                        d="M8 2v8M4.5 7L8 10.5 11.5 7M2.5 13.5h11"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
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
