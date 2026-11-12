"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "../../components/AppShell";
import { Button, Card, ErrorBox, GridIcon, SectionTitle, Spinner } from "../../components/ui";
import { api, apiFetch, ApiError } from "../../lib/api";
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

/* Breakpoint sama dengan Live (md, 768px): di bawah md selalu 1 kolom,
   pemilih grid baru tampil di md. */
const GRID_CLASS: Record<number, string> = {
  1: "md:grid-cols-1",
  2: "md:grid-cols-2",
  3: "md:grid-cols-2 lg:grid-cols-3",
  4: "md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
};

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
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
  ad,
}: {
  streamId: number;
  streamName: string;
  isOnline: boolean;
  date: string;
  ad: AdConfig | null;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [active, setActive] = useState<TimelineEntry | null>(null);
  const [videoSrc, setVideoSrc] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [urlLoading, setUrlLoading] = useState(false);
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

  const playEntry = useCallback(
    async (entry: TimelineEntry) => {
      const mySeq = ++playSeqRef.current;
      setActive(entry);
      revokeVideoObjectUrl();
      setVideoSrc(null);
      setVideoError(null);
      setUrlLoading(true);
      try {
        const p = await api.get<PlaybackUrl>(
          `/recordings/${streamId}/playback-url?time=${encodeURIComponent(entry.start)}`,
        );
        if (mySeq !== playSeqRef.current) return;
        /* Hormati expires_at: URL yang sudah kedaluwarsa jangan dipakai. */
        if (p.expires_at && new Date(p.expires_at).getTime() <= Date.now()) {
          setVideoError("Tautan rekaman sudah kedaluwarsa, coba putar lagi segmen ini.");
          return;
        }
        /* <video> tidak bisa mengirim header Authorization (token ada di
           localStorage), jadi segmen diunduh lewat apiFetch lalu diputar
           dari blob object URL. Pola yang sama dengan poster kamera,
           bukan ?token= di URL. */
        const path = p.url.startsWith("/api/") ? p.url.slice(4) : p.url;
        const res = await apiFetch(path);
        if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
        const blob = await res.blob();
        if (mySeq !== playSeqRef.current) return;
        const objectUrl = URL.createObjectURL(blob);
        videoObjectUrlRef.current = objectUrl;
        setVideoSrc(objectUrl);
      } catch (e) {
        if (mySeq !== playSeqRef.current) return;
        setError(
          e instanceof ApiError ? e.message : "Gagal memuat URL playback",
        );
      } finally {
        if (mySeq === playSeqRef.current) setUrlLoading(false);
      }
    },
    [streamId, revokeVideoObjectUrl],
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
          {/* Linimasa */}
          <div className="border-b border-ink-800 px-4 py-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-400">
                {timeline.date}
              </span>
              <span className="rounded-full bg-ink-800 px-2.5 py-[3px] text-[11px] font-semibold text-slate-400 shadow-sm">
                {timeline.entries.length} segmen
              </span>
            </div>
            <div className="relative h-12 overflow-hidden rounded-full bg-ink-800 shadow-sm">
              {Array.from({ length: 25 }).map((_, h) => (
                <span
                  key={h}
                  className="absolute top-0 h-full w-px bg-ink-500/25"
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
                    disabled={urlLoading}
                    title={`${fmtTime(e.start)} - ${fmtTime(e.end)}${e.has_event ? " · ada event" : ""}`}
                    aria-label={`Putar segmen ${fmtTime(e.start)}`}
                    className={`absolute top-0.5 h-11 rounded-full transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 ${
                      isActive
                        ? "bg-gradient-to-r from-accent-600 to-accent-500 shadow-[0_2px_12px_-2px_var(--nv-accent-600)]"
                        : e.has_event
                          ? "bg-warn-400/80 hover:bg-warn-400"
                          : "bg-accent-600/60 hover:bg-accent-500"
                    }`}
                    style={{ left: `${left}%`, width: `${width}%`, minWidth: "24px" }}
                  />
                );
              })}
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

          {/* Pratinjau */}
          <div>
            <div className="flex items-center justify-between gap-2 border-b border-ink-800 px-4 py-3">
              <span className="shrink-0 text-[15px] font-extrabold tracking-tight text-slate-100">Pratinjau</span>
              {active && (
                <span className="min-w-0 flex-1 truncate text-right text-xs font-medium text-slate-400">
                  {fmtTime(active.start)} - {fmtTime(active.end)}
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
                <div className="flex aspect-video flex-col items-center justify-center gap-2 px-6 text-center">
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
              ) : videoSrc ? (
                <video
                  ref={videoRef}
                  key={videoSrc}
                  src={videoSrc}
                  controls
                  playsInline
                  onError={() =>
                    setVideoError(
                      "Video gagal dimuat, segmen mungkin sudah terhapus atau tautannya kedaluwarsa.",
                    )
                  }
                  className="aspect-video w-full bg-black"
                />
              ) : (
                <div className="flex aspect-video flex-col items-center justify-center gap-2 px-6 text-center">
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
          </div>
        </>
      )}

      {/* Iklan di bawah panel (di luar area 16:9), bukan overlay: tampil di
          semua fase panel supaya tinggi panel stabil. */}
      {ad?.is_active && (
        <AdBanner
          config={ad}
          hovered={panelHovered}
          clickTick={adClickTick}
          placement="below"
        />
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
                <label className="flex flex-1 flex-col gap-1.5">
                  <span className="text-xs font-semibold text-slate-400">
                    Kamera
                  </span>
                  <select
                    value={streamId}
                    onChange={(e) => setStreamId(e.target.value)}
                    className="h-11 rounded-xl bg-ink-800 px-4 text-base text-slate-100 shadow-sm outline-none transition-all duration-150 focus:ring-2 focus:ring-accent-500/30"
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
          <div
            className={`mx-auto grid w-full max-w-5xl grid-cols-1 gap-4 ${multi ? (GRID_CLASS[gridCols] ?? GRID_CLASS[2]) : ""}`}
          >
            {selectedStreams.map((s) => (
              <PlaybackPanel
                key={s.id}
                streamId={s.id}
                streamName={s.name}
                isOnline={s.is_online}
                date={date}
                ad={ad}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
