"use client";

import { useCallback, useEffect, useState, type RefObject } from "react";

/* Layar penuh + rotasi untuk panggung video.
   - Default: TIDAK mengunci orientasi — HP tetap berdiri dan mengikuti
     auto-rotate perangkat; video tampil utuh (object-contain).
   - rotate(): kunci landscape lewat Screen Orientation API (Android Chrome
     saat fullscreen). Bila tidak didukung (iOS/desktop), putar konten 90°
     lewat CSS (.nv-rot, hanya aktif saat layar portrait).
   - iPhone tidak punya Fullscreen API untuk elemen: pakai pemutar native
     video.webkitEnterFullscreen (sudah bisa auto-rotate sendiri). */

type RotMode = "auto" | "locked" | "css";

type WebkitDoc = Document & {
  webkitFullscreenElement?: Element | null;
  webkitExitFullscreen?: () => Promise<void> | void;
};
type WebkitEl = HTMLElement & {
  webkitRequestFullscreen?: () => Promise<void> | void;
};
type WebkitVideo = HTMLVideoElement & { webkitEnterFullscreen?: () => void };
type LockableOrientation = ScreenOrientation & {
  lock?: (o: "landscape" | "portrait") => Promise<void>;
};

const fsElement = () =>
  document.fullscreenElement ?? (document as WebkitDoc).webkitFullscreenElement ?? null;

export function useFullscreen(
  ref: RefObject<HTMLElement | null>,
  videoRef?: RefObject<HTMLVideoElement | null>,
) {
  const [fs, setFs] = useState(false);
  const [rot, setRot] = useState<RotMode>("auto");

  useEffect(() => {
    const onChange = () => {
      const on = !!ref.current && fsElement() === ref.current;
      setFs(on);
      if (!on) {
        try {
          screen.orientation?.unlock?.();
        } catch {
          /* tidak didukung */
        }
        setRot("auto");
      }
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("webkitfullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("webkitfullscreenchange", onChange);
    };
  }, [ref]);

  const toggle = useCallback(() => {
    const el = ref.current as WebkitEl | null;
    if (!el) return;
    const d = document as WebkitDoc;
    if (fsElement()) {
      if (d.exitFullscreen) d.exitFullscreen().catch(() => {});
      else d.webkitExitFullscreen?.();
      return;
    }
    if (el.requestFullscreen) {
      el.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
    } else if (el.webkitRequestFullscreen) {
      el.webkitRequestFullscreen();
    } else {
      (videoRef?.current as WebkitVideo | null)?.webkitEnterFullscreen?.();
    }
  }, [ref, videoRef]);

  const rotate = useCallback(async () => {
    if (rot !== "auto") {
      try {
        screen.orientation?.unlock?.();
      } catch {
        /* tidak didukung */
      }
      setRot("auto");
      return;
    }
    const o = screen.orientation as LockableOrientation | undefined;
    try {
      if (!o?.lock) throw new Error("lock tidak didukung");
      await o.lock("landscape");
      setRot("locked");
    } catch {
      setRot("css");
    }
  }, [rot]);

  return { fs, rotated: rot !== "auto", cssRotate: rot === "css", toggle, rotate };
}
