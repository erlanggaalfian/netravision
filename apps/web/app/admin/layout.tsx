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
            <div className="-mx-4 flex gap-6 overflow-x-auto px-4">
              {NAV.map((n) => {
                const active = n.exact
                  ? pathname === n.href
                  : pathname.startsWith(n.href + "/") || pathname === n.href;
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-[44px] shrink-0 items-center whitespace-nowrap border-b-2 text-sm transition-colors ${
                      active
                        ? "border-accent-500 font-semibold text-white"
                        : "border-transparent font-medium text-slate-400 hover:border-ink-600 hover:text-slate-200"
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
