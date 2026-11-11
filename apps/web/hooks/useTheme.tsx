"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export type Theme = "dark" | "light";

const KEY = "nv-theme";

function resolveInitial(): Theme {
  if (typeof window === "undefined") return "dark";
  // Skrip anti-FOUC di <head> sudah menulis data-theme sebelum paint.
  const attr = document.documentElement.dataset.theme;
  if (attr === "dark" || attr === "light") return attr;
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch {
    /* abaikan */
  }
  // Hormati prefers-color-scheme hanya bila belum ada preferensi tersimpan.
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({
  theme: "dark",
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Inisialisasi malas dari resolveInitial() agar tidak menimpa nilai
  // anti-FOUC (data-theme di <html>) dengan "dark" hardcoded lalu
  // menulisnya ke localStorage sebelum render pertama yang benar.
  const [theme, setTheme] = useState<Theme>(resolveInitial);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* abaikan (mode privat) */
    }
  }, [theme]);

  const toggle = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return (
    <ThemeCtx.Provider value={{ theme, toggle }}>
      {children}
    </ThemeCtx.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeCtx);
}
