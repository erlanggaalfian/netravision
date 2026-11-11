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
  /* placement: "overlay" = menempel di atas video (posisi bawah/atas
     mengikuti config.position); "below" = strip di bawah video, di luar
     area 16:9, tidak menutupi video maupun tombol. Mode berkala yang
     sedang sembunyi tetap mengambil ruang supaya tinggi tile stabil. */
  placement?: "overlay" | "below";
}

/* Banner iklan fleksibel (2026-11-06):
   - Posisi: bawah | atas
   - Jenis tampilan: always (selalu tampil) | periodic (berkala).
     Teks SELALU berjalan di semua pilihan, tidak ada statis.
   - Cara tampil berkala: interval (tampil/sembunyi bergantian) |
     hover (terlihat saat hover + jeda setelah hover) | click (muncul
     saat tile diklik, hilang lagi setelah X detik)
   - Klik banner: buka click_url di tab baru bila diisi
   Selalu gelap (area video). */
export function AdBanner({
  config,
  className = "",
  hovered = false,
  clickTick = 0,
  placement = "overlay",
}: Props) {
  const [visible, setVisible] = useState(true);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const isPeriodic = config.display_mode === "periodic";
  const trigger = config.periodic_trigger || "interval";

  const later = (fn: () => void, ms: number) => {
    const t = setTimeout(fn, ms);
    timers.current.push(t);
    return t;
  };
  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  /* Reset saat jenis tampilan / cara tampil berubah. */
  useEffect(() => {
    clearTimers();
    setVisible(!isPeriodic);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPeriodic, trigger]);

  /* Berkala + interval: tampil X detik, sembunyi Y detik, berulang. */
  useEffect(() => {
    if (!isPeriodic || trigger !== "interval") return;
    const showMs = Math.max(1, config.popup_show_seconds || 10) * 1000;
    const hideMs = Math.max(1, config.popup_hide_seconds || 50) * 1000;
    let alive = true;
    let timeout: ReturnType<typeof setTimeout>;
    const tick = (show: boolean) => {
      if (!alive) return;
      setVisible(show);
      timeout = setTimeout(() => tick(!show), show ? showMs : hideMs);
    };
    /* Siklus pertama langsung tampil, bukan menunggu showMs+hideMs. */
    setVisible(true);
    timeout = setTimeout(() => tick(false), showMs);
    return () => {
      alive = false;
      clearTimeout(timeout);
    };
  }, [
    isPeriodic,
    trigger,
    config.popup_show_seconds,
    config.popup_hide_seconds,
  ]);

  /* Berkala + hover: saat tile di-hover, tampil X detik; setelah hover
     selesai, iklan MASIH tampil selama jeda, baru hilang. Hover lagi
     membatalkan timer hilang dan menampilkan lagi (tanpa cooldown). */
  const hoverShowMs = Math.max(1, config.marquee_hover_show_seconds || 5) * 1000;
  const hoverHideDelayMs =
    Math.max(0, config.marquee_hover_hide_delay_seconds || 5) * 1000;
  /* Nilai hovered terbaru untuk dipakai di dalam timer, supaya iklan
     tidak disembunyikan saat pointer masih di atas tile. */
  const hoveredRef = useRef(hovered);
  hoveredRef.current = hovered;
  useEffect(() => {
    if (!isPeriodic || trigger !== "hover") return;
    if (!hovered) return;
    clearTimers();
    setVisible(true);
    later(() => {
      /* Masih di-hover: tetap tampil, baru hilang setelah jeda
         pasca-hover yang dijadwalkan effect di bawah. */
      if (hoveredRef.current) return;
      setVisible(false);
    }, hoverShowMs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPeriodic, trigger, hovered]);

  /* Hover selesai: tahan tampil selama jeda, baru hilang. */
  const wasHovered = useRef(false);
  useEffect(() => {
    if (!isPeriodic || trigger !== "hover") return;
    if (wasHovered.current && !hovered) {
      clearTimers();
      later(() => setVisible(false), hoverHideDelayMs);
    }
    wasHovered.current = hovered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hovered]);

  /* Berkala + click: tiap tile diklik, tampil X detik lalu hilang lagi. */
  const clickShowMs = Math.max(1, config.marquee_click_show_seconds || 5) * 1000;
  const firstTick = useRef(true);
  useEffect(() => {
    if (firstTick.current) {
      firstTick.current = false;
      return;
    }
    if (!isPeriodic || trigger !== "click") return;
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

  // Berkala: sembunyi saat tidak tampil.
  const timedCls = isPeriodic
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

  const wrapCls =
    placement === "below"
      ? `relative w-full ${timedCls} ${className}`
      : `absolute inset-x-0 ${position} z-20 ${timedCls} ${className}`;

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
