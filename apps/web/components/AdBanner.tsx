"use client";

import { useEffect, useState } from "react";
import type { AdConfig } from "../lib/types";
import { normalizeUploadUrl } from "../lib/api";

interface Props {
  config: AdConfig;
  className?: string;
}

/* Banner iklan fleksibel (2026-11-06):
   - Posisi: bawah | atas
   - Mode: marquee (teks berjalan) | popup (berkala) | static (diam)
   - Trigger popup: always (terus) | interval (tampil/sembunyi bergantian) | hover (saat hover video)
   - Klik: buka click_url di tab baru bila diisi
   Selalu gelap (area video). */
export function AdBanner({ config, className = "" }: Props) {
  const [visible, setVisible] = useState(true);

  const isPopup = config.display_mode === "popup";
  const trigger = config.popup_trigger || "always";

  /* Popup interval: tampil X detik, sembunyi Y detik, berulang. */
  useEffect(() => {
    if (!isPopup || trigger !== "interval") {
      setVisible(true);
      return;
    }
    const showMs = Math.max(1, config.popup_show_seconds || 10) * 1000;
    const hideMs = Math.max(1, config.popup_hide_seconds || 50) * 1000;
    let timeout: ReturnType<typeof setTimeout>;
    let alive = true;
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

  // Hover: sembunyi sampai tile di-hover (tile punya class `group`).
  const hoverCls =
    isPopup && trigger === "hover"
      ? "opacity-0 transition-opacity duration-200 group-hover:opacity-100"
      : "";
  // Interval: sembunyi saat fase hide.
  const intervalCls =
    isPopup && trigger === "interval"
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
          className="shrink-0 rounded object-contain"
          style={{
            height: Math.min(60, Math.max(10, config.image_height)),
            opacity: imgAlpha,
          }}
        />
      )}
      {config.marquee_text && (
        <div className="min-w-0 flex-1 overflow-hidden">
          {config.display_mode === "static" || (isPopup && trigger !== "always") ? (
            <span
              className="block truncate whitespace-nowrap"
              style={{
                color: hexA(config.text_color, txtAlpha),
                fontSize: Math.min(24, Math.max(8, config.font_size)),
                fontFamily: config.font_family || "monospace",
              }}
            >
              {config.marquee_text}
            </span>
          ) : (
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
          )}
        </div>
      )}
    </div>
  );

  const wrapCls = `absolute inset-x-0 ${position} z-20 ${hoverCls} ${intervalCls} ${className}`;

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
