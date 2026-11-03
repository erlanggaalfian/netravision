"use client";

import { useEffect, useRef, useState } from "react";
import { playWhep, stopWhep } from "../lib/whep";
import { api, withToken } from "../lib/api";
import { AdBanner } from "./AdBanner";
import { useFullscreen } from "../hooks/useFullscreen";
import type { Stream, AdConfig } from "../lib/types";

interface Props {
  stream: Stream | null;
  onClose: () => void;
}

/* Modal fokus — pola v2 (openCameraPopup): SUB dulu agar langsung tampil,
   lalu MAIN (HD) disambung di latar dan ditukar mulus begitu frame pertama
   main siap. Main gagal -> tetap di SUB. Tombol LQ/HQ untuk ganti manual.
   Banner iklan (bila aktif & diizinkan untuk akun ini) tampil lower-third,
   seperti popup guest v2.0.
   Visual: header rapi (status + nama + info stream), kontrol jelas ≥44px. */
export function FocusModal({ stream, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const switchRef = useRef<((url: string, target: "LQ" | "HQ") => void) | null>(null);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [vRatio, setVRati] = useState<string | null>(null);
  const [quality, setQuality] = useState<"LQ" | "HQ">("LQ");
  const isDesktop = () =>
    typeof window !== "undefined" &&
    window.matchMedia("(min-width: 768px)").matches &&
    window.matchMedia("(pointer: fine)").matches;
  const [want, setWant] = useState<"LQ" | "HQ">(() => (isDesktop() ? "HQ" : "LQ"));
  const [ad, setAd] = useState<AdConfig | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const { fs, rotated, cssRotate, toggle: toggleFs, rotate } = useFullscreen(
    stageRef,
    videoRef,
  );

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

  /* Default seperti v2: desktop (>=768px) HQ, HP LQ. Tombol LQ/HQ bisa
     mengganti di keduanya. Kamera berganti -> kembali ke default. */
  useEffect(() => {
    setWant(isDesktop() ? "HQ" : "LQ");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream]);

  useEffect(() => {
    setFailed(false);
    setPlaying(false);
    setVRati(null);
    setQuality("LQ");
    const video = videoRef.current;
    const main = stream?.whep_main_url;
    const sub = stream?.whep_sub_url;
    if (!video || !(main || sub) || !stream?.is_online) return;
    let cancelled = false;
    let pending: RTCPeerConnection | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const fail = () => {
      if (!cancelled) setFailed(true);
    };

    /* Ganti stream dengan smooth: sambung URL baru di elemen tersembunyi,
       tukar srcObject saat sudah bergambar (tanpa layar hitam/loading),
       lalu tutup koneksi lama. Dipakai untuk upgrade otomatis maupun
       toggle manual LQ/HQ dua arah. */
    const smoothSwitch = (url: string, target: "LQ" | "HQ") => {
      if (cancelled || !url) return;
      // Batalkan switch yang masih jalan bila ada.
      if (pending) {
        stopWhep(pending);
        pending = null;
      }
      const hidden = document.createElement("video");
      hidden.muted = true;
      hidden.playsInline = true;
      // Tandai switch ini sedang berjalan agar tidak tertimpa.
      let myCancelled = false;
      const cancelMine = () => {
        myCancelled = true;
      };
      playWhep(hidden, url)
        .then((pc) => {
          if (cancelled || myCancelled) return stopWhep(pc);
          pending = pc;
          const swap = () => {
            if (cancelled || myCancelled || hidden.videoWidth === 0) return;
            video.srcObject = hidden.srcObject;
            video.play().catch(() => {});
            stopWhep(pcRef.current);
            pcRef.current = pc;
            pending = null;
            setQuality(target);
          };
          if (hidden.videoWidth > 0) swap();
          else hidden.addEventListener("resize", swap, { once: true });
        })
        .catch(() => {
          /* gagal: tetap di stream lama, jangan tampilkan error */
        });
      return cancelMine;
    };
    // Simpan agar toggle manual bisa pakai.
    switchRef.current = smoothSwitch;

    /* Sambung MAIN di elemen tersembunyi; tukar srcObject saat sudah
       bergambar (tanpa layar hitam), lalu tutup koneksi SUB. */
    const goHQ = () => {
      if (!main || cancelled) return;
      smoothSwitch(main, "HQ");
    };

    if (want === "LQ" || !main || !sub) {
      playWhep(video, (want === "HQ" ? main : sub) || main || sub!, fail)
        .then((pc) => {
          if (cancelled) return stopWhep(pc);
          pcRef.current = pc;
          setQuality(want === "HQ" && main ? "HQ" : "LQ");
        })
        .catch(fail);
    } else {
      playWhep(video, sub, fail)
        .then((pc) => {
          if (cancelled) return stopWhep(pc);
          pcRef.current = pc;
          // v2: upgrade HD 1 detik setelah sub tampil.
          timer = setTimeout(goHQ, 1000);
        })
        .catch(() => {
          if (!cancelled) goHQ();
        });
    }
    return () => {
      cancelled = true;
      clearTimeout(timer);
      stopWhep(pending);
      stopWhep(pcRef.current);
      pcRef.current = null;
      switchRef.current = null;
    };
  }, [stream, want]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.fullscreenElement) onClose();
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/85 p-3 sm:p-6"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        className="nv-pop max-h-[calc(100dvh-1.5rem)] w-full max-w-5xl overflow-x-hidden overflow-y-auto rounded-2xl bg-ink-900 ring-1 ring-ink-600/30 sm:max-h-[calc(100dvh-3rem)]"
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
                {quality === "HQ" ? "Main stream (HD)" : "Sub stream (LQ)"}
                {stream.brand ? `, ${stream.brand}` : ""}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={() => {
                const target = quality === "HQ" ? "LQ" : "HQ";
                const url = target === "HQ" ? stream?.whep_main_url : stream?.whep_sub_url;
                // Smooth: sambung di background, tukar saat sudah bergambar.
                // Jangan ubah `want` agar effect tidak restart (layar hitam).
                if (url && switchRef.current) switchRef.current(url, target);
              }}
              aria-label={quality === "HQ" ? "Ganti ke sub stream (LQ)" : "Ganti ke main stream (HD)"}
              title={quality === "HQ" ? "Ganti ke sub stream (LQ)" : "Ganti ke main stream (HD)"}
              className={`flex h-11 min-w-11 items-center justify-center rounded-xl px-3 text-xs font-bold tracking-wide transition active:scale-95 ${quality === "HQ" ? "bg-ok-400/20 text-ok-400 hover:bg-ok-400/30" : "bg-ink-500/15 text-white hover:bg-ink-500/25"}`}
            >
              {quality}
            </button>
            <button
              onClick={snapshot}
              aria-label="Ambil snapshot"
              title="Ambil snapshot"
              className="flex h-11 items-center gap-2 rounded-xl bg-ink-500/15 px-4 text-sm font-medium text-white transition hover:bg-ink-500/25 active:scale-95"
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
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-ink-500/15 text-white transition hover:bg-ink-500/25 active:scale-95"
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
        <div
          ref={stageRef}
          className={`nv-stage relative ${vRatio ? "" : "aspect-video"} bg-black ${cssRotate ? "nv-rot" : ""}`}
          style={vRatio ? { aspectRatio: vRatio } : undefined}
        >
          <div className="nv-rot-inner relative h-full w-full">
          {ad?.is_active && <AdBanner config={ad} />}
          {failed || !stream.is_online ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
              <svg
                width="32"
                height="32"
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
              <p className="text-sm font-medium text-slate-300">
                {stream.is_online ? "Gagal memutar stream" : "Kamera offline"}
              </p>
              <p className="text-xs text-slate-400">
                {stream.is_online
                  ? "Coba tutup dan buka kembali"
                  : "Kamera tidak terjangkau saat ini"}
              </p>
            </div>
          ) : (
            <>
              {/* Tombol layar penuh bawaan video dimatikan: di Android ia
                  memaksa landscape. Pakai kontrol sendiri (ikut rotasi HP,
                  putar manual lewat tombol). */}
              <video
                ref={videoRef}
                controls
                controlsList="nofullscreen"
                disablePictureInPicture
                playsInline
                onPlaying={() => setPlaying(true)}
                onLoadedMetadata={(e) => {
                  const v = e.currentTarget;
                  if (v.videoWidth && v.videoHeight) {
                    setVRati(`${v.videoWidth} / ${v.videoHeight}`);
                  }
                }}
                className="h-full w-full object-contain"
              />
              {/* Poster langsung tampil saat popup dibuka agar tidak hitam/
                  loading dulu; hilang begitu video mulai bergambar. */}
              {!playing &&
                (stream.poster_url ? (
                  <img
                    src={withToken(stream.poster_url)}
                    alt={stream.name}
                    className="pointer-events-none absolute inset-0 h-full w-full object-contain"
                  />
                ) : (
                  <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                    <span className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/15 border-t-accent-400 motion-reduce:animate-none" />
                      Menghubungkan…
                    </span>
                  </div>
                ))}
              <div className="absolute right-2 top-2 flex gap-2">
                {fs && (
                  <button
                    onClick={rotate}
                    className={`flex h-11 w-11 items-center justify-center rounded-xl text-white backdrop-blur-sm transition active:scale-95 ${rotated ? "bg-accent-400/40 hover:bg-accent-400/50" : "bg-black/50 hover:bg-black/70"}`}
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
                  onClick={toggleFs}
                  className="flex h-11 w-11 items-center justify-center rounded-xl bg-black/50 text-white backdrop-blur-sm transition hover:bg-black/70 active:scale-95"
                  aria-label={fs ? "Keluar layar penuh" : "Layar penuh"}
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
              </div>
            </>
          )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-2.5 sm:px-5">
          <span
            className={`text-xs font-medium ${stream.is_online ? "text-ok-400" : "text-bad-400"}`}
          >
            {stream.is_online ? "● Online" : "● Offline"}
          </span>
          <span className="hidden text-xs text-slate-400 sm:block">
            Tekan ESC untuk menutup
          </span>
        </div>
      </div>
    </div>
  );
}
