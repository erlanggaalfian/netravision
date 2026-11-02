"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "../lib/auth";
import { useCameraStatus } from "../hooks/useCameraStatus";

interface NavItem {
  href: string;
  label: string;
  adminOnly?: boolean;
  icon: ReactNode;
}

function icon(path: string): ReactNode {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
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

  const items = NAV.filter((n) => !n.adminOnly || user?.role === "admin");

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  return (
    <div className="flex min-h-dvh bg-ink-950">
      {/* Sidebar desktop */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-white/10 bg-ink-900 md:flex">
        <div className="flex items-center gap-2 px-5 pb-2 pt-6">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-600 text-sm font-bold text-white">
            N
          </span>
          <div>
            <div className="text-sm font-bold tracking-wide text-white">
              NetraVision
            </div>
            <div className="flex items-center gap-1.5 text-[11px] text-neutral-400">
              <span
                className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-ok-400" : "bg-warn-400"}`}
              />
              {connected ? "Terhubung" : "Menghubungkan…"}
            </div>
          </div>
        </div>
        <nav className="flex flex-col gap-1 px-3 py-4">
          {items.map((n) => {
            const active = pathname?.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
                  active
                    ? "bg-accent-600/15 text-accent-300"
                    : "text-neutral-400 hover:bg-white/5 hover:text-white"
                }`}
              >
                {n.icon}
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto border-t border-white/10 p-4">
          <div className="mb-2 truncate text-xs text-neutral-400">
            {user?.username} · {user?.role}
          </div>
          <button
            onClick={handleLogout}
            className="w-full rounded-lg bg-white/5 px-3 py-2 text-left text-sm text-neutral-300 transition hover:bg-white/10 active:scale-[0.99]"
          >
            Keluar
          </button>
        </div>
      </aside>

      {/* Konten */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar mobile */}
        <header className="flex items-center justify-between border-b border-white/10 bg-ink-900 px-4 py-3 md:hidden">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-600 text-xs font-bold text-white">
              N
            </span>
            <span className="text-sm font-bold text-white">NetraVision</span>
          </div>
          <button
            onClick={handleLogout}
            className="rounded-lg bg-white/5 px-3 py-2 text-xs text-neutral-300 active:scale-95"
          >
            Keluar
          </button>
        </header>

        <main className="min-w-0 flex-1 pb-24 md:pb-8">{children}</main>

        {/* Tab bar mobile */}
        <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-white/10 bg-ink-900/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
          {items.map((n) => {
            const active = pathname?.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`flex min-h-[56px] flex-1 flex-col items-center justify-center gap-1 text-[10px] transition active:scale-95 ${
                  active ? "text-accent-300" : "text-neutral-500"
                }`}
              >
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
