"use client";

import { useEffect, useRef, useState } from "react";
import type { AdConfig } from "../../../lib/types";
import { ApiError, api, apiFetch } from "../../../lib/api";
import {
  Button,
  Card,
  ErrorBox,
  Field,
  SectionTitle,
  Select,
  Spinner,
  TextArea,
  TextInput,
} from "../../../components/ui";

const DEFAULTS: AdConfig = {
  image_url: "",
  marquee_text: "",
  bg_color: "#1e293b",
  text_color: "#ffffff",
  scroll_speed: 5,
  font_size: 10,
  font_family: "monospace",
  image_opacity: 1.0,
  bg_opacity: 1.0,
  text_opacity: 1.0,
  is_active: true,
  box_width: 100,
  text_align: "left",
  image_height: 20,
  embed_timeout_seconds: 300,
  click_to_play: true,
};

function hexToRgba(hex: string, alpha: number): string {
  let c = hex.replace("#", "");
  if (c.length === 3) c = c[0] + c[0] + c[1] + c[1] + c[2] + c[2];
  const r = parseInt(c.slice(0, 2), 16) || 0;
  const g = parseInt(c.slice(2, 4), 16) || 0;
  const b = parseInt(c.slice(4, 6), 16) || 0;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/* ---- Pratinjau langsung (mock monitor 16:9, selalu gelap) ---- */
function AdPreview({ cfg }: { cfg: AdConfig }) {
  const [now, setNow] = useState("");
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const f = (v: number) => String(v).padStart(2, "0");
      setNow(
        `${d.getFullYear()}-${f(d.getMonth() + 1)}-${f(d.getDate())} ` +
          `${f(d.getHours())}:${f(d.getMinutes())}:${f(d.getSeconds())}`,
      );
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);

  // Paritas v2.0: durasi = max(10, (11 - speed) * 18) detik.
  const duration = Math.max(10, (11 - cfg.scroll_speed) * 18);
  const text = (cfg.marquee_text || "Teks Iklan Anda") + "\u00A0\u00A0|\u00A0\u00A0";

  const bannerStyle: React.CSSProperties = {
    backgroundColor: hexToRgba(cfg.bg_color, cfg.bg_opacity),
    opacity: cfg.is_active ? 1 : 0.3,
    justifyContent:
      cfg.text_align === "center"
        ? "center"
        : cfg.text_align === "right"
          ? "flex-end"
          : "flex-start",
  };
  if (cfg.box_width >= 100) {
    bannerStyle.left = 10;
    bannerStyle.right = 10;
  } else {
    bannerStyle.width = `${cfg.box_width}%`;
    if (cfg.text_align === "left") bannerStyle.left = 10;
    else if (cfg.text_align === "right") bannerStyle.right = 10;
    else {
      bannerStyle.left = "50%";
      bannerStyle.transform = "translateX(-50%)";
    }
  }

  return (
    <div className="mb-6 rounded-2xl border border-ink-700/60 bg-ink-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Live Preview (Pratinjau Langsung)
        </span>
        <span className="rounded-md border border-accent-500/30 bg-accent-500/10 px-2.5 py-0.5 font-mono text-[10px] text-accent-300">
          Widescreen Monitor (16:9)
        </span>
      </div>
      <div className="nv-stage relative aspect-video w-full overflow-hidden rounded-xl border border-white/10">
        <style>{`@keyframes nv-marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }`}</style>
        {/* Label kamera kiri-atas */}
        <div className="absolute left-3 top-3 flex select-none items-center gap-1.5 rounded-md border border-white/10 bg-black/70 px-2.5 py-1 font-mono text-[10px] text-white">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
          <span className="font-bold tracking-wide">LOBBY UTAMA - LIVE</span>
        </div>
        {/* Indikator REC kanan-atas */}
        <div className="absolute right-3 top-3 flex select-none items-center gap-1.5 rounded-md border border-white/10 bg-black/70 px-2.5 py-1 font-mono text-[10px] font-bold tracking-widest text-rose-500">
          <span className="h-1.5 w-1.5 animate-ping rounded-full bg-rose-500" />
          <span>● REC</span>
        </div>
        {/* Jam mock kanan-bawah */}
        <div className="absolute bottom-3 right-3 select-none rounded-md border border-white/10 bg-black/70 px-2 py-0.5 font-mono text-[10px] text-slate-300">
          {now}
        </div>
        {/* Banner overlay lower-third */}
        <div
          className="absolute bottom-0 flex items-center gap-2 overflow-hidden border-t border-white/10 px-2.5 py-1.5"
          style={bannerStyle}
        >
          {cfg.image_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={cfg.image_url}
              alt="Logo sponsor"
              className="w-auto shrink-0 rounded object-contain"
              style={{
                height: cfg.image_height,
                opacity: cfg.image_opacity,
              }}
            />
          )}
          <div className="relative flex min-w-0 flex-1 items-center overflow-hidden">
            <div
              className="flex whitespace-nowrap"
              style={{ animation: `nv-marquee ${duration}s linear infinite` }}
            >
              {[0, 1].map((i) => (
                <span
                  key={i}
                  style={{
                    color: cfg.text_color,
                    opacity: cfg.text_opacity,
                    fontSize: cfg.font_size,
                    fontFamily: cfg.font_family,
                  }}
                >
                  {text}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
        checked ? "bg-emerald-500" : "bg-ink-600"
      }`}
    >
      <span
        className={`absolute left-[2px] top-[2px] h-5 w-5 rounded-full bg-white transition-transform ${
          checked ? "translate-x-5" : "translate-x-0"
        }`}
      />
    </button>
  );
}

function RangeRow({
  label,
  min,
  max,
  value,
  display,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  value: number;
  display: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-1.5 flex-1 cursor-pointer appearance-none rounded-lg bg-ink-600 accent-sky-500"
        />
        <span className="w-12 text-right font-mono text-xs font-bold text-accent-400">
          {display}
        </span>
      </div>
    </div>
  );
}

function ColorRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <div className="flex gap-2">
        <input
          type="color"
          value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : "#1e293b"}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-9 shrink-0 cursor-pointer rounded-lg border border-ink-600 bg-transparent"
          aria-label={label}
        />
        <TextInput
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#1E293B"
          className="font-mono uppercase"
        />
      </div>
    </div>
  );
}

export default function AdminAdsPage() {
  const [cfg, setCfg] = useState<AdConfig | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [saved, setSaved] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .get<AdConfig>("/ad-config")
      .then((r) => setCfg({ ...DEFAULTS, ...r }))
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat konfigurasi"),
      );
  }, []);

  function set<K extends keyof AdConfig>(key: K, value: AdConfig[K]) {
    setCfg((c) => (c ? { ...c, [key]: value } : c));
  }

  async function save() {
    if (!cfg) return;
    setError("");
    setBusy(true);
    setSaved(false);
    try {
      const res = await api.post<AdConfig>("/admin/ad-config", cfg);
      setCfg({ ...DEFAULTS, ...res });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setError("");
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("image", file);
      const res = await apiFetch("/admin/ad-config/upload-image", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const d = await res.json();
          msg = d.detail || msg;
        } catch {
          /* abaikan */
        }
        throw new ApiError(res.status, msg);
      }
      const data = (await res.json()) as { image_url: string };
      set("image_url", data.image_url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal mengunggah gambar");
    } finally {
      setUploading(false);
    }
  }

  if (cfg === null && !error) return <Spinner />;

  return (
    <div>
      <SectionTitle
        title="Ad Space Config"
        desc="Atur gambar dan teks berjalan pada popup guest"
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {cfg && (
        <Card>
          <AdPreview cfg={cfg} />

          {/* Toggle status */}
          <div className="mb-6 flex items-center justify-between rounded-xl border border-ink-700/60 bg-ink-900/60 p-4">
            <div>
              <span className="block font-mono text-xs font-semibold uppercase tracking-wider text-white">
                Status Penayangan Iklan
              </span>
              <span className="font-mono text-[10px] text-slate-400">
                Tampilkan space iklan ini di video stream guest
              </span>
            </div>
            <Toggle
              checked={cfg.is_active}
              onChange={(v) => set("is_active", v)}
              label="Status Penayangan Iklan"
            />
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {/* Seksi 1: Tata Letak & Latar */}
            <div className="space-y-4 rounded-xl border border-ink-700/60 bg-ink-900/40 p-4">
              <div className="border-b border-ink-700/60 pb-2">
                <span className="font-mono text-xs font-semibold uppercase text-accent-400">
                  1. Tata Letak &amp; Latar
                </span>
              </div>
              <RangeRow
                label="Lebar Wadah Iklan (10% - 100%)"
                min={10}
                max={100}
                value={cfg.box_width}
                display={`${cfg.box_width}%`}
                onChange={(v) => set("box_width", v)}
              />
              <Field label="Posisi Aliran Konten">
                <Select
                  value={cfg.text_align}
                  onChange={(e) => set("text_align", e.target.value)}
                >
                  <option value="left">Rata Kiri</option>
                  <option value="center">Rata Tengah</option>
                  <option value="right">Rata Kanan</option>
                </Select>
              </Field>
              <ColorRow
                label="Warna Latar Belakang"
                value={cfg.bg_color}
                onChange={(v) => set("bg_color", v)}
              />
              <RangeRow
                label="Transparansi Latar (0% - 100%)"
                min={0}
                max={100}
                value={Math.round(cfg.bg_opacity * 100)}
                display={`${Math.round(cfg.bg_opacity * 100)}%`}
                onChange={(v) => set("bg_opacity", v / 100)}
              />
            </div>

            {/* Seksi 2: Logo Sponsor & Media */}
            <div className="space-y-4 rounded-xl border border-ink-700/60 bg-ink-900/40 p-4">
              <div className="border-b border-ink-700/60 pb-2">
                <span className="font-mono text-xs font-semibold uppercase text-accent-400">
                  2. Logo Sponsor &amp; Media
                </span>
              </div>
              <div>
                <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Gambar Sponsor (Kiri Iklan)
                </span>
                <div className="flex h-16 w-full items-center justify-center overflow-hidden rounded-xl border border-ink-700/60 bg-black/40">
                  {cfg.image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={cfg.image_url}
                      alt="Pratinjau logo"
                      className="max-h-14 object-contain"
                    />
                  ) : (
                    <span className="font-mono text-[10px] text-slate-500">
                      Tidak ada gambar
                    </span>
                  )}
                </div>
                <div className="mt-3 flex gap-2">
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) upload(f);
                      e.target.value = "";
                    }}
                  />
                  <Button
                    variant="subtle"
                    onClick={() => fileRef.current?.click()}
                    disabled={uploading}
                    className="flex-1"
                  >
                    {uploading ? "Mengunggah…" : "Pilih Berkas"}
                  </Button>
                </div>
                <div className="mt-2">
                  <TextInput
                    value={cfg.image_url}
                    onChange={(e) => set("image_url", e.target.value)}
                    placeholder="Atau tempel URL gambar..."
                    aria-label="Tempel URL gambar"
                    className="text-xs"
                  />
                </div>
              </div>
              <RangeRow
                label="Transparansi Logo (0% - 100%)"
                min={0}
                max={100}
                value={Math.round(cfg.image_opacity * 100)}
                display={`${Math.round(cfg.image_opacity * 100)}%`}
                onChange={(v) => set("image_opacity", v / 100)}
              />
              <RangeRow
                label="Tinggi Ukuran Logo (10px - 60px)"
                min={10}
                max={60}
                value={cfg.image_height}
                display={`${cfg.image_height}px`}
                onChange={(v) => set("image_height", v)}
              />
            </div>

            {/* Seksi 3: Teks Bergulir & Font */}
            <div className="space-y-4 rounded-xl border border-ink-700/60 bg-ink-900/40 p-4">
              <div className="border-b border-ink-700/60 pb-2">
                <span className="font-mono text-xs font-semibold uppercase text-accent-400">
                  3. Teks Bergulir (Marquee)
                </span>
              </div>
              <Field label="Isi Teks Marquee">
                <TextArea
                  rows={2}
                  value={cfg.marquee_text}
                  onChange={(e) => set("marquee_text", e.target.value)}
                  placeholder="Ketik kalimat informasi iklan..."
                />
              </Field>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <ColorRow
                  label="Warna Teks"
                  value={cfg.text_color}
                  onChange={(v) => set("text_color", v)}
                />
                <Field label="Jenis Font">
                  <Select
                    value={cfg.font_family}
                    onChange={(e) => set("font_family", e.target.value)}
                  >
                    <option value="monospace">Monospace</option>
                    <option value="sans-serif">Sans-Serif</option>
                    <option value="serif">Serif</option>
                    <option value="cursive">Cursive</option>
                    <option value="Arial, sans-serif">Arial</option>
                    <option value="'Courier New', monospace">Courier</option>
                  </Select>
                </Field>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <RangeRow
                  label="Ukuran Font"
                  min={8}
                  max={24}
                  value={cfg.font_size}
                  display={`${cfg.font_size}px`}
                  onChange={(v) => set("font_size", v)}
                />
                <RangeRow
                  label="Kecepatan"
                  min={1}
                  max={10}
                  value={cfg.scroll_speed}
                  display={`${cfg.scroll_speed}`}
                  onChange={(v) => set("scroll_speed", v)}
                />
              </div>
              <RangeRow
                label="Transparansi Teks (0% - 100%)"
                min={0}
                max={100}
                value={Math.round(cfg.text_opacity * 100)}
                display={`${Math.round(cfg.text_opacity * 100)}%`}
                onChange={(v) => set("text_opacity", v / 100)}
              />
            </div>
          </div>

          <div className="mt-6">
            <Button onClick={save} disabled={busy} className="w-full">
              {busy ? "Menyimpan…" : "Simpan Konfigurasi Iklan"}
            </Button>
            {saved && (
              <p className="mt-3 flex items-center justify-center gap-1.5 text-sm text-ok-400">
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2.5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M20 6L9 17l-5-5" />
                </svg>
                Tersimpan
              </p>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
