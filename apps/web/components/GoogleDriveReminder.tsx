"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Modal, PRIMARY_GRADIENT } from "./ui";

/* Pengingat akun Google Drive (perintah user 2026-11-20): bila remote
   gdrive tidak terhubung atau error, tampilkan popup pengingat tiap
   5 menit sampai akun terhubung lagi. Hanya untuk super_admin (endpoint
   status-nya super_admin only), dan tidak tampil saat user sudah berada
   di halaman Penyimpanan, karena di sana status akun sudah terlihat
   langsung. Popup bisa ditutup; pemeriksaan berikutnya tetap jalan dan
   popup muncul lagi bila akun masih putus. Gagal cek (mis. API mati)
   tidak menampilkan popup, karena status Google tidak bisa dipastikan. */

const INITIAL_DELAY_MS = 10_000;
const CHECK_INTERVAL_MS = 5 * 60_000;

interface ConnectionStatus {
  connected: boolean;
  email?: string;
  rclone_found?: boolean;
  error?: string;
}

export function GoogleDriveReminder() {
  const { user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [show, setShow] = useState(false);
  const [errorDetail, setErrorDetail] = useState("");

  const isSuperAdmin = user?.role === "super_admin";
  const onStoragePage = pathname?.startsWith("/admin/storage");

  useEffect(() => {
    if (!isSuperAdmin) return;
    let cancelled = false;

    const check = async () => {
      try {
        const res = await apiFetch("/admin/storage/google-drive/connection");
        if (!res.ok) return;
        const st = (await res.json()) as ConnectionStatus;
        if (cancelled) return;
        if (!st.connected) {
          setErrorDetail(st.error ?? "");
          setShow(true);
        } else {
          setShow(false);
        }
      } catch {
        /* Gagal cek: jangan tampilkan popup. */
      }
    };

    const initialTimer = setTimeout(check, INITIAL_DELAY_MS);
    const interval = setInterval(check, CHECK_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(initialTimer);
      clearInterval(interval);
    };
  }, [isSuperAdmin]);

  if (!show || onStoragePage) return null;

  const goToStorage = () => {
    setShow(false);
    router.push("/admin/storage");
  };

  return (
    <Modal
      title="Akun Google Drive tidak terhubung"
      onClose={() => setShow(false)}
    >
      <p className="text-sm leading-relaxed text-slate-300">
        Rekaman tidak bisa diunggah ke Google Drive selama akun tidak
        terhubung. Hubungkan kembali akun Google di halaman Penyimpanan.
      </p>
      {errorDetail && (
        <p className="mt-3 rounded-lg bg-ink-800 px-3 py-2 text-xs leading-relaxed text-slate-400">
          {errorDetail}
        </p>
      )}
      <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-end">
        <button
          type="button"
          onClick={() => setShow(false)}
          className="min-h-[44px] cursor-pointer rounded-xl bg-ink-800 px-4 text-sm font-semibold text-slate-300 transition hover:bg-ink-700 active:scale-95"
        >
          Tutup
        </button>
        <button
          type="button"
          onClick={goToStorage}
          className={`min-h-[44px] cursor-pointer rounded-xl px-4 text-sm font-semibold text-white transition active:scale-95 ${PRIMARY_GRADIENT}`}
        >
          Buka Penyimpanan
        </button>
      </div>
      <p className="mt-3 text-center text-xs text-slate-500">
        Pengingat ini muncul lagi tiap 5 menit selama akun belum terhubung.
      </p>
    </Modal>
  );
}
