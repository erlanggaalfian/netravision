"use client";

import { useEffect, useRef, useState } from "react";
import { playWhep, stopWhep } from "../lib/whep";
import { api } from "../lib/api";
import { AdBanner } from "./AdBanner";
import type { Stream, AdConfig } from "../lib/types";

interface Props {
  stream: Stream | null;
  onClose: () => void;
}

/* Modal fokus: memutar MAIN stream (tajam) + tombol snapshot.
   Banner iklan (bila aktif & diizinkan untuk akun ini) tampil lower-third,
   seperti popup guest v2.0.
   Visual: header rapi (status + nama + info stream), kontrol jelas ≥44px. */
export function FocusModal({ stream, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const [failed, setFailed] = useState(false);
  const [ad, setAd] = useState<AdConfig | null>(null);

  /* Config iklan: backend menonaktifkan otomatis bila show_ads=False. */
  useEffect(() => {
    if (!stream) return;
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
  }, [stream]);

  useEffect(() => {
    setFailed(false);
    const video = videoRef.current;
    const main = stream?.whep_main_url;
    const sub = stream?.whep_sub_url;
    if (!video || !(main || sub) || !stream?.is_online) return;
    let cancelled = false;
    const fail = () => {
      if (!cancelled) setFailed(true);
    };
    const keep = (pc: RTCPeerConnection) => {
      if (cancelled) stopWhep(pc);
      else pcRef.current = pc;
    };
    /* Main dulu (tajam). Banyak kamera hanya mengizinkan 1 sesi RTSP —
       bila main ditolak, pakai sub (path sama yang sudah dipakai grid). */
    playWhep(video, main || sub!, fail)
      .then(keep)
      .catch(() => {
        if (cancelled) return;
        if (main && sub) playWhep(video, sub, fail).then(keep).catch(fail);
        else fail();
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

  /* Focus trap (I3): fokus awal ke tombol tutup, Tab berputar di dalam
     dialog, fokus dikembalikan ke pemicu saat modal ditutup. */
  useEffect(() => {
    if (!stream) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const prev = document.activeElement as HTMLElement | null;
    dialog
      .querySelector<HTMLElement>("[data-focus-close]")
      ?.focus({ preventScroll: true });
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const els = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => el.getClientRects().length > 0);
      if (els.length === 0) return;
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener("keydown", onKeyDown);
    return () => {
      dialog.removeEventListener("keydown", onKeyDown);
      prev?.focus?.({ preventScroll: true });
    };
  }, [stream]);

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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-3 sm:p-6"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        className="nv-stage nv-pop max-h-[calc(100dvh-1.5rem)] w-full max-w-5xl overflow-x-hidden overflow-y-auto rounded-2xl bg-ink-900 ring-1 ring-white/15 sm:max-h-[calc(100dvh-3rem)]"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={stream.name}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <span
              className={`h-2.5 w-2.5 shrink-0 rounded-full ${stream.is_online ? "bg-ok-400" : "bg-bad-400"}`}
            />
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold text-white">
                {stream.name}
              </h2>
              <p className="text-xs text-slate-400">
                {stream.brand ? `Stream utama, ${stream.brand}` : "Stream utama"}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={snapshot}
              aria-label="Ambil snapshot"
              title="Ambil snapshot"
              className="flex h-11 items-center gap-2 rounded-xl bg-white/10 px-4 text-sm font-medium text-white transition hover:bg-white/20 active:scale-95"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 20 20"
                fill="none"
                aria-hidden
              >
                <path
                  d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="hidden min-[420px]:inline">Snapshot</span>
            </button>
            <button
              onClick={onClose}
              data-focus-close
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 text-white transition hover:bg-white/20 active:scale-95"
              aria-label="Tutup"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                aria-hidden
              >
                <path
                  d="M3 3l10 10M13 3L3 13"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </div>

        {/* Video */}
        <div className="relative aspect-video bg-black">
          {ad?.is_active && <AdBanner config={ad} />}
          {failed || !stream.is_online ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
              <svg
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                className="text-slate-500"
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
              <p className="text-sm font-medium text-slate-300">
                {stream.is_online ? "Gagal memutar stream utama" : "Kamera offline"}
              </p>
              <p className="text-xs text-slate-400">
                {stream.is_online
                  ? "Coba tutup dan buka kembali"
                  : "Kamera tidak terjangkau saat ini"}
              </p>
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

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-2.5 sm:px-5">
          <span
            className={`text-xs font-medium ${stream.is_online ? "text-ok-400" : "text-bad-400"}`}
          >
            {stream.is_online ? "● Online" : "● Offline"}
          </span>
          <span className="hidden text-xs text-slate-500 sm:block">
            Tekan ESC untuk menutup
          </span>
        </div>
      </div>
    </div>
  );
}
