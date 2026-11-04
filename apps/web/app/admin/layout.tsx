"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { AdminGuard } from "../../components/AdminGuard";
import { AppShell } from "../../components/AppShell";
import { useAuth } from "../../lib/auth";

interface SubItem {
  href: string;
  label: string;
}

interface NavItem {
  label: string;
  desc: string;
  icon: string;
  superAdminOnly?: boolean;
  subs: SubItem[];
}

const NAV: NavItem[] = [
  {
    label: "Kamera", desc: "Kelola kamera CCTV",
    icon: "M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z",
    subs: [
      { href: "/admin/streams", label: "Daftar Kamera" },
    ],
  },
  {
    label: "Pengguna", desc: "Kelola akun pengguna",
    icon: "M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM3.5 17.5c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6",
    subs: [
      { href: "/admin/users", label: "Daftar Pengguna" },
    ],
  },
  {
    label: "Akses", desc: "Hak akses kamera",
    icon: "M10 2.5l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9v-5l7-3z",
    subs: [
      { href: "/admin/access", label: "Kelola Akses" },
    ],
  },
  {
    label: "Scanner", desc: "Pindai kamera jaringan",
    icon: "M4 8V5.5A1.5 1.5 0 015.5 4H8M12 4h2.5A1.5 1.5 0 0116 5.5V8M16 12v2.5a1.5 1.5 0 01-1.5 1.5H12M8 16H5.5A1.5 1.5 0 014 14.5V12M7 10h6",
    superAdminOnly: true,
    subs: [
      { href: "/admin/scanner", label: "Pindai Jaringan" },
    ],
  },
  {
    label: "Iklan", desc: "Banner iklan kamera",
    icon: "M4 5h16v11H4zM4 16l4-4M20 16l-4-4",
    superAdminOnly: true,
    subs: [
      { href: "/admin/ads", label: "Konfigurasi Iklan" },
    ],
  },
  {
    label: "API Key", desc: "Kunci akses API",
    icon: "M10 13.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM10 2.5v3M10 14.5v3M2.5 10h3M14.5 10h3",
    superAdminOnly: true,
    subs: [
      { href: "/admin/keys", label: "Daftar API Key" },
    ],
  },
  {
    label: "Penyimpanan", desc: "Google Drive",
    icon: "M4 7l8-4 8 4-8 4-8-4zM4 7v10l8 4 8-4V7M12 11v8",
    superAdminOnly: true,
    subs: [
      { href: "/admin/storage", label: "Folder Drive" },
    ],
  },
];

function NavIcon({ path }: { path: string }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <path d={path} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const visibleNav = NAV.filter((n) => !n.superAdminOnly || isSuperAdmin);
  const [expanded, setExpanded] = useState<string | null>(null);

  const toggle = (label: string) => {
    setExpanded((prev) => (prev === label ? null : label));
  };

  return (
    <AdminGuard>
      <AppShell>
        <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:py-8">
          {/* Desktop: tab horizontal */}
          <nav aria-label="Navigasi admin" className="mb-5 hidden sm:mb-7 md:block">
            <div className="nv-scroll-x -mx-4 flex gap-2 overflow-x-auto px-4 py-2">
              {visibleNav.map((n) => {
                const href = n.subs[0].href;
                const cleanPath = (pathname ?? "").replace(/\/+$/, "") || "/";
                const active = cleanPath.startsWith(href + "/") || cleanPath === href;
                if (n.superAdminOnly && !isSuperAdmin && active && typeof window !== "undefined") {
                  window.location.href = "/admin/streams";
                  return null;
                }
                return (
                  <Link
                    key={n.label}
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-[42px] shrink-0 cursor-pointer items-center whitespace-nowrap rounded-full px-4 text-sm transition-all duration-150 active:scale-[0.97] ${
                      active
                        ? "bg-gradient-to-r from-accent-600 to-accent-500 font-semibold text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                        : "font-medium text-slate-300 hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    {n.label}
                  </Link>
                );
              })}
            </div>
          </nav>

          {/* Mobile: accordion ala aplikasi */}
          <nav aria-label="Navigasi admin" className="mb-5 md:hidden">
            <div className="nv-panel-modern divide-y divide-white/5 overflow-hidden">
              {visibleNav.map((n) => {
                const isOpen = expanded === n.label;
                const cleanPath = (pathname ?? "").replace(/\/+$/, "") || "/";
                const isActiveSection = n.subs.some(
                  (s) => cleanPath === s.href || cleanPath.startsWith(s.href + "/")
                );
                return (
                  <div key={n.label}>
                    <button
                      type="button"
                      onClick={() => toggle(n.label)}
                      aria-expanded={isOpen}
                      className={`flex min-h-[60px] w-full cursor-pointer items-center gap-3 px-4 text-left transition-colors active:bg-white/5 ${
                        isActiveSection ? "bg-accent-600/10" : ""
                      }`}
                    >
                      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${isActiveSection ? "bg-gradient-to-b from-accent-500 to-accent-600 text-onaccent" : "bg-white/5 text-slate-300"}`}>
                        <NavIcon path={n.icon} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[15px] font-semibold text-slate-200">
                          {n.label}
                        </span>
                        <span className="block truncate text-xs text-slate-400">
                          {n.desc}
                        </span>
                      </span>
                      <svg
                        width="16" height="16" viewBox="0 0 16 16" fill="none"
                        className={`shrink-0 text-slate-400 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                        aria-hidden
                      >
                        <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </button>
                    {isOpen && (
                      <div className="border-t border-white/5 bg-black/20">
                        {n.subs.map((s) => {
                          const subActive = cleanPath === s.href || cleanPath.startsWith(s.href + "/");
                          return (
                            <Link
                              key={s.href}
                              href={s.href}
                              className={`flex min-h-[48px] cursor-pointer items-center gap-3 px-4 pl-[68px] text-sm transition-colors active:bg-white/5 ${
                                subActive ? "font-semibold text-accent-300" : "text-slate-300"
                              }`}
                            >
                              <span className={`h-1.5 w-1.5 rounded-full ${subActive ? "bg-accent-400" : "bg-slate-500"}`} />
                              {s.label}
                            </Link>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </nav>

          {children}
        </div>
      </AppShell>
    </AdminGuard>
  );
}
