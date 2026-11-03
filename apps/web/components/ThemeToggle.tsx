"use client";

import { useTheme } from "../hooks/useTheme";

/* Toggle mode gelap/terang. 44px, ikon SVG matahari/bulan. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
      title={dark ? "Mode terang" : "Mode gelap"}
      className={`nv-glass flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-full text-neutral-300 transition hover:text-white active:scale-95 ${className}`}
    >
      {dark ? (
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
          <path
            d="M10 13.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7z"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <path
            d="M10 1.8v2M10 16.2v2M1.8 10h2M16.2 10h2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M15.8 4.2l-1.4 1.4M5.6 14.4l-1.4 1.4"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
          <path
            d="M16.5 12.5A7 7 0 017.5 3.5a7 7 0 109 9z"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  );
}
