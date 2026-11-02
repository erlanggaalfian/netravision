"use client";

import { useEffect, useRef, useState } from "react";
import { playWhep, stopWhep } from "../lib/whep";
import type { Stream } from "../lib/types";

interface Props {
  stream: Stream;
  onExpand: (stream: Stream) => void;
}

/* Tile kamera: TIDAK PERNAH dilipat (aturan yang dikunci).
   Grid memakai sub stream (ringan); klik → modal pakai main stream (tajam).
   Kontrol overlay: tap-toggle di layar sentuh. */
export function CameraTile({ stream, onExpand }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const [showControls, setShowControls] = useState(false);

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
          playWhep(video, url)
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

  return (
    <div
      ref={boxRef}
      onClick={toggleControls}
      className={`vk-touch-toggle ${showControls ? "cam-show-controls" : ""} group relative aspect-video select-none overflow-hidden rounded-lg bg-ink-900 ring-1 ring-white/10`}
    >
      {stream.is_online && !failed ? (
        <>
          <video
            ref={videoRef}
            muted
            playsInline
            className="h-full w-full object-cover"
          />
          {!playing && stream.poster_url && (
            <img
              src={stream.poster_url}
              alt={stream.name}
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover"
            />
          )}
        </>
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-2 bg-ink-900">
          <span
            className={`h-2.5 w-2.5 rounded-full ${stream.is_online ? "bg-warn-400" : "bg-bad-400"}`}
          />
          <span className="text-xs text-neutral-400">
            {stream.is_online ? "Memuat…" : "Offline"}
          </span>
          {stream.poster_url && (
            <img
              src={stream.poster_url}
              alt={stream.name}
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover opacity-40"
            />
          )}
        </div>
      )}

      {/* Overlay kontrol */}
      <div className="cam-controls absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 bg-gradient-to-t from-black/80 to-transparent px-3 pb-2 pt-6">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${stream.is_online ? "bg-ok-400" : "bg-bad-400"}`}
          />
          <span className="truncate text-xs font-medium text-white">
            {stream.name}
          </span>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onExpand(stream);
          }}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white/10 text-white backdrop-blur transition hover:bg-white/20 active:scale-95"
          aria-label={`Perbesar ${stream.name}`}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
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
  );
}
