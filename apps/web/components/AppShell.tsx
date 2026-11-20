"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { isAdminRole, useAuth } from "../lib/auth";
import { useCameraStatus } from "../hooks/useCameraStatus";
import { useIdleLogout } from "../hooks/useIdleLogout";
import { PRIMARY_GRADIENT } from "./ui";
import { GoogleDriveReminder } from "./GoogleDriveReminder";
import { ThemeToggle } from "./ThemeToggle";

interface NavItem {
  href: string;
  label: string;
  adminOnly?: boolean;
  hideOnMobile?: boolean;
  /* Jangan prefetch: halaman ini membawa CSS/JS berat yang hanya
     dipakai saat halaman dibuka (mis. Leaflet di Peta). Prefetch
     membuat browser memuat CSS-nya lebih dulu lalu memperingatkan
     "preloaded but not used" bila user tidak segera membuka halaman. */
  noPrefetch?: boolean;
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
    noPrefetch: true,
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

/* Kerangka aplikasi: sidebar di desktop, tab bar bawah di mobile.
   Bahasa desain mengikuti NetBackup: navbar biru solid, kartu putih,
   tab bar bawah putih menempel. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const { connected } = useCameraStatus();
  /* Keluar memanggil POST /auth/logout dulu: nonaktifkan kedua tombol
     Keluar selama proses supaya tidak diklik ganda. */
  const [loggingOut, setLoggingOut] = useState(false);
  /* Diam 1 jam tanpa gerakan -> minta login lagi; selama masih ada
     pengoperasian, sesi tidak putus. F3.6: hook mengembalikan status
     peringatan supaya banner hitung mundur bisa dirender di sini. */
  const { idleWarning, idleSecondsLeft, stayLoggedIn } = useIdleLogout();

  const items = NAV.filter((n) => !n.adminOnly || isAdminRole(user?.role));

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    await logout();
    router.push("/login");
  };

  return (
    <div className="flex min-h-dvh bg-ink-950">
      {/* Sidebar desktop */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-ink-800 bg-ink-900 md:flex">
        <div className="flex items-center gap-3 px-5 pb-1 pt-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {/* F5.11: turunan kecil logo-96.webp (4,1 KB), bukan logo.png 174 KB. */}
          <img
            src="/icons/logo-96.webp"
            alt="Logo NetraVision"
            width={40}
            height={40}
            className="h-10 w-10 object-contain"
          />
          <div>
            <div className="text-[15px] font-bold tracking-tight text-slate-300">
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
                prefetch={n.noPrefetch ? false : undefined}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-[44px] items-center gap-3 rounded-xl px-4 py-2.5 text-sm transition-colors duration-150 active:scale-[0.98] ${
                  active
                    ? `${PRIMARY_GRADIENT} font-semibold`
                    : "font-medium text-slate-400 hover:bg-ink-800 hover:text-slate-200"
                }`}
              >
                {n.icon}
                {n.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-ink-800 p-4">
          <div className="mb-3 flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-500/10 text-xs font-bold uppercase text-accent-text">
              {(user?.username ?? "?").slice(0, 1)}
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-300">
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
              disabled={loggingOut}
              className="min-h-[44px] flex-1 cursor-pointer rounded-xl bg-ink-800 px-4 py-2.5 text-left text-sm font-medium text-slate-400 shadow-sm transition-all duration-150 ease-out hover:bg-ink-700 hover:text-slate-200 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loggingOut ? "Keluar…" : "Keluar"}
            </button>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {/* Konten */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar mobile */}
        <header className="flex items-center justify-between border-b border-ink-800 bg-ink-900 px-4 py-3 md:hidden">
          <div className="flex items-center gap-2.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {/* F5.11: turunan kecil logo-64.webp (2,6 KB), bukan logo.png 174 KB. */}
            <img
              src="/icons/logo-64.webp"
              alt="Logo NetraVision"
              width={32}
              height={32}
              className="h-8 w-8 object-contain"
            />
            <div>
              <div className="text-sm font-bold tracking-tight text-slate-200">
                NetraVision
              </div>
              <div className="flex items-center gap-1 text-[11px] font-medium text-slate-400">
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
              disabled={loggingOut}
              className="min-h-[44px] cursor-pointer rounded-xl bg-ink-800 px-4 text-xs font-semibold text-slate-300 shadow-sm transition-all duration-150 hover:bg-ink-700 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loggingOut ? "Keluar…" : "Keluar"}
            </button>
          </div>
        </header>

        <main className="min-w-0 flex-1 pb-[72px] md:pb-8">{children}</main>

        {/* F3.6: peringatan sebelum logout paksa karena diam, dengan
            tombol "Tetap masuk". Sesi guest tidak pernah sampai ke sini
            (guest diperbarui diam-diam di hook). */}
        {idleWarning && (
          <div
            role="alertdialog"
            aria-live="assertive"
            aria-label="Sesi hampir berakhir"
            className="fixed inset-x-3 bottom-[76px] z-[80] flex flex-col gap-3 rounded-2xl bg-ink-800 p-4 shadow-[0_8px_24px_-8px_rgba(0,0,0,0.5)] ring-1 ring-ink-600/40 sm:inset-x-auto sm:bottom-6 sm:right-6 sm:w-[380px] md:bottom-6"
          >
            <p className="text-sm font-semibold text-slate-100">
              Sesi Anda akan berakhir dalam {idleSecondsLeft} detik
            </p>
            <p className="text-xs text-slate-400">
              Tidak ada aktivitas selama hampir 1 jam. Ketuk Tetap masuk
              supaya sesi tidak putus.
            </p>
            <button
              onClick={stayLoggedIn}
              className={`flex min-h-[48px] w-full cursor-pointer items-center justify-center rounded-xl px-4 text-sm font-semibold transition active:scale-[0.98] ${PRIMARY_GRADIENT}`}
            >
              Tetap masuk
            </button>
          </div>
        )}

        {/* Tab bar mobile: menempel bawah, ikut tema terang/gelap
            (bg-ink-900 + border-ink-800, sama seperti sidebar/topbar),
            dengan padding safe-area. */}
        <nav
          className="fixed inset-x-0 bottom-0 z-40 flex border-t border-ink-800 bg-ink-900 px-2 pb-[env(safe-area-inset-bottom)] pt-1 md:hidden"
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
                prefetch={n.noPrefetch ? false : undefined}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-[56px] flex-1 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl text-[11px] font-medium leading-tight transition-colors duration-150 active:scale-95 ${
                  active ? PRIMARY_GRADIENT : "text-slate-400"
                }`}
              >
                {n.icon}
                {n.label}
              </Link>
            );
          })}
        </nav>

        {/* Pengingat akun Google Drive putus/error: popup tiap 5 menit
            untuk super_admin, kecuali di halaman Penyimpanan. */}
        <GoogleDriveReminder />
      </div>
    </div>
  );
}
