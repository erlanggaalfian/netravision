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

        <nav className="flex flex-col gap-1 px-3 py-5" aria-label="Navigasi utama">
          {items.map((n) => {
            const active = pathname?.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-h-[44px] items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-150 ease-out ${
                  active
                    ? "bg-accent-500/10 text-white"
                    : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-100"
                }`}
              >
                {active && (
                  <span
                    className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-accent-400"
                    aria-hidden
                  />
                )}
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
              <div className="text-[11px] capitalize text-slate-500">
                {user?.role}
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleLogout}
              className="min-h-[44px] flex-1 cursor-pointer rounded-xl bg-white/[0.04] px-3 py-2.5 text-left text-sm font-medium text-slate-300 transition-all duration-150 ease-out hover:bg-white/[0.08] hover:text-white active:scale-[0.99]"
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
              <div className="flex items-center gap-1 text-[10px] font-medium text-slate-500">
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
              className="min-h-[44px] cursor-pointer rounded-xl bg-white/[0.04] px-4 text-xs font-semibold text-slate-300 transition-colors duration-150 active:scale-95"
            >
              Keluar
            </button>
          </div>
        </header>

        <main className="min-w-0 flex-1 pb-24 md:pb-8">{children}</main>

        {/* Tab bar mobile */}
        <nav
          className="fixed inset-x-0 bottom-0 z-40 flex border-t border-white/8 bg-ink-900 pb-[env(safe-area-inset-bottom)] md:hidden"
          aria-label="Navigasi utama"
        >
          {items.map((n) => {
            const active = pathname?.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-h-[60px] flex-1 cursor-pointer flex-col items-center justify-center gap-1 text-[10px] font-medium transition-colors duration-150 active:scale-95 ${
                  active ? "text-accent-300" : "text-slate-500"
                }`}
              >
                {active && (
                  <span
                    className="absolute top-0 h-[2.5px] w-10 rounded-full bg-accent-400"
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
