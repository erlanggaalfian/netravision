"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { isAdminRole, useAuth } from "../lib/auth";
import { useCameraStatus } from "../hooks/useCameraStatus";
import { ThemeToggle } from "./ThemeToggle";

interface NavItem {
  href: string;
  label: string;
  adminOnly?: boolean;
  hideOnMobile?: boolean;
  icon: ReactNode;
}

function icon(path: string): ReactNode {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <path
        d={path}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const NAV: NavItem[] = [
  {
    href: "/live",
    label: "Live",
    icon: icon("M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z"),
  },
  {
    href: "/playback",
    label: "Putar Ulang",
    icon: icon("M6 4.5v11l9-5.5-9-5.5z"),
  },
  {
    href: "/maps",
    label: "Peta",
    icon: icon("M10 17.5s5.5-4.8 5.5-9a5.5 5.5 0 10-11 0c0 4.2 5.5 9 5.5 9zM10 10.5a2 2 0 100-4 2 2 0 000 4z"),
  },
  {
    href: "/monitors",
    label: "Monitor",
    hideOnMobile: true,
    icon: icon("M3 4.5h14v9H3zM7 17.5h6M10 13.5v4"),
  },
  {
    href: "/admin",
    label: "Admin",
    adminOnly: true,
    icon: icon("M10 2.5l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9v-5l7-3z"),
  },
];

/* Kerangka aplikasi: sidebar di desktop, tab bar bawah di mobile. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const { connected } = useCameraStatus();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const items = NAV.filter((n) => !n.adminOnly || isAdminRole(user?.role));
  /* Drawer menampilkan semua menu (termasuk yang disembunyikan dari tab bar). */
  const drawerItems = NAV.filter((n) => !n.adminOnly || isAdminRole(user?.role));

  const handleLogout = async () => {
    setDrawerOpen(false);
    await logout();
    router.push("/login");
  };

  /* Kunci scroll body + tutup dengan Escape saat drawer terbuka. */
  useEffect(() => {
    if (!drawerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [drawerOpen]);

  return (
    <div className="flex min-h-dvh bg-ink-950">
      {/* Sidebar desktop */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-white/8 bg-ink-900 md:flex">
        <div className="flex items-center gap-3 px-5 pb-1 pt-6">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-600 text-base font-extrabold tracking-tight text-onaccent shadow-[0_1px_2px_rgba(0,0,0,0.45)]">
            N
          </span>
          <div>
            <div className="text-[15px] font-bold tracking-tight text-white">
              NetraVision
            </div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
              <span
                className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-ok-400" : "bg-warn-400"}`}
              />
              {connected ? "Terhubung" : "Menghubungkan…"}
            </div>
          </div>
        </div>

        <nav className="flex flex-col gap-2 px-3 py-5" aria-label="Navigasi utama">
          {items.map((n) => {
            const active = pathname?.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`nv-glass relative flex min-h-[44px] items-center gap-3 rounded-full px-4 py-2.5 text-sm transition-all duration-150 ease-out active:scale-[0.98] ${
                  active
                    ? "nv-glass-active font-semibold text-onaccent"
                    : "font-medium text-slate-300 hover:-translate-y-px hover:text-white"
                }`}
              >
                <span className={active ? "text-accent-300" : ""}>{n.icon}</span>
                {n.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-white/8 p-4">
          <div className="mb-3 flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink-700 text-xs font-bold uppercase text-slate-200">
              {(user?.username ?? "?").slice(0, 1)}
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-100">
                {user?.username}
              </div>
              <div className="text-[11px] capitalize text-slate-400">
                {user?.role}
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleLogout}
              className="nv-glass min-h-[44px] flex-1 cursor-pointer rounded-full px-4 py-2.5 text-left text-sm font-medium text-slate-300 transition-all duration-150 ease-out hover:text-white active:scale-[0.98]"
            >
              Keluar
            </button>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {/* Konten */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar mobile */}
        <header className="flex items-center justify-between border-b border-white/8 bg-ink-900 px-4 py-3 md:hidden">
          <div className="flex items-center gap-2.5">
            <button
              onClick={() => setDrawerOpen(true)}
              aria-label="Buka menu"
              aria-expanded={drawerOpen}
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl text-slate-300 transition-all duration-150 hover:bg-white/5 hover:text-white active:scale-95"
            >
              <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden>
                <path
                  d="M3 6h16M3 11h16M3 16h16"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </button>
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-600 text-xs font-extrabold text-onaccent">
              N
            </span>
            <div>
              <div className="text-sm font-bold tracking-tight text-white">
                NetraVision
              </div>
              <div className="flex items-center gap-1 text-[10px] font-medium text-slate-400">
                <span
                  className={`h-1 w-1 rounded-full ${connected ? "bg-ok-400" : "bg-warn-400"}`}
                />
                {connected ? "Terhubung" : "Menghubungkan…"}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle className="h-11 w-11" />
            <button
              onClick={handleLogout}
              className="nv-glass min-h-[44px] cursor-pointer rounded-full px-4 text-xs font-semibold text-slate-300 transition-all duration-150 active:scale-95"
            >
              Keluar
            </button>
          </div>
        </header>

        <main className="min-w-0 flex-1 pb-20 md:pb-8">{children}</main>

        {/* Tab bar mobile */}
        <nav
          className="nv-glass fixed inset-x-4 bottom-4 z-40 flex rounded-2xl p-1 shadow-[0_4px_16px_rgba(0,0,0,0.35)] md:hidden"
          aria-label="Navigasi utama"
        >
          {items
            .filter((n) => !n.hideOnMobile)
            .map((n) => {
            const active = pathname?.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-h-[52px] flex-1 cursor-pointer flex-col items-center justify-center gap-0.5 text-[10px] font-medium leading-tight transition-colors duration-150 active:scale-95 ${
                  active ? "text-accent-300" : "text-slate-300"
                }`}
              >
                {active && (
                  <span
                    className="absolute inset-x-2 inset-y-1 rounded-lg bg-accent-500/20 ring-1 ring-accent-400/30"
                    aria-hidden
                  />
                )}
                {n.icon}
                {n.label}
              </Link>
            );
          })}
        </nav>
        {/* Drawer menu mobile ala aplikasi (geser dari kiri) */}
        <div
          className={`fixed inset-0 z-50 md:hidden ${drawerOpen ? "" : "pointer-events-none"}`}
          aria-hidden={!drawerOpen}
        >
          {/* Backdrop */}
          <div
            onClick={() => setDrawerOpen(false)}
            className={`absolute inset-0 bg-black/60 transition-opacity duration-200 ${
              drawerOpen ? "opacity-100" : "opacity-0"
            }`}
          />
          {/* Panel */}
          <aside
            role="dialog"
            aria-label="Menu"
            className={`absolute inset-y-0 left-0 flex w-[300px] max-w-[85vw] flex-col bg-ink-900 shadow-[8px_0_32px_rgba(0,0,0,0.4)] transition-transform duration-200 ease-out ${
              drawerOpen ? "translate-x-0" : "-translate-x-full"
            }`}
          >
            <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-600 text-xs font-extrabold text-onaccent">
                  N
                </span>
                <div>
                  <div className="text-sm font-bold tracking-tight text-white">
                    NetraVision
                  </div>
                  <div className="flex items-center gap-1 text-[10px] font-medium text-slate-400">
                    <span
                      className={`h-1 w-1 rounded-full ${connected ? "bg-ok-400" : "bg-warn-400"}`}
                    />
                    {connected ? "Terhubung" : "Menghubungkan…"}
                  </div>
                </div>
              </div>
              <button
                onClick={() => setDrawerOpen(false)}
                aria-label="Tutup menu"
                className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl text-slate-300 transition-all duration-150 hover:bg-white/5 hover:text-white active:scale-95"
              >
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
                  <path
                    d="M5 5l10 10M15 5L5 15"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>

            <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="Menu">
              {drawerItems.map((n) => {
                const active = pathname?.startsWith(n.href);
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    onClick={() => setDrawerOpen(false)}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-[48px] items-center gap-3 rounded-xl px-4 py-3 text-sm transition-all duration-150 active:scale-[0.98] ${
                      active
                        ? "bg-accent-500/15 font-semibold text-accent-300 ring-1 ring-accent-400/25"
                        : "font-medium text-slate-300 hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    {n.icon}
                    {n.label}
                  </Link>
                );
              })}
            </nav>

            <div className="border-t border-white/8 p-4">
              <div className="rounded-2xl bg-white/5 p-4 ring-1 ring-white/8">
                <div className="text-sm text-slate-300">
                  Halo,{" "}
                  <span className="font-bold text-white">{user?.username}</span>
                </div>
                <div className="mt-0.5 text-[11px] capitalize text-slate-400">
                  {user?.role}
                </div>
                <button
                  onClick={handleLogout}
                  className="mt-3 min-h-[48px] w-full cursor-pointer rounded-xl bg-red-600 px-4 text-sm font-semibold text-white transition-all duration-150 hover:bg-red-500 active:scale-[0.98]"
                >
                  Keluar
                </button>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
