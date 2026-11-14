/* Kolom "Lokasi" multi-format bersama (perintah user 2026-11-14):
   satu input yang menerima koordinat desimal, tautan Google Maps
   (lengkap/pendek), Plus Code, DMS, atau alamat, lalu mengubahnya
   jadi latitude/longitude lewat POST /api/maps/resolve-location.
   Dipakai di Scanner (Tambah terpilih), Tambah/Ubah Kamera, dan
   Set Koordinat. Kolom angka lat/lng lama tetap ada sebagai edit
   lanjutan; komponen ini hanya mengisi keduanya. */

"use client";

import { useState } from "react";
import { ApiError, api } from "../lib/api";

type ResolveOut = {
  latitude: number;
  longitude: number;
  format: string;
  place_name: string | null;
};

export function LocationInput({
  lat,
  lng,
  onChange,
  disabled,
}: {
  lat: string;
  lng: string;
  onChange: (lat: string, lng: string) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [okMsg, setOkMsg] = useState("");
  const [errMsg, setErrMsg] = useState("");

  async function resolve(value: string) {
    const t = value.trim();
    if (!t) {
      setErrMsg("");
      setOkMsg("");
      return;
    }
    setBusy(true);
    setErrMsg("");
    setOkMsg("");
    try {
      const got = await api.post<ResolveOut>("/maps/resolve-location", {
        text: t,
      });
      const la = String(got.latitude.toFixed(6));
      const lo = String(got.longitude.toFixed(6));
      onChange(la, lo);
      setOkMsg(
        `Ditemukan: ${la}, ${lo} (${got.format})` +
          (got.place_name ? ` · ${got.place_name}` : ""),
      );
    } catch (e) {
      setErrMsg(
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : "Lokasi tidak bisa diurai.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold text-slate-200">
        Lokasi
      </span>
      <span className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void resolve(text);
            }
          }}
          onPaste={(e) => {
            const pasted = e.clipboardData.getData("text");
            setTimeout(() => void resolve(pasted), 0);
          }}
          placeholder="Tempel koordinat, tautan Google Maps, Plus Code, DMS, atau alamat"
          disabled={disabled || busy}
          className="w-full rounded-xl bg-ink-800 px-3.5 py-2.5 text-[15px] text-slate-100 placeholder:text-slate-400 shadow-sm outline-none transition-all duration-150 ease-out focus:ring-2 focus:ring-accent-500/30"
        />
        <button
          type="button"
          onClick={() => void resolve(text)}
          disabled={disabled || busy || text.trim() === ""}
          className="shrink-0 rounded-xl bg-accent-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Mencari…" : "Cari"}
        </button>
      </span>
      <span className="mt-1.5 block text-xs text-slate-400">
        Format: koordinat desimal (-7.873522, 111.257658), tautan Google Maps,
        Plus Code, DMS, atau alamat. Enter atau tempel langsung mengurai.
      </span>
      {okMsg && (
        <span className="mt-1.5 block text-xs leading-relaxed text-ok-300">
          {okMsg}
        </span>
      )}
      {errMsg && (
        <span className="mt-1.5 block text-xs leading-relaxed text-red-400">
          {errMsg}
        </span>
      )}
      {lat.trim() !== "" && lng.trim() !== "" && !okMsg && (
        <span className="mt-1.5 block font-mono text-xs text-slate-400">
          Koordinat saat ini: {lat}, {lng}
        </span>
      )}
    </label>
  );
}
