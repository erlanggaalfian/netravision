"use client";

import { useEffect, useRef, useState } from "react";
import type { AdConfig } from "../lib/types";
import { normalizeUploadUrl } from "../lib/api";

interface Props {
  config: AdConfig;
  className?: string;
  /* Sinyal dari tile/modal pembungkus: hovered = pointer di atas tile,
     clickTick = bertambah tiap tile diklik. Dipakai perilaku hover/click. */
  hovered?: boolean;
  clickTick?: number;
}

/* Banner iklan fleksibel (2026-11-06):
   - Posisi: bawah | atas
   - Mode: marquee (teks berjalan) | popup (berkala). TIDAK ADA statis:
     teks selalu berjalan di semua pilihan.
   - Perilaku marquee: always (selalu terlihat, hover maupun tidak) |
     hover (terlihat saat hover + jeda setelah hover) | click (muncul
     saat tile diklik, hilang lagi setelah X detik)
   - Trigger popup: always (terus) | interval (tampil/sembunyi bergantian) | hover (saat hover video)
   - Klik banner: buka click_url di tab baru bila diisi
   Selalu gelap (area video). */
export function AdBanner({
  config,
  className = "",
  hovered = false,
  clickTick = 0,
}: Props) {
  const [visible, setVisible] = useState(true);
  const [cooling, setCooling] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const isPopup = config.display_mode === "popup";
  const trigger = config.popup_trigger || "always";
  const isMarquee = config.display_mode !== "popup";
  const marqueeBehavior = config.marquee_behavior || "always";

  const later = (fn: () => void, ms: number) => {
    const t = setTimeout(fn, ms);
    timers.current.push(t);
    return t;
  };
  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  /* Reset saat mode/perilaku berubah. */
  useEffect(() => {
    clearTimers();
    setCooling(false);
    setVisible(marqueeBehavior === "always" || !isMarquee ? true : false);
    if (isPopup && trigger !== "interval") setVisible(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMarquee, isPopup, trigger, marqueeBehavior]);

  /* Popup interval: tampil X detik, sembunyi Y detik, berulang. */
  useEffect(() => {
    if (!isPopup || trigger !== "interval") return;
    const showMs = Math.max(1, config.popup_show_seconds || 10) * 1000;
    const hideMs = Math.max(1, config.popup_hide_seconds || 50) * 1000;
    let alive = true;
    let timeout: ReturnType<typeof setTimeout>;
    const tick = (show: boolean) => {
      if (!alive) return;
      setVisible(show);
      timeout = setTimeout(() => tick(!show), show ? showMs : hideMs);
    };
    timeout = setTimeout(() => tick(false), showMs);
    return () => {
      alive = false;
      clearTimeout(timeout);
    };
  }, [
    isPopup,
    trigger,
    config.popup_show_seconds,
    config.popup_hide_seconds,
  ]);

  /* Marquee hover: saat tile di-hover, tampil X detik lalu sembunyi;
     setelah hover selesai, jeda Y detik sebelum bisa tampil lagi. */
  const hoverShowMs = Math.max(1, config.marquee_hover_show_seconds || 5) * 1000;
  const hoverCooldownMs =
    Math.max(0, config.marquee_hover_cooldown_seconds || 30) * 1000;
  useEffect(() => {
    if (!isMarquee || marqueeBehavior !== "hover") return;
    if (!hovered) return;
    if (cooling) return;
    setVisible(true);
    clearTimers();
    later(() => {
      setVisible(false);
      setCooling(true);
      later(() => setCooling(false), hoverCooldownMs);
    }, hoverShowMs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMarquee, marqueeBehavior, hovered, cooling]);

  /* Marquee hover selesai: mulai jeda bila banner sempat tampil. */
  const wasHovered = useRef(false);
  useEffect(() => {
    if (!isMarquee || marqueeBehavior !== "hover") return;
    if (wasHovered.current && !hovered) {
      clearTimers();
      setVisible(false);
      setCooling(true);
      later(() => setCooling(false), hoverCooldownMs);
    }
    wasHovered.current = hovered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hovered]);

  /* Marquee click: tiap tile diklik, tampil X detik lalu hilang lagi. */
  const clickShowMs = Math.max(1, config.marquee_click_show_seconds || 5) * 1000;
  const firstTick = useRef(true);
  useEffect(() => {
    if (firstTick.current) {
      firstTick.current = false;
      return;
    }
    if (!isMarquee || marqueeBehavior !== "click") return;
    if (clickTick <= 0) return;
    clearTimers();
    setVisible(true);
    later(() => setVisible(false), clickShowMs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clickTick]);

  useEffect(() => clearTimers, []);

  if (!config.is_active) return null;
  if (!config.marquee_text?.trim() && !config.image_url?.trim()) return null;

  const bgAlpha = Math.min(1, Math.max(0, config.bg_opacity));
  const imgAlpha = Math.min(1, Math.max(0, config.image_opacity));
  const txtAlpha = Math.min(1, Math.max(0, config.text_opacity));
  const duration = Math.max(10, (11 - config.scroll_speed) * 18);
  const align =
    config.text_align === "center"
      ? "justify-center"
      : config.text_align === "right"
        ? "justify-end"
        : "justify-start";
  const position = config.position === "top" ? "top-0" : "bottom-0";
  const borderSide =
    config.position === "top" ? "border-b" : "border-t";

  // Tinggi gambar tidak boleh melebihi tinggi banner dikurangi padding
  // vertikal (py-1.5 = 12px), kalau tidak gambar terpotong oleh
  // overflow-hidden. Bila banner_height 0 (otomatis), banner mengikuti
  // gambar sehingga tidak ada batasan.
  const bannerH = config.banner_height > 0 ? config.banner_height : 0;
  const imgH = Math.min(
    60,
    Math.max(10, config.image_height),
    bannerH > 0 ? Math.max(10, bannerH - 12) : 60,
  );

  // Hover (popup): sembunyi sampai tile di-hover (tile punya class `group`).
  const hoverCls =
    isPopup && trigger === "hover"
      ? "opacity-0 transition-opacity duration-200 group-hover:opacity-100"
      : "";
  // Interval (popup) + hover/click (marquee): sembunyi saat tidak tampil.
  const timedCls =
    (isPopup && trigger === "interval") ||
    (isMarquee && marqueeBehavior !== "always")
      ? `transition-opacity duration-300 ${visible ? "opacity-100" : "pointer-events-none opacity-0"}`
      : "";

  const inner = (
    <div
      className={`flex items-center gap-2.5 overflow-hidden border-white/10 px-3 py-1.5 ${borderSide} ${align}`}
      style={{
        width: `${Math.min(100, Math.max(10, config.box_width))}%`,
        margin:
          config.text_align === "center"
            ? "0 auto"
            : config.text_align === "right"
              ? "0 0 0 auto"
              : undefined,
        backgroundColor: hexA(config.bg_color, bgAlpha),
        minHeight: config.banner_height > 0 ? config.banner_height : 30,
        height: config.banner_height > 0 ? config.banner_height : undefined,
      }}
    >
      {config.image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={normalizeUploadUrl(config.image_url)}
          alt=""
          aria-hidden
          className="max-h-full shrink-0 rounded object-contain"
          style={{
            height: imgH,
            opacity: imgAlpha,
          }}
        />
      )}
      {config.marquee_text && (
        <div className="min-w-0 flex-1 overflow-hidden">
          {/* Teks SELALU berjalan, di semua mode dan perilaku. */}
          <div
            className="flex w-max whitespace-nowrap"
            style={{ animation: `nv-marquee ${duration}s linear infinite` }}
          >
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className="pr-16"
                style={{
                  color: hexA(config.text_color, txtAlpha),
                  fontSize: Math.min(24, Math.max(8, config.font_size)),
                  fontFamily: config.font_family || "monospace",
                }}
              >
                {config.marquee_text}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  const wrapCls = `absolute inset-x-0 ${position} z-20 ${hoverCls} ${timedCls} ${className}`;

  return (
    <div className={wrapCls}>
      <style>{`@keyframes nv-marquee { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }`}</style>
      {config.click_url?.trim() ? (
        <a
          href={config.click_url}
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-pointer"
          onClick={(e) => e.stopPropagation()}
        >
          {inner}
        </a>
      ) : (
        <div className="pointer-events-none">{inner}</div>
      )}
    </div>
  );
}

function hexA(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return `rgba(30,41,59,${alpha})`;
  const v = m[1];
  const r = parseInt(v.slice(0, 2), 16);
  const g = parseInt(v.slice(2, 4), 16);
  const b = parseInt(v.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
