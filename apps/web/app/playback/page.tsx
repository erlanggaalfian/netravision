"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "../../components/AppShell";
import { Button, Card, ErrorBox, GridIcon, SectionTitle, Spinner } from "../../components/ui";
import { Dropdown } from "../../components/Dropdown";
import { api, apiFetch, ApiError, usePosterUrl } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import type { AdConfig, Stream } from "../../lib/types";
import { AdBanner } from "../../components/AdBanner";

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
  { cols: 1, label: "1×1" },
  { cols: 2, label: "2×2" },
  { cols: 3, label: "3×3" },
  { cols: 4, label: "4×4" },
];

/* Samakan dengan Live: di md+ jumlah kolom = gridCols (3x3 jadi 3 kolom
   di md, bukan baru di lg; 4x4 jadi 4 kolom di md, bukan baru di xl). */
const GRID_CLASS: Record<number, string> = {
  1: "md:grid-cols-1",
  2: "md:grid-cols-2",
  3: "md:grid-cols-3",
  4: "md:grid-cols-4",
};

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/* Jam:menit dari timestamp (waktu lokal). */
function fmtClock(ms: number): string {
  return new Date(ms).toLocaleTimeString("id-ID", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/* Jam:menit:detik dari timestamp (waktu lokal). */
function fmtClockSec(ms: number): string {
  return new Date(ms).toLocaleTimeString("id-ID", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/* Total durasi rekaman sehari, mis. "45 mnt rekaman" / "2 jam 10 mnt rekaman". */
function fmtDuration(ms: number): string {
  const totalMin = Math.round(ms / 60000);
  if (totalMin < 60) return `${totalMin} mnt rekaman`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m === 0 ? `${h} jam rekaman` : `${h} jam ${m} mnt rekaman`;
}
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/* Kartu kosong: panel modern, ikon gradient + glow. Pakai nested=true bila
   sudah berada di dalam panel, supaya tidak ada panel ganda. */
function EmptyCard({ title, desc, nested = false }: { title: string; desc: string; nested?: boolean }) {
  return (
    <div className={`${nested ? "" : "nv-panel-modern "}px-6 py-12 text-center`}>
      <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-b from-accent-500 to-accent-600 text-onaccent shadow-[0_8px_24px_-8px_var(--nv-accent-500)]">
        <svg
          width="28"
          height="28"
          viewBox="0 0 20 20"
          fill="none"
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
      </div>
      <p className="text-lg font-extrabold tracking-tight text-slate-100">{title}</p>
      <p className="mx-auto mt-1.5 max-w-xs text-[13px] leading-relaxed text-slate-400">
        {desc}
      </p>
    </div>
  );
}

/* Satu panel playback mandiri: satu kamera, tanggal dari induk. */
function PlaybackPanel({
  streamId,
  streamName,
  isOnline,
  date,
  posterUrl,
  ad,
}: {
  streamId: number;
  streamName: string;
  isOnline: boolean;
  date: string;
  posterUrl: string | null;
  ad: AdConfig | null;
}) {
  /* Poster terbaru kamera (blob object URL, header Authorization),
     pola sama seperti CameraTile. */
  const posterSrc = usePosterUrl(posterUrl);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [active, setActive] = useState<TimelineEntry | null>(null);
  const [videoSrc, setVideoSrc] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [urlLoading, setUrlLoading] = useState(false);
  /* Unduh rentang: jam mulai/selesai (datetime-local), default mengikuti
     segmen aktif. */
  const [rangeStart, setRangeStart] = useState("");
  const [rangeEnd, setRangeEnd] = useState("");
  const [rangeDownloading, setRangeDownloading] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  /* Object URL segmen yang sedang diputar (blob via apiFetch): dicabut
     saat ganti segmen / unmount supaya tidak bocor memori. */
  const videoObjectUrlRef = useRef<string | null>(null);
  const revokeVideoObjectUrl = useCallback(() => {
    if (videoObjectUrlRef.current) {
      URL.revokeObjectURL(videoObjectUrlRef.current);
      videoObjectUrlRef.current = null;
    }
  }, []);

  useEffect(() => revokeVideoObjectUrl, [revokeVideoObjectUrl]);
  /* Putar berkelanjutan: segmen habis langsung lanjut ke segmen berikut
     tanpa jeda (selalu aktif, tidak ada tombol). Segmen berikut diunduh
     duluan (prefetch) selagi segmen aktif diputar, supaya pindah segmen
     nyaris tanpa jeda. */
  const prefetchRef = useRef<{
    start: string;
    promise: Promise<string>;
  } | null>(null);
  /* Posisi awal (detik) di dalam segmen saat lompat ke jam tertentu
     lewat linimasa; diterapkan saat metadata video sudah dimuat. */
  const seekOffsetRef = useRef(0);
  /* Tooltip hover linimasa: jam:menit di posisi kursor. */
  const [hoverTime, setHoverTime] = useState<{
    xPct: number;
    label: string;
  } | null>(null);
  /* Posisi putar saat ini (ms sejak 00:00) untuk playhead + jam berjalan. */
  const [playheadMs, setPlayheadMs] = useState<number | null>(null);
  /* Cabut prefetch yang tidak jadi dipakai (mis. user pindah segmen). */
  const dropPrefetch = useCallback(() => {
    const pre = prefetchRef.current;
    prefetchRef.current = null;
    if (pre) {
      pre.promise.then((u) => URL.revokeObjectURL(u)).catch(() => {});
    }
  }, []);

  useEffect(() => dropPrefetch, [dropPrefetch]);
  /* Nomor urutan: hanya respons terbaru load linimasa / fetch URL
     playback yang dipakai, respons kedaluwarsa diabaikan. */
  const loadSeqRef = useRef(0);
  const playSeqRef = useRef(0);
  const hasTimelineRef = useRef(false);
  /* Sinyal iklan: hover panel + klik/fokus pada area video saja (bukan
     tombol, segmen, atau unduhan). */
  const [panelHovered, setPanelHovered] = useState(false);
  const [adClickTick, setAdClickTick] = useState(0);

  const load = useCallback(async () => {
    const mySeq = ++loadSeqRef.current;
    setPhase("loading");
    setError(null);
    /* Jangan kosongkan timeline/active/videoSrc sebelum fetch berhasil:
       Muat ulang saat sedang menonton tidak boleh menghilangkan video
       yang sedang diputar bila reload kemudian gagal. */
    try {
      const t = await api.get<TimelineData>(
        `/recordings/${streamId}/timeline?date=${date}`,
      );
      if (mySeq !== loadSeqRef.current) return;
      setTimeline(t);
      hasTimelineRef.current = true;
      setPhase("ready");
    } catch (e) {
      if (mySeq !== loadSeqRef.current) return;
      if (e instanceof ApiError && e.status === 404) {
        /* Endpoint timeline sudah ada; 404 berarti kamera tidak
           ditemukan, bukan fitur belum tersedia. */
        setError("Kamera tidak ditemukan");
        setPhase(hasTimelineRef.current ? "ready" : "not-implemented");
      } else {
        setError(e instanceof ApiError ? e.message : "Gagal memuat linimasa");
        setPhase(hasTimelineRef.current ? "ready" : "error");
      }
    }
  }, [streamId, date]);

  /* Kamera/tanggal berganti: linimasa lama bukan lagi acuan, jadi
     kegagalan load berikutnya tidak boleh kembali ke fase ready. */
  useEffect(() => {
    hasTimelineRef.current = false;
  }, [streamId, date]);

  useEffect(() => {
    load();
  }, [load]);

  /* Unduh satu segmen jadi blob object URL (dipakai putar + prefetch).
     <video> tidak bisa mengirim header Authorization (token ada di
     localStorage), jadi segmen diunduh lewat apiFetch lalu diputar dari
     blob object URL. Pola yang sama dengan poster kamera, bukan ?token=
     di URL. */
  const fetchSegmentBlob = useCallback(
    async (entry: TimelineEntry): Promise<string> => {
      const p = await api.get<PlaybackUrl>(
        `/recordings/${streamId}/playback-url?time=${encodeURIComponent(entry.start)}`,
      );
      /* Hormati expires_at: URL yang sudah kedaluwarsa jangan dipakai. */
      if (p.expires_at && new Date(p.expires_at).getTime() <= Date.now()) {
        throw new ApiError(
          410,
          "Tautan rekaman sudah kedaluwarsa, coba putar lagi segmen ini.",
        );
      }
      const path = p.url.startsWith("/api/") ? p.url.slice(4) : p.url;
      const res = await apiFetch(path);
      if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    },
    [streamId],
  );

  /* Unduh segmen berikut di latar belakang selagi segmen aktif diputar. */
  const prefetchNext = useCallback(
    (entry: TimelineEntry) => {
      if (!timeline) return;
      const idx = timeline.entries.findIndex((e) => e.start === entry.start);
      const next = timeline.entries[idx + 1];
      if (!next) return;
      if (prefetchRef.current?.start === next.start) return;
      const promise = fetchSegmentBlob(next);
      prefetchRef.current = { start: next.start, promise };
      promise.catch(() => {
        if (prefetchRef.current?.start === next.start) {
          prefetchRef.current = null;
        }
        /* Prefetch gagal: segmen berikut tetap bisa diputar, diunduh
           saat dipilih. */
      });
    },
    [timeline, fetchSegmentBlob],
  );

  const playEntry = useCallback(
    async (entry: TimelineEntry, offsetSec = 0) => {
      const mySeq = ++playSeqRef.current;
      setActive(entry);
      seekOffsetRef.current = offsetSec;
      revokeVideoObjectUrl();
      setVideoSrc(null);
      setVideoError(null);
      setUrlLoading(true);
      try {
        let objectUrl: string;
        /* Pakai hasil prefetch bila segmen ini sudah diunduh duluan. */
        const pre = prefetchRef.current;
        if (pre && pre.start === entry.start) {
          prefetchRef.current = null;
          objectUrl = await pre.promise;
        } else {
          /* Prefetch lama tidak dipakai lagi (user pindah segmen). */
          dropPrefetch();
          objectUrl = await fetchSegmentBlob(entry);
        }
        if (mySeq !== playSeqRef.current) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        videoObjectUrlRef.current = objectUrl;
        setVideoSrc(objectUrl);
        setPlayheadMs(new Date(entry.start).getTime());
        prefetchNext(entry);
      } catch (e) {
        if (mySeq !== playSeqRef.current) return;
        setError(
          e instanceof ApiError ? e.message : "Gagal memuat URL playback",
        );
      } finally {
        if (mySeq === playSeqRef.current) setUrlLoading(false);
      }
    },
    [fetchSegmentBlob, prefetchNext, dropPrefetch, revokeVideoObjectUrl],
  );

  /* Segmen habis: lanjut otomatis ke segmen berikut. */
  const handleVideoEnded = useCallback(() => {
    if (!timeline || !active) return;
    const idx = timeline.entries.findIndex((e) => e.start === active.start);
    const next = timeline.entries[idx + 1];
    if (next) playEntry(next);
  }, [timeline, active, playEntry]);

  /* Metadata video dimuat: terapkan posisi awal bila lompat dari linimasa. */
  const handleLoadedMetadata = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    const off = seekOffsetRef.current;
    seekOffsetRef.current = 0;
    if (off > 0 && off < v.duration) v.currentTime = off;
  }, []);

  /* Jam berjalan selama video diputar (untuk playhead + header). */
  const handleTimeUpdate = useCallback(() => {
    const v = videoRef.current;
    if (!v || !active) return;
    setPlayheadMs(new Date(active.start).getTime() + v.currentTime * 1000);
  }, [active]);

  /* Lompat ke jam tertentu di linimasa: cari segmen yang memuat jam itu
     lalu putar dari posisi di dalam segmen. */
  const seekToTime = useCallback(
    (timeMs: number) => {
      if (!timeline) return;
      const at = new Date(timeMs);
      const entry = timeline.entries.find((e) => {
        const s = new Date(e.start).getTime();
        const en = new Date(e.end).getTime();
        return s <= timeMs && timeMs < en;
      });
      if (entry) {
        const off = Math.max(
          0,
          (timeMs - new Date(entry.start).getTime()) / 1000,
        );
        playEntry(entry, off);
        return;
      }
      /* Di celah tanpa rekaman: putar segmen pertama sesudah jam itu. */
      const next = timeline.entries.find(
        (e) => new Date(e.start).getTime() > timeMs,
      );
      if (next) playEntry(next);
    },
    [timeline, playEntry],
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
      /* Revoke setelah unduhan sempat mulai, revoke langsung bisa
         membatalkan unduhan di sebagian browser. */
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal mengunduh");
    } finally {
      setDownloading(false);
    }
  }, [active, streamId]);

  /* Jam rentang mengikuti segmen aktif saat segmen berganti. */
  useEffect(() => {
    if (!active) return;
    setRangeStart(toLocalInput(active.start));
    setRangeEnd(toLocalInput(active.end));
  }, [active]);

  const downloadRange = useCallback(async () => {
    if (!rangeStart || !rangeEnd) {
      setError("Isi jam mulai dan jam selesai dulu.");
      return;
    }
    if (new Date(rangeEnd).getTime() <= new Date(rangeStart).getTime()) {
      setError("Jam selesai harus setelah jam mulai.");
      return;
    }
    if (
      new Date(rangeEnd).getTime() - new Date(rangeStart).getTime() >
      2 * 60 * 60 * 1000
    ) {
      setError("Rentang maksimal 2 jam per unduhan.");
      return;
    }
    setRangeDownloading(true);
    try {
      const res = await apiFetch(
        `/recordings/${streamId}/download-range?start=${encodeURIComponent(rangeStart)}&end=${encodeURIComponent(rangeEnd)}`,
      );
      if (!res.ok) {
        const msg =
          res.status === 404
            ? "Tidak ada rekaman pada rentang itu."
            : `HTTP ${res.status}`;
        throw new ApiError(res.status, msg);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `rekaman-${streamId}-${rangeStart.replace(/[:.]/g, "-")}-sd-${rangeEnd.replace(/[:.]/g, "-")}.mp4`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal mengunduh rentang");
    } finally {
      setRangeDownloading(false);
    }
  }, [rangeStart, rangeEnd, streamId]);

  const dayStart = useMemo(() => new Date(`${date}T00:00:00`).getTime(), [date]);
  const frac = useCallback(
    (iso: string) => {
      const t = new Date(iso).getTime();
      return Math.min(1, Math.max(0, (t - dayStart) / DAY_MS));
    },
    [dayStart],
  );

  return (
    <div
      className="nv-panel-modern min-w-0 overflow-hidden"
      onMouseEnter={() => setPanelHovered(true)}
      onMouseLeave={() => setPanelHovered(false)}
    >
      {/* Header panel: dot status + nama kamera + Muat ulang, di dalam panel */}
      <div className="flex items-center justify-between gap-2 border-b border-ink-800 px-4 py-3">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${isOnline ? "bg-ok-400" : "bg-bad-400"}`}
          aria-label={isOnline ? "Online" : "Offline"}
        />
        <span className="min-w-0 flex-1 truncate text-base font-extrabold tracking-tight text-slate-100">
          {streamName}
        </span>
        <Button
          variant="subtle"
          className="shrink-0"
          onClick={load}
          disabled={phase === "loading"}
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 16 16"
            fill="none"
            className={phase === "loading" ? "animate-spin motion-reduce:animate-none" : ""}
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
          {phase === "loading" ? "Memuat…" : "Muat ulang"}
        </Button>
      </div>

      {error && (
        <div className="px-4 pt-3">
          <ErrorBox message={error} />
        </div>
      )}

      {phase === "idle" && (
        <div className="p-4">
          <EmptyCard
            nested
            title="Menyiapkan linimasa…"
            desc="Sebentar ya, kami sedang mengambil jadwal rekaman kamera ini."
          />
        </div>
      )}

      {phase === "loading" && (
        <div className="animate-pulse p-4 motion-reduce:animate-none">
          <div className="h-10 rounded-xl bg-ink-800" />
          <div className="mt-3 aspect-video rounded-xl bg-ink-800" />
        </div>
      )}

      {phase === "not-implemented" && (
        <div className="p-4">
          <EmptyCard
            nested
            title={error ? "Kamera tidak ditemukan" : "Linimasa belum tersedia"}
            desc={
              error ??
              "Linimasa rekaman tersedia mulai Fase 3. Coba lagi nanti."
            }
          />
        </div>
      )}

      {phase === "error" && !error && (
        <div className="p-4">
          <EmptyCard
            nested
            title="Terjadi kesalahan"
            desc="Gagal memuat linimasa. Coba muat ulang."
          />
        </div>
      )}

      {phase === "ready" && timeline && (
        <>
          {/* Linimasa: satu track video utuh. Arahkan kursor untuk lihat
              jam:menit di posisi itu, klik untuk lompat ke jam itu. */}
          <div className="border-b border-ink-800 px-4 py-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-400">
                {timeline.date}
              </span>
              <span className="rounded-full bg-ink-800 px-2.5 py-[3px] text-[11px] font-semibold text-slate-400 shadow-sm">
                {fmtDuration(
                  timeline.entries.reduce(
                    (sum, e) =>
                      sum +
                      (new Date(e.end).getTime() -
                        new Date(e.start).getTime()),
                    0,
                  ),
                )}
              </span>
            </div>
            <div
              role="slider"
              aria-label="Linimasa rekaman"
              aria-valuemin={0}
              aria-valuemax={1439}
              aria-valuenow={
                playheadMs !== null
                  ? Math.floor((playheadMs - dayStart) / 60000)
                  : undefined
              }
              aria-valuetext={
                playheadMs !== null ? fmtClock(playheadMs) : undefined
              }
              tabIndex={0}
              onMouseMove={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const xPct = Math.min(
                  1,
                  Math.max(0, (e.clientX - rect.left) / rect.width),
                );
                setHoverTime({
                  xPct: xPct * 100,
                  label: fmtClock(dayStart + xPct * DAY_MS),
                });
              }}
              onMouseLeave={() => setHoverTime(null)}
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const xPct = Math.min(
                  1,
                  Math.max(0, (e.clientX - rect.left) / rect.width),
                );
                seekToTime(dayStart + xPct * DAY_MS);
              }}
              onKeyDown={(e) => {
                if (!playheadMs) return;
                if (e.key === "ArrowRight") {
                  e.preventDefault();
                  seekToTime(playheadMs + 60_000);
                } else if (e.key === "ArrowLeft") {
                  e.preventDefault();
                  seekToTime(playheadMs - 60_000);
                }
              }}
              className="relative h-12 cursor-pointer overflow-hidden rounded-full bg-ink-800 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
            >
              {Array.from({ length: 25 }).map((_, h) => (
                <span
                  key={h}
                  className="pointer-events-none absolute top-0 h-full w-px bg-ink-500/25"
                  style={{ left: `${(h / 24) * 100}%` }}
                />
              ))}
              {/* Daerah yang ada rekamannya: blok-blok segmen berjejer
                  tanpa celah, tampak seperti satu track video. */}
              {timeline.entries.map((e, i) => {
                const left = frac(e.start) * 100;
                const width = Math.max(0.4, (frac(e.end) - frac(e.start)) * 100);
                const isActive = active?.start === e.start;
                return (
                  <span
                    key={i}
                    aria-hidden
                    className={`pointer-events-none absolute top-0.5 h-11 ${
                      isActive
                        ? "bg-gradient-to-r from-accent-600 to-accent-500 shadow-[0_2px_12px_-2px_var(--nv-accent-600)]"
                        : e.has_event
                          ? "bg-warn-400/80"
                          : "bg-accent-600/60"
                    }`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                  />
                );
              })}
              {/* Playhead: garis posisi putar saat ini. */}
              {playheadMs !== null && (
                <span
                  aria-hidden
                  className="pointer-events-none absolute top-0 h-full w-0.5 bg-white shadow-[0_0_6px_rgba(255,255,255,0.9)]"
                  style={{
                    left: `${Math.min(100, Math.max(0, ((playheadMs - dayStart) / DAY_MS) * 100))}%`,
                  }}
                />
              )}
              {/* Tooltip hover: jam:menit di posisi kursor. */}
              {hoverTime && (
                <span
                  aria-hidden
                  className="pointer-events-none absolute top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-md bg-ink-950 px-2 py-1 text-[11px] font-bold tabular-nums whitespace-nowrap text-white shadow-lg ring-1 ring-white/20"
                  style={{ left: `${hoverTime.xPct}%` }}
                >
                  {hoverTime.label}
                </span>
              )}
              {timeline.entries.length === 0 && (
                <div className="flex h-full items-center justify-center text-[11px] text-slate-400">
                  Tidak ada rekaman pada tanggal ini
                </div>
              )}
            </div>
            {/* Label jam pada tick utama (tiap 3 jam). */}
            <div className="relative mt-1.5 h-3.5" aria-hidden>
              {[0, 3, 6, 9, 12, 15, 18, 21].map((h) => (
                <span
                  key={h}
                  className="absolute -translate-x-1/2 text-[10px] font-medium tabular-nums text-slate-400"
                  style={{ left: `${(h / 24) * 100}%` }}
                >
                  {String(h).padStart(2, "0")}
                </span>
              ))}
            </div>
          </div>

          {/* Pratinjau: jam berjalan mengikuti video yang diputar. */}
          <div>
            <div className="flex items-center justify-between gap-2 border-b border-ink-800 px-4 py-3">
              <span className="shrink-0 text-[15px] font-extrabold tracking-tight text-slate-100">Pratinjau</span>
              {playheadMs !== null && (
                <span className="min-w-0 flex-1 truncate text-right text-xs font-medium tabular-nums text-slate-400">
                  {fmtClockSec(playheadMs)}
                </span>
              )}
            </div>
            {/* Area video: klik atau fokus keyboard di sini menaikkan
                sinyal klik iklan, klik tombol/segmen/unduh tidak. */}
            <div
              className="nv-stage"
              onClick={() => setAdClickTick((t) => t + 1)}
              onFocus={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                  setAdClickTick((t) => t + 1);
                }
              }}
            >
              {videoError ? (
                <div className="relative flex aspect-video flex-col items-center justify-center gap-2 overflow-hidden px-6 text-center">
                  {posterSrc && (
                    <img
                      src={posterSrc}
                      alt=""
                      aria-hidden
                      loading="lazy"
                      className="absolute inset-0 h-full w-full object-cover opacity-20"
                    />
                  )}
                  <div className="relative flex flex-col items-center justify-center gap-2">
                    <p className="text-sm font-semibold text-slate-200">
                      Video gagal diputar
                    </p>
                    <p className="text-xs text-slate-400">{videoError}</p>
                    <button
                      onClick={() => active && playEntry(active)}
                      className="mt-1 flex h-11 items-center rounded-xl bg-white/10 px-4 text-xs font-bold text-white transition hover:bg-white/25 active:scale-95"
                    >
                      Coba lagi
                    </button>
                  </div>
                </div>
              ) : videoSrc ? (
                <video
                  ref={videoRef}
                  key={videoSrc}
                  src={videoSrc}
                  poster={posterSrc}
                  controls
                  playsInline
                  autoPlay
                  onEnded={handleVideoEnded}
                  onLoadedMetadata={handleLoadedMetadata}
                  onTimeUpdate={handleTimeUpdate}
                  onError={() =>
                    setVideoError(
                      "Video gagal dimuat, segmen mungkin sudah terhapus atau tautannya kedaluwarsa.",
                    )
                  }
                  className="aspect-video w-full bg-black"
                />
              ) : (
                <div className="relative flex aspect-video flex-col items-center justify-center gap-2 overflow-hidden px-6 text-center">
                  {posterSrc && (
                    <>
                      <img
                        src={posterSrc}
                        alt=""
                        aria-hidden
                        loading="lazy"
                        className="absolute inset-0 h-full w-full object-cover"
                      />
                      <div
                        className="absolute inset-0 bg-black/55"
                        aria-hidden
                      />
                    </>
                  )}
                  <div className="relative flex flex-col items-center justify-center gap-2">
                    <svg
                      width="28"
                      height="28"
                      viewBox="0 0 20 20"
                      fill="none"
                      className="text-slate-400"
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
                    <p className="text-xs text-slate-400">
                      {active
                        ? "Memuat video…"
                        : "Klik salah satu segmen pada linimasa untuk memutar."}
                    </p>
                  </div>
                </div>
              )}
            </div>
            {active && (
              <div className="flex items-center justify-between gap-2 border-t border-ink-800 px-4 py-3">
                <span className="min-w-0 flex-1 truncate text-xs text-slate-400">
                  {active.has_event && (
                    <span className="mr-2 rounded-full bg-warn-400/15 px-2 py-0.5 text-[10px] font-semibold text-warn-400">
                      Event
                    </span>
                  )}
                  {videoError ? "Rekaman gagal diputar" : "Rekaman siap diputar"}
                </span>
                <Button
                  variant="primary"
                  className="shrink-0"
                  onClick={downloadActive}
                  disabled={downloading}
                >
                  {downloading ? "Mengunduh…" : "Unduh"}
                </Button>
              </div>
            )}
            {/* Iklan tepat di bawah video, sebelum bagian unduh. */}
            {ad?.is_active && (
              <AdBanner
                config={ad}
                hovered={panelHovered}
                clickTick={adClickTick}
                placement="below"
              />
            )}
            {/* Unduh rentang: dari jam sekian ke jam sekian, digabung jadi
                satu file MP4. */}
            <div className="border-t border-ink-800 px-4 py-3">
              <p className="mb-2 text-xs font-bold text-slate-200">
                Unduh rentang waktu
              </p>
              <div className="flex flex-wrap items-end gap-2">
                <label className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-[11px] font-medium text-slate-400">
                    Dari
                  </span>
                  <input
                    type="datetime-local"
                    value={rangeStart}
                    onChange={(e) => setRangeStart(e.target.value)}
                    className="h-11 min-w-0 rounded-xl border border-ink-700 bg-ink-800 px-3 text-sm text-slate-100"
                  />
                </label>
                <label className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-[11px] font-medium text-slate-400">
                    Sampai
                  </span>
                  <input
                    type="datetime-local"
                    value={rangeEnd}
                    onChange={(e) => setRangeEnd(e.target.value)}
                    className="h-11 min-w-0 rounded-xl border border-ink-700 bg-ink-800 px-3 text-sm text-slate-100"
                  />
                </label>
                <Button
                  variant="primary"
                  className="shrink-0"
                  onClick={downloadRange}
                  disabled={rangeDownloading || !rangeStart || !rangeEnd}
                >
                  {rangeDownloading ? "Mengunduh…" : "Unduh rentang"}
                </Button>
              </div>
              <p className="mt-2 text-[11px] text-slate-400">
                Maksimal 2 jam per unduhan. Segmen yang ada digabung jadi satu
                file MP4.
              </p>
            </div>
          </div>
        </>
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
  /* Default grid: 3x3 di PC (9 panel per halaman), 2x2 di HP.
     Ditentukan sekali saat halaman dimuat (sama seperti Live). */
  const [gridCols, setGridCols] = useState(() =>
    typeof window !== "undefined" &&
    window.matchMedia("(min-width: 768px)").matches
      ? 3
      : 2,
  );
  const [page, setPage] = useState(1);
  /* Panel kontrol dilipat di HP (tombol filter), selalu tampil di desktop. */
  const [filterOpen, setFilterOpen] = useState(false);
  const [date, setDate] = useState(todayStr());
  /* Config iklan: sekali per halaman, dipakai semua panel. */
  const [ad, setAd] = useState<AdConfig | null>(null);

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
      return;
    }
    if (user) {
      /* Hanya kamera yang benar-benar punya rekaman (playback) yang
         bisa dipilih, lewat /recordings/cameras (bukan semua /streams).
         Dropdown kamera tunggal dan chip multi-kamera sama-sama memakai
         `streams` di bawah, jadi keduanya otomatis terfilter. */
      api
        .get<Stream[]>("/recordings/cameras")
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

  /* Config iklan: sekali per halaman, dipakai semua panel. */
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

  const toggleMultiId = (id: number) => {
    setMultiIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const byId = useMemo(() => new Map(streams.map((s) => [s.id, s])), [streams]);

  /* Ganti grid / mode / kamera terpilih / tanggal: kembali ke halaman 1. */
  useEffect(() => {
    setPage(1);
  }, [gridCols, multi, multiIds, streamId, date]);

  /* Filter tanggal aktif bila tanggal bukan hari ini. */
  const filterActive = date !== todayStr();

  if (loading || (!user && !loading)) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-ink-950">
        <Spinner />
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

  /* Paginasi grid multi-kamera (sama seperti Live): per halaman tampil
     gridCols x gridCols panel (2x2 = 4, 3x3 = 9, 4x4 = 16). Saat
     single-kamera tidak ada paginasi. */
  const perPage = gridCols * gridCols;
  const totalPages = multi
    ? Math.max(1, Math.ceil(selectedStreams.length / perPage))
    : 1;
  const safePage = Math.min(page, totalPages);
  const visibleStreams = multi
    ? selectedStreams.slice((safePage - 1) * perPage, safePage * perPage)
    : selectedStreams;

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-4 py-5 md:px-6 md:py-7">
        <SectionTitle
          title="Putar Ulang"
          desc="Pilih kamera dan tanggal, lalu muat linimasa rekaman."
          action={
            <div className="flex items-center gap-2">
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
                {filterActive && (
                  <span className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-accent-500" />
                )}
              </button>
              <Button
                variant={multi ? "primary" : "subtle"}
                onClick={() => setMulti((v) => !v)}
                aria-pressed={multi}
              >
                Multi kamera
              </Button>
            </div>
          }
        />

        {/* Kontrol: dilipat di HP, tampil di desktop */}
        <Card
          className={`mb-5 ${filterOpen ? "block" : "hidden md:block"}`}
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:gap-3">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end xl:min-w-0 xl:flex-1">
              {!multi ? (
                /* Pemilih kamera: dropdown custom bersama (bukan <select>
                   native). Pembungkus <label> diganti div+span supaya
                   tidak ada interaksi label-tombol yang aneh. */
                <div className="flex flex-1 flex-col gap-1.5">
                  <span className="text-xs font-semibold text-slate-400">
                    Kamera
                  </span>
                  <Dropdown
                    variant="field"
                    options={streams.map((s) => ({ value: String(s.id), label: s.name }))}
                    value={streamId}
                    onChange={setStreamId}
                    ariaLabel="Pilih kamera"
                    placeholder={streams.length === 0 ? "Belum ada kamera" : "Pilih kamera"}
                  />
                </div>
              ) : (
                <div className="flex flex-1 flex-col gap-1.5">
                  <span className="text-xs font-semibold text-slate-400">
                    Kamera ({multiIds.length} dipilih)
                  </span>
                  <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto rounded-xl bg-ink-800 p-2 shadow-sm">
                    {streams.map((s) => {
                      const on = multiIds.includes(s.id);
                      return (
                        <button
                          key={s.id}
                          onClick={() => toggleMultiId(s.id)}
                          aria-pressed={on}
                          className={`flex h-11 min-w-0 items-center gap-2 rounded-full px-3.5 text-xs font-medium transition active:scale-95 ${
                            on
                              ? "bg-gradient-to-r from-accent-600 to-accent-500 font-semibold text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                              : "bg-ink-800 text-slate-300 shadow-sm hover:bg-ink-700 hover:text-slate-200"
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 shrink-0 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                          />
                          <span className="min-w-0 truncate">{s.name}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold text-slate-400">
                  Tanggal
                </span>
                <input
                  type="date"
                  value={date}
                  max={todayStr()}
                  onChange={(e) => setDate(e.target.value)}
                  className="h-11 rounded-xl bg-ink-800 px-4 text-base text-slate-100 shadow-sm outline-none transition-all duration-150 focus:ring-2 focus:ring-accent-500/30"
                />
              </label>
            </div>
            {multi && (
              <div className="hidden items-center gap-2 md:flex">
                <span className="text-xs font-semibold text-slate-400">
                  Grid:
                </span>
                <div
                  className="flex items-center gap-1 rounded-full bg-ink-800 p-1 shadow-sm"
                  role="tablist"
                  aria-label="Tata letak grid playback"
                >
                  {GRID_OPTS.map((g) => (
                    <button
                      key={g.cols}
                      role="tab"
                      aria-selected={gridCols === g.cols}
                      aria-label={`Grid ${g.label}`}
                      title={`Grid ${g.label}`}
                      onClick={() => setGridCols(g.cols)}
                      className={`flex h-11 min-w-[52px] items-center justify-center rounded-full px-3 text-xs font-bold transition-all duration-200 active:scale-95 ${
                        gridCols === g.cols
                          ? "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                          : "text-slate-400 hover:bg-ink-700 hover:text-slate-200"
                      }`}
                    >
                      <GridIcon cols={g.cols} />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* Panel-panel playback */}
        {selectedStreams.length === 0 ? (
          <EmptyCard
            title={multi ? "Belum ada kamera dipilih" : "Belum ada kamera"}
            desc={
              multi
                ? "Pilih minimal satu kamera pada panel filter untuk memutar ulang rekamannya."
                : "Tambahkan kamera terlebih dahulu di menu Admin untuk mulai memutar ulang."
            }
          />
        ) : (
          <>
            <div
              className={`mx-auto grid w-full max-w-5xl grid-cols-1 gap-4 ${multi ? (GRID_CLASS[gridCols] ?? GRID_CLASS[2]) : ""}`}
            >
              {visibleStreams.map((s) => (
                <PlaybackPanel
                  key={s.id}
                  streamId={s.id}
                  streamName={s.name}
                  isOnline={s.is_online}
                  date={date}
                  posterUrl={s.poster_url}
                  ad={ad}
                />
              ))}
            </div>
            {multi && totalPages > 1 && (
              <div className="mt-4 flex items-center justify-center gap-2">
                <Button
                  variant="subtle"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={safePage <= 1}
                  aria-label="Halaman sebelumnya"
                  className="rounded-full"
                >
                  ‹ Sebelumnya
                </Button>
                <span className="text-sm font-semibold text-slate-300">
                  Halaman {safePage} dari {totalPages}
                </span>
                <Button
                  variant="subtle"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={safePage >= totalPages}
                  aria-label="Halaman berikutnya"
                  className="rounded-full"
                >
                  Berikutnya ›
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
