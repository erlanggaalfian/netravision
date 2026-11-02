"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AdminGuard } from "../../components/AdminGuard";
import { useAuth } from "../../lib/auth";

const NAV = [
  { href: "/admin", label: "Dasbor", exact: true },
  { href: "/admin/streams", label: "Kamera" },
  { href: "/admin/users", label: "Pengguna" },
  { href: "/admin/groups", label: "Grup" },
  { href: "/admin/keys", label: "API Key" },
  { href: "/admin/ads", label: "Iklan" },
  { href: "/admin/drive", label: "Drive" },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { logout } = useAuth();

  return (
    <AdminGuard>
      <div className="min-h-screen bg-ink-950">
        <header className="sticky top-0 z-40 border-b border-ink-700/60 bg-ink-950/90 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
            <div className="flex items-center gap-3">
              <button
                onClick={() => router.push("/live")}
                className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 hover:bg-ink-800 hover:text-white"
                aria-label="Kembali ke pantauan"
              >
                ←
              </button>
              <p className="font-semibold text-white">Konsol Admin</p>
            </div>
            <button
              onClick={() => logout().then(() => router.push("/login"))}
              className="flex min-h-[40px] items-center rounded-lg px-3 text-sm text-slate-400 hover:bg-ink-800 hover:text-white"
            >
              Keluar
            </button>
          </div>
          <nav className="mx-auto max-w-6xl overflow-x-auto px-4 pb-3">
            <div className="flex gap-1">
              {NAV.map((n) => {
                const active = n.exact
                  ? pathname === n.href
                  : pathname.startsWith(n.href + "/") || pathname === n.href;
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    className={`whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                      active
                        ? "bg-accent-600/20 text-accent-300"
                        : "text-slate-400 hover:bg-ink-800 hover:text-slate-200"
                    }`}
                  >
                    {n.label}
                  </Link>
                );
              })}
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-5 sm:py-8">{children}</main>
      </div>
    </AdminGuard>
  );
}
