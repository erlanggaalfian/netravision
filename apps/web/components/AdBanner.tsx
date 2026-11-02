"use client";

import type { AdConfig } from "../lib/types";

interface Props {
  config: AdConfig;
  className?: string;
}

/* Banner iklan lower-third ala v2.0 (popup guest / embed).
   Selalu gelap (area video), mengikuti 16 field AdConfig. */
export function AdBanner({ config, className = "" }: Props) {
  if (!config.is_active) return null;

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

  return (
    <div className={`pointer-events-none absolute inset-x-0 bottom-0 z-20 ${className}`}>
      <style>{`@keyframes nv-marquee { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }`}</style>
      <div
        className={`flex items-center gap-2.5 overflow-hidden border-t border-white/10 px-3 py-1.5 ${align}`}
        style={{
          width: `${Math.min(100, Math.max(10, config.box_width))}%`,
          margin:
            config.text_align === "center"
              ? "0 auto"
              : config.text_align === "right"
                ? "0 0 0 auto"
                : undefined,
          backgroundColor: hexA(config.bg_color, bgAlpha),
          minHeight: 30,
        }}
      >
        {config.image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={config.image_url}
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
            <div
              className="flex w-max whitespace-nowrap"
              style={{ animation: `nv-marquee ${duration}s linear infinite` }}
            >
              {[0, 1].map((i) => (
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
