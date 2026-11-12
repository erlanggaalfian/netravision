"use client";

import { useEffect, useRef, useState } from "react";
import { playWhep, stopWhep } from "../lib/whep";
import { useFullscreen } from "../hooks/useFullscreen";
import { usePosterUrl } from "../lib/api";
import { AdBanner } from "./AdBanner";
import type { AdConfig, Stream } from "../lib/types";

interface Props {
  stream: Stream;
  onExpand: (stream: Stream) => void;
  ad?: AdConfig | null;
  /* Layar penuh grid Monitor: iklan masuk ke dalam frame (overlay di
     bawah area video), bukan di bawah video. */
  adInFrame?: boolean;
  /* Layar penuh grid Monitor: tile mengisi sel grid (stage fleksibel)
     supaya semua baris muat dan nama kamera tidak terpotong. */
  fillCell?: boolean;
}

/* Tile kamera: TIDAK PERNAH dilipat (aturan yang dikunci).
   Grid memakai sub stream (ringan); klik → modal pakai main stream (tajam).
   Kontrol overlay: tap-toggle di layar sentuh (class vk-touch-toggle).
   Visual konsol NVR: rounded-2xl, ring status 2px (ok/warn/bad),
   scrim netral untuk kontrol, empty/offline state rapi (ikon SVG + teks). */
export function CameraTile({ stream, onExpand, ad, adInFrame = false, fillCell = false }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const [failMsg, setFailMsg] = useState<string | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const [retryTick, setRetryTick] = useState(0);
  const [showControls, setShowControls] = useState(false);
  /* Sinyal iklan: hover tile + tiap klik tile (perilaku marquee hover/click). */
  const [tileHovered, setTileHovered] = useState(false);
  const [adClickTick, setAdClickTick] = useState(0);

  const { fs, rotated, cssRotate, toggle: toggleFs, rotate } = useFullscreen(
    boxRef,
    videoRef,
  );

  const url = stream.whep_sub_url || stream.whep_main_url;
  /* Poster lewat blob object URL (header Authorization), bukan ?token= di URL. */
  const posterSrc = usePosterUrl(stream.poster_url);

  /* Pulih dari gagal: begitu kamera kembali online, URL berubah, atau
     kamera berganti, reset state gagal/terputus supaya tile mencoba
     ulang tanpa reload penuh. Effect WHEP di bawah memakai `failed`
     sebagai dependensi, jadi reset ini memicu percobaan ulang. */
  useEffect(() => {
    setFailed(false);
    setFailMsg(null);
    setDisconnected(false);
    setPlaying(false);
  }, [stream.id, stream.is_online, url]);

  useEffect(() => {
    if (!stream.is_online) return;
    /* Online tapi tidak ada URL WHEP sama sekali: gagal dengan pesan
       yang jelas, bukan spinner selamanya. */
    if (!url) {
      setFailed(true);
      setFailMsg("URL stream tidak tersedia");
      return;
    }
    if (failed || disconnected) return;
    const box = boxRef.current;
    const video = videoRef.current;
    if (!box || !video) return;

    let cancelled = false;
    const fail = (msg: string) => {
      if (cancelled) return;
      stopWhep(pcRef.current);
      pcRef.current = null;
      setPlaying(false);
      setFailed(true);
      setFailMsg(msg);
    };
    const io = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry.isIntersecting && !pcRef.current && !cancelled) {
          playWhep(
            video,
            url,
            () => fail("Stream tidak dapat diputar"),
            undefined,
            () => {
              if (cancelled) return;
              stopWhep(pcRef.current);
              pcRef.current = null;
              setPlaying(false);
              setDisconnected(true);
            },
          )
            .then((pc) => {
              if (cancelled) {
                stopWhep(pc);
                return;
              }
              pcRef.current = pc;
              setDisconnected(false);
              setPlaying(true);
            })
            .catch(() => {
              fail("Stream tidak dapat diputar");
            });
        } else if (!entry.isIntersecting && pcRef.current) {
          stopWhep(pcRef.current);
          pcRef.current = null;
          setPlaying(false);
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(box);
    return () => {
      cancelled = true;
      io.disconnect();
      stopWhep(pcRef.current);
      pcRef.current = null;
    };
  }, [url, stream.is_online, stream.id, failed, disconnected, retryTick]);

  const toggleControls = () => setShowControls((v) => !v);

  const online = stream.is_online && !failed && !disconnected;
  /* Kontrol terlihat saat tap-toggle aktif, hover mouse, atau fokus keyboard
     masuk (tiga pemicu yang sama dengan CSS .cam-controls di globals.css);
     saat ketiganya mati, kontrol juga disembunyikan dari keyboard
     (invisible), bukan cuma opacity 0. */
  const controlsVisible = showControls || tileHovered;

  return (
    <div
      ref={boxRef}
      onMouseEnter={() => setTileHovered(true)}
      onMouseLeave={() => setTileHovered(false)}
      /* Fallback keyboard untuk :focus-within (I1): tampilkan kontrol saat
         fokus keyboard masuk ke tile, sembunyikan saat fokus keluar. */
      onFocus={() => setShowControls(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) {
          setShowControls(false);
        }
      }}
      className={`vk-touch-toggle ${showControls ? "cam-show-controls" : ""} group relative select-none overflow-hidden transition-all duration-300 ${
        fs
          ? "fixed inset-0 z-[70] border-0 bg-black"
          : `rounded-2xl bg-ink-900 shadow-[0_8px_24px_-8px_rgba(0,0,0,0.35)] ${fillCell ? "flex h-full flex-col" : ""}`
      }`}
    >
      {/* Area video: selalu gelap (nv-stage), di kedua tema. Klik di sini
          saja yang toggle kontrol dan memberi sinyal klik iklan; klik pada
          footer atau banner iklan di bawah tidak ikut. */}
      <div
        onClick={() => {
          toggleControls();
          setAdClickTick((t) => t + 1);
        }}
        className={`nv-stage relative bg-black ${cssRotate ? "nv-rot" : ""} ${fs ? "h-full" : fillCell ? "min-h-0 flex-1" : "aspect-video"}`}
      >
      <div className="nv-rot-inner relative h-full w-full">
      {stream.is_online && !failed ? (
        <>
          <video
            ref={videoRef}
            muted
            playsInline
            className={`h-full w-full ${fs || fillCell ? "object-contain" : "object-cover"}`}
          />
          {!playing &&
            (posterSrc ? (
              <img
                src={posterSrc}
                alt={stream.name}
                loading="lazy"
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="flex items-center gap-2.5 rounded-full bg-black/50 px-4 py-2 text-xs font-medium text-slate-300">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/15 border-t-accent-400 motion-reduce:animate-none" />
                  Menghubungkan…
                </span>
              </div>
            ))}
          {playing && !disconnected && (
            <span className="pointer-events-none absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-[11px] font-bold tracking-wider text-white shadow-[0_4px_12px_rgba(0,0,0,0.4)]">
              <span className="h-1.5 w-1.5 rounded-full bg-bad-400 shadow-[0_0_8px_2px_rgba(248,113,113,0.6)]" />
              LIVE
            </span>
          )}
          {disconnected && !playing && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60 px-4 text-center">
              <span className="text-sm font-semibold text-slate-200">
                Koneksi terputus
              </span>
              <span className="text-xs text-slate-400">
                Mencoba lagi, atau ketuk Coba lagi di bawah.
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setDisconnected(false);
                  setRetryTick((t) => t + 1);
                }}
                className="mt-1 flex h-11 items-center rounded-xl bg-white/10 px-4 text-xs font-bold text-white transition hover:bg-white/25 active:scale-95"
              >
                Coba lagi
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="relative flex h-full w-full flex-col items-center justify-center gap-2.5 bg-ink-900 px-4 text-center">
          {posterSrc && (
            <img
              src={posterSrc}
              alt=""
              aria-hidden
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover opacity-20"
            />
          )}
          <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-ink-800">
            <svg
              width="26"
              height="26"
              viewBox="0 0 24 24"
              fill="none"
              className="text-slate-400"
              aria-hidden
            >
              <path
                d="M3 8.5A1.5 1.5 0 014.5 7h9A1.5 1.5 0 0115 8.5v6a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 013 14.5v-6z"
                stroke="currentColor"
                strokeWidth="1.6"
              />
              <path
                d="M15 10.5l5-3v9l-5-3"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path
                d="M4 4l16 16"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </div>
          <span className="relative text-sm font-semibold tracking-tight text-slate-200">
            {stream.is_online ? "Gagal memuat" : "Offline"}
          </span>
          <span className="relative text-xs text-slate-400">
            {stream.is_online
              ? (failMsg ?? "Stream tidak dapat diputar")
              : "Kamera tidak terjangkau"}
          </span>
          {stream.is_online && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setFailed(false);
                setFailMsg(null);
                setRetryTick((t) => t + 1);
              }}
              className="relative mt-1 flex h-11 items-center rounded-xl bg-white/10 px-4 text-xs font-bold text-white transition hover:bg-white/25 active:scale-95"
            >
              Coba lagi
            </button>
          )}
        </div>
      )}

      {/* Overlay kontrol: hanya tombol aksi (nama + status ada di footer kartu) */}
      <div className={`cam-controls absolute inset-x-0 bottom-0 z-30 flex items-center justify-end gap-2 bg-gradient-to-t from-black/85 via-black/40 to-transparent px-3 pb-3 pt-8 ${controlsVisible ? "visible" : "invisible"}`}>
        <div className="flex shrink-0 items-center gap-2">
          {fs && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                rotate();
              }}
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-white transition active:scale-95 ${rotated ? "bg-accent-400/30 hover:bg-accent-400/40" : "bg-white/10 hover:bg-white/25"}`}
              aria-label={rotated ? "Ikuti rotasi HP" : "Putar ke landscape"}
              aria-pressed={rotated}
              title={rotated ? "Ikuti rotasi HP" : "Putar ke landscape"}
            >
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
                <rect
                  x="6"
                  y="2.5"
                  width="8"
                  height="13"
                  rx="1.5"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  transform={rotated ? "rotate(90 10 9)" : undefined}
                />
                <path
                  d="M3 13.5a7 7 0 004.5 4M17 6.5a7 7 0 00-4.5-4"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              toggleFs();
            }}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white shadow-[0_4px_12px_rgba(0,0,0,0.3)] transition-all duration-200 hover:bg-white/25 hover:shadow-[0_6px_16px_rgba(0,0,0,0.4)] active:scale-95"
            aria-label={fs ? `Keluar layar penuh ${stream.name}` : `Layar penuh ${stream.name}`}
            title={fs ? "Keluar layar penuh" : "Layar penuh"}
          >
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path
                d={fs ? "M6 2v4H2M14 6h-4V2M10 14v-4h4M2 10h4v4" : "M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"}
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onExpand(stream);
            }}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white shadow-[0_4px_12px_rgba(0,0,0,0.3)] transition-all duration-200 hover:bg-white/25 hover:shadow-[0_6px_16px_rgba(0,0,0,0.4)] active:scale-95"
          aria-label={`Perbesar ${stream.name}`}
          title="Perbesar"
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
            <path
              d="M6 2H2v4M10 14h4v-4M2 2l4 4M14 14l-4-4"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          </svg>
        </button>
        </div>
      </div>
      </div>
      {/* Iklan di dalam frame (overlay) saat layar penuh grid Monitor:
          menempel di bawah area video, di dalam 16:9. */}
      {adInFrame && ad?.is_active && (
        <AdBanner
          config={ad}
          hovered={tileHovered}
          clickTick={adClickTick}
          placement="overlay"
        />
      )}
      </div>
      {/* Iklan di bawah video (di luar area 16:9), bukan overlay, supaya
          tidak menutupi tombol. Disembunyikan saat layar penuh dan saat
          iklan dipindah ke dalam frame (adInFrame). */}
      {!fs && !adInFrame && ad?.is_active && (
        <AdBanner
          config={ad}
          hovered={tileHovered}
          clickTick={adClickTick}
          placement="below"
        />
      )}
      {/* Footer kartu: titik status kecil + nama kamera saja (tanpa chip). */}
      {!fs && (
        <div className="flex items-center gap-2 border-t border-ink-800/60 px-3.5 py-3">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${online ? "bg-ok-400" : "bg-bad-400"}`}
            aria-label={online ? "Online" : "Offline"}
          />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight text-white">
            {stream.name}
          </span>
        </div>
      )}
    </div>
  );
}
