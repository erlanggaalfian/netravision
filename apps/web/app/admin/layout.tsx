"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AdminGuard } from "../../components/AdminGuard";
import { AppShell } from "../../components/AppShell";

const NAV = [
  { href: "/admin", label: "Dasbor", exact: true },
  { href: "/admin/streams", label: "Kamera" },
  { href: "/admin/users", label: "Pengguna" },
  { href: "/admin/groups", label: "Grup" },
  { href: "/admin/keys", label: "API Key" },
  { href: "/admin/ads", label: "Iklan" },
  { href: "/admin/storage", label: "Penyimpanan" },
  { href: "/admin/scanner", label: "Scanner" },
  { href: "/admin/access", label: "Akses" },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <AdminGuard>
      <AppShell>
        <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:py-8">
          <nav aria-label="Navigasi admin" className="mb-5 sm:mb-7">
            <div className="nv-scroll-x -mx-4 flex gap-2 overflow-x-auto px-4 py-2">
              {NAV.map((n) => {
                const active = n.exact
                  ? pathname === n.href
                  : pathname.startsWith(n.href + "/") || pathname === n.href;
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={`nv-glass flex min-h-[42px] shrink-0 cursor-pointer items-center whitespace-nowrap rounded-full px-4 text-sm transition-all duration-150 active:scale-[0.97] ${
                      active
                        ? "nv-glass-active font-semibold text-white"
                        : "font-medium text-slate-300 hover:-translate-y-px hover:text-white"
                    }`}
                  >
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
