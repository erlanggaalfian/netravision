"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { AdminGuard } from "../../components/AdminGuard";
import { AppShell } from "../../components/AppShell";
import { useAuth } from "../../lib/auth";

interface NavItem {
  href: string;
  label: string;
  icon: string;
  superAdminOnly?: boolean;
}

const NAV: NavItem[] = [
  { href: "/admin/streams", label: "Kamera", icon: "M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z" },
  { href: "/admin/users", label: "Pengguna", icon: "M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM3.5 17.5c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" },
  { href: "/admin/scanner", label: "Scanner", icon: "M4 8V5.5A1.5 1.5 0 015.5 4H8M12 4h2.5A1.5 1.5 0 0116 5.5V8M16 12v2.5a1.5 1.5 0 01-1.5 1.5H12M8 16H5.5A1.5 1.5 0 014 14.5V12M7 10h6", superAdminOnly: true },
  { href: "/admin/ads", label: "Iklan", icon: "M4 5h16v11H4zM4 16l4-4M20 16l-4-4", superAdminOnly: true },
  { href: "/admin/keys", label: "API Key", icon: "M10 13.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM10 2.5v3M10 14.5v3M2.5 10h3M14.5 10h3", superAdminOnly: true },
  { href: "/admin/storage", label: "Penyimpanan", icon: "M4 7l8-4 8 4-8 4-8-4zM4 7v10l8 4 8-4V7M12 11v8", superAdminOnly: true },
];

/* Pola persis Nexfiber Lainnya: grup + list divide-y, panel modern. */
function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-4">
      <h2 className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-[0.08em] text-slate-400">{title}</h2>
      <ul className="nv-panel-modern divide-y divide-slate-200/10 overflow-hidden !p-0">{children}</ul>
    </section>
  );
}

const row = "flex min-h-[48px] items-center gap-3 px-4 text-[15px]";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const visibleNav = NAV.filter((n) => !n.superAdminOnly || isSuperAdmin);

  return (
    <AdminGuard>
      <AppShell>
        <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:py-8">
          {/* Desktop: tab horizontal */}
          <nav aria-label="Navigasi admin" className="mb-5 hidden sm:mb-7 md:block">
            <div className="nv-scroll-x -mx-4 flex gap-2 overflow-x-auto px-4 py-2">
              {visibleNav.map((n) => {
                const cleanPath = (pathname ?? "").replace(/\/+$/, "") || "/";
                const active = cleanPath.startsWith(n.href + "/") || cleanPath === n.href;
                if (n.superAdminOnly && !isSuperAdmin && active && typeof window !== "undefined") {
                  window.location.href = "/admin/streams";
                  return null;
                }
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-[42px] shrink-0 cursor-pointer items-center whitespace-nowrap rounded-full px-4 text-sm transition-all duration-150 active:scale-[0.97] ${
                      active
                        ? "bg-gradient-to-r from-accent-600 to-accent-500 font-semibold text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                        : "bg-ink-800/60 font-medium text-slate-300 shadow-[0_1px_3px_rgba(0,0,0,0.2)] hover:bg-ink-800 hover:text-slate-200"
                    }`}
                  >
                    {n.label}
                  </Link>
                );
              })}
            </div>
          </nav>

          {/* Mobile: menu hanya di /admin, subhalaman langsung konten */}
          {(() => {
            const cleanPath = (pathname ?? "").replace(/\/+$/, "") || "/";
            const isAdminIndex = cleanPath === "/admin";
            return (
              <>
                {isAdminIndex && (
                  <nav aria-label="Navigasi admin" className="mb-5 md:hidden">
                    <Group title="Admin">
                      {visibleNav.map((n) => (
                        <li key={n.href}>
                          <Link href={n.href} className={`${row} text-slate-200 transition-colors hover:bg-ink-800/50 active:bg-ink-800/60`}>
                            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden className="shrink-0 text-slate-300">
                              <path d={n.icon} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                            <span className="flex-1">{n.label}</span>
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden className="shrink-0 text-slate-500">
                              <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          </Link>
                        </li>
                      ))}
                    </Group>
                  </nav>
                )}
                {/* Desktop tetap tampil menu tab; mobile subhalaman: sembunyikan children di /admin */}
                <div className={isAdminIndex ? "hidden md:block" : ""}>
                  {children}
                </div>
              </>
            );
          })()}
        </div>
      </AppShell>
    </AdminGuard>
  );
}
