"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
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

  const items = NAV.filter((n) => !n.adminOnly || isAdminRole(user?.role));

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

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

        <main className="min-w-0 flex-1 pb-24 md:pb-8">{children}</main>

        {/* Tab bar mobile */}
        <nav
          className="nv-glass fixed inset-x-3 bottom-3 z-40 flex rounded-2xl px-1.5 py-1.5 shadow-[0_4px_16px_rgba(0,0,0,0.35)] md:hidden"
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
                className={`relative flex min-h-[60px] flex-1 cursor-pointer flex-col items-center justify-center gap-1 text-[10px] font-medium transition-colors duration-150 active:scale-95 ${
                  active ? "text-accent-300" : "text-slate-300"
                }`}
              >
                {active && (
                  <span
                    className="absolute inset-x-1 inset-y-0.5 rounded-xl bg-accent-500/20 ring-1 ring-accent-400/30"
                    aria-hidden
                  />
                )}
                {n.icon}
                {n.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
