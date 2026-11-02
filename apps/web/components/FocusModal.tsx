"use client";

import { useEffect, useRef, useState } from "react";
import { playWhep, stopWhep } from "../lib/whep";
import type { Stream } from "../lib/types";

interface Props {
  stream: Stream | null;
  onClose: () => void;
}

/* Modal fokus: memutar MAIN stream (tajam) + tombol snapshot. */
export function FocusModal({ stream, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    const video = videoRef.current;
    const url = stream?.whep_main_url || stream?.whep_sub_url;
    if (!video || !url || !stream?.is_online) return;
    let cancelled = false;
    playWhep(video, url)
      .then((pc) => {
        if (cancelled) stopWhep(pc);
        else pcRef.current = pc;
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      stopWhep(pcRef.current);
      pcRef.current = null;
    };
  }, [stream]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!stream) return null;

  const snapshot = () => {
    const video = videoRef.current;
    if (!video) return;
    const c = document.createElement("canvas");
    c.width = video.videoWidth;
    c.height = video.videoHeight;
    c.getContext("2d")?.drawImage(video, 0, 0);
    const a = document.createElement("a");
    a.href = c.toDataURL("image/jpeg", 0.85);
    a.download = `${stream.name}-${Date.now()}.jpg`;
    a.click();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/15"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${stream.is_online ? "bg-ok-400" : "bg-bad-400"}`}
            />
            <h2 className="text-sm font-semibold text-white">{stream.name}</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={snapshot}
              className="rounded-md bg-white/10 px-3 py-2 text-xs text-white transition hover:bg-white/20 active:scale-95"
            >
              Snapshot
            </button>
            <button
              onClick={onClose}
              className="flex h-9 w-9 items-center justify-center rounded-md bg-white/10 text-white transition hover:bg-white/20 active:scale-95"
              aria-label="Tutup"
            >
              ✕
            </button>
          </div>
        </div>
        <div className="aspect-video bg-black">
          {failed ? (
            <div className="flex h-full items-center justify-center text-sm text-neutral-400">
              Gagal memutar stream utama
            </div>
          ) : (
            <video
              ref={videoRef}
              controls
              playsInline
              className="h-full w-full object-contain"
            />
          )}
        </div>
      </div>
    </div>
  );
}
