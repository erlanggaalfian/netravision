"use client";

import { useEffect, useRef, useState } from "react";
import { playWhep, stopWhep } from "../lib/whep";
import { useFullscreen } from "../hooks/useFullscreen";
import { withToken } from "../lib/api";
import type { Stream } from "../lib/types";

interface Props {
  stream: Stream;
  onExpand: (stream: Stream) => void;
}

/* Tile kamera: TIDAK PERNAH dilipat (aturan yang dikunci).
   Grid memakai sub stream (ringan); klik → modal pakai main stream (tajam).
   Kontrol overlay: tap-toggle di layar sentuh (class vk-touch-toggle).
   Visual konsol NVR: rounded-2xl, ring status 2px (ok/warn/bad),
   scrim netral untuk kontrol, empty/offline state rapi (ikon SVG + teks). */
export function CameraTile({ stream, onExpand }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const [showControls, setShowControls] = useState(false);

  const { fs, rotated, cssRotate, toggle: toggleFs, rotate } = useFullscreen(
    boxRef,
    videoRef,
  );

  const url = stream.whep_sub_url || stream.whep_main_url;

  useEffect(() => {
    const box = boxRef.current;
    const video = videoRef.current;
    if (!box || !video || !url || !stream.is_online) return;

    let cancelled = false;
    const io = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry.isIntersecting && !pcRef.current && !cancelled) {
          playWhep(video, url, () => {
            if (!cancelled) setFailed(true);
          })
            .then((pc) => {
              if (cancelled) {
                stopWhep(pc);
                return;
              }
              pcRef.current = pc;
              setPlaying(true);
            })
            .catch(() => {
              if (!cancelled) setFailed(true);
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
  }, [url, stream.is_online, stream.id]);

  const toggleControls = () => setShowControls((v) => !v);

  const ring = !stream.is_online || failed ? "ring-bad-400" : "ring-ok-400";

  return (
    <div
      ref={boxRef}
      onClick={toggleControls}
      /* Fallback keyboard untuk :focus-within (I1): tampilkan kontrol saat
         fokus keyboard masuk ke tile, sembunyikan saat fokus keluar. */
      onFocus={() => setShowControls(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) {
          setShowControls(false);
        }
      }}
      className={`nv-stage vk-touch-toggle ${showControls ? "cam-show-controls" : ""} ${cssRotate ? "nv-rot" : ""} group relative aspect-video select-none overflow-hidden rounded-2xl bg-ink-900 ring-2 ${ring}`}
    >
      <div className="nv-rot-inner relative h-full w-full">
      {stream.is_online && !failed ? (
        <>
          <video
            ref={videoRef}
            muted
            playsInline
            className={`h-full w-full ${fs ? "object-contain" : "object-cover"}`}
          />
          {!playing &&
            (stream.poster_url ? (
              <img
                src={withToken(stream.poster_url)}
                alt={stream.name}
                loading="lazy"
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="flex items-center gap-2 text-xs text-slate-400">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/15 border-t-accent-400 motion-reduce:animate-none" />
                  Menghubungkan…
                </span>
              </div>
            ))}
          {playing && (
            <span className="pointer-events-none absolute left-3 top-3 flex items-center gap-1.5 rounded-md bg-black/60 px-2 py-1 text-[11px] font-semibold tracking-wide text-white">
              <span className="h-1.5 w-1.5 rounded-full bg-bad-400" />
              LIVE
            </span>
          )}
        </>
      ) : (
        <div className="relative flex h-full w-full flex-col items-center justify-center gap-2 bg-ink-900 px-4 text-center">
          {stream.poster_url && (
            <img
              src={withToken(stream.poster_url)}
              alt=""
              aria-hidden
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover opacity-25"
            />
          )}
          <svg
            width="30"
            height="30"
            viewBox="0 0 24 24"
            fill="none"
            className="relative text-slate-400"
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
          <span className="relative text-sm font-medium text-slate-300">
            {stream.is_online ? "Gagal memuat" : "Offline"}
          </span>
          <span className="relative text-xs text-slate-400">
            {stream.is_online
              ? "Stream tidak dapat diputar"
              : "Kamera tidak terjangkau"}
          </span>
        </div>
      )}

      {/* Overlay kontrol: scrim netral di bawah teks */}
      <div className="cam-controls absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 bg-gradient-to-t from-black/85 via-black/40 to-transparent px-3 pb-3 pt-8">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${stream.is_online && !failed ? "bg-ok-400" : "bg-bad-400"}`}
          />
          <span className="truncate text-sm font-medium text-white">
            {stream.name}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {fs && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                rotate();
              }}
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-white transition active:scale-95 ${rotated ? "bg-accent-400/30 hover:bg-accent-400/40" : "bg-white/10 hover:bg-white/20"}`}
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
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white transition hover:bg-white/20 active:scale-95"
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
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white transition hover:bg-white/20 active:scale-95"
          aria-label={`Perbesar ${stream.name}`}
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
    </div>
  );
}
