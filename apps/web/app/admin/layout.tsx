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

function ChevronLeftIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}

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
        <header className="sticky top-0 z-40 border-b border-ink-700/60 bg-ink-950/95">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
            <div className="flex items-center gap-2">
              <button
                onClick={() => router.push("/live")}
                className="flex h-11 w-11 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-ink-800 hover:text-white"
                aria-label="Kembali ke pantauan"
              >
                <ChevronLeftIcon />
              </button>
              <p className="text-[15px] font-semibold tracking-tight text-white">
                Konsol Admin
              </p>
            </div>
            <button
              onClick={() => logout().then(() => router.push("/login"))}
              className="flex min-h-[44px] items-center rounded-lg px-3 text-sm text-slate-400 transition-colors hover:bg-ink-800 hover:text-white"
            >
              Keluar
            </button>
          </div>
          <nav aria-label="Navigasi admin">
            <div className="mx-auto max-w-6xl px-4">
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
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-5 sm:py-8">{children}</main>
      </div>
    </AdminGuard>
  );
}
