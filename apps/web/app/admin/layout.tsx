"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { AdminGuard } from "../../components/AdminGuard";
import { AppShell } from "../../components/AppShell";
import { PRIMARY_GRADIENT } from "../../components/ui";
import { useAuth } from "../../lib/auth";

interface NavItem {
  href: string;
  label: string;
  icon: string;
  superAdminOnly?: boolean;
}

const NAV: NavItem[] = [
  { href: "/admin/streams", label: "Kamera", icon: "M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z" },
  { href: "/admin/groups", label: "Grup Kamera", icon: "M7 8a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 14.5c0-2.8 2-4.5 4.5-4.5s4.5 1.7 4.5 4.5M13.5 8a2.5 2.5 0 100-5M14 10.2c2.3.3 3.5 1.9 3.5 4.3" },
  { href: "/admin/users", label: "Pengguna", icon: "M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM3.5 17.5c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" },
  { href: "/admin/scanner", label: "Scanner", icon: "M4 8V5.5A1.5 1.5 0 015.5 4H8M12 4h2.5A1.5 1.5 0 0116 5.5V8M16 12v2.5a1.5 1.5 0 01-1.5 1.5H12M8 16H5.5A1.5 1.5 0 014 14.5V12M7 10h6", superAdminOnly: true },
  { href: "/admin/ads", label: "Iklan", icon: "M4 5h16v11H4zM4 16l4-4M20 16l-4-4", superAdminOnly: true },
  { href: "/admin/keys", label: "API Key", icon: "M10 13.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM10 2.5v3M10 14.5v3M2.5 10h3M14.5 10h3", superAdminOnly: true },
  { href: "/admin/storage", label: "Penyimpanan", icon: "M4 7l8-4 8 4-8 4-8-4zM4 7v10l8 4 8-4V7M12 11v8", superAdminOnly: true },
  { href: "/admin/diagnostics", label: "Diagnostik", icon: "M3 12h4l3 8 4-16 3 8h4", superAdminOnly: true },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const visibleNav = NAV.filter((n) => !n.superAdminOnly || isSuperAdmin);
  /* E-K1: periksa rute yang diminta terhadap daftar superAdminOnly
     SEBELUM render, bukan dari visibleNav yang sudah difilter. */
  const cleanPath = (pathname ?? "").replace(/\/+$/, "") || "/";
  const restricted =
    !isSuperAdmin &&
    NAV.some(
      (n) =>
        n.superAdminOnly &&
        (cleanPath === n.href || cleanPath.startsWith(n.href + "/")),
    );
  useEffect(() => {
    if (user && restricted) {
      router.replace("/admin/streams");
    }
  }, [user, restricted, router]);
  if (user && restricted) return null;

  return (
    <AdminGuard>
      <AppShell>
        <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:py-8">
          {/* Tab horizontal di SEMUA lebar (termasuk HP): bisa di-scroll
              horizontal (nv-scroll-x) supaya pengguna HP di subhalaman
              tetap bisa pindah bagian tanpa tombol back browser. */}
          <nav aria-label="Navigasi admin" className="mb-5 sm:mb-7">
            <div className="nv-scroll-x -mx-4 flex gap-2 overflow-x-auto px-4 py-2">
              {visibleNav.map((n) => {
                const cleanPath = (pathname ?? "").replace(/\/+$/, "") || "/";
                const active = cleanPath.startsWith(n.href + "/") || cleanPath === n.href;
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-[44px] shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap rounded-full px-4 text-sm transition-all duration-150 active:scale-[0.97] ${
                      active
                        ? PRIMARY_GRADIENT + " font-semibold"
                        : "bg-ink-800/60 font-medium text-slate-300 shadow-[0_1px_3px_rgba(0,0,0,0.2)] hover:bg-ink-800 hover:text-slate-200"
                    }`}
                  >
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden className="shrink-0">
                      <path d={n.icon} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {n.label}
                  </Link>
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
