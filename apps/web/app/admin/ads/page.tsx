"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api, apiFetch } from "../../../lib/api";
import {
  Button,
  Card,
  ErrorBox,
  Field,
  SectionTitle,
  Select,
  Spinner,
  TextInput,
} from "../../../components/ui";

interface AdConfig {
  enabled: boolean;
  title: string | null;
  image_url: string | null;
  link_url: string | null;
  position: string | null;
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
      .get<AdConfig>("/admin/ad-config")
      .then(setCfg)
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat konfigurasi"),
      );
  }, []);

  async function save() {
    if (!cfg) return;
    setError("");
    setBusy(true);
    setSaved(false);
    try {
      const res = await api.post<AdConfig>("/admin/ad-config", cfg);
      setCfg(res);
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
      setCfg((c) => (c ? { ...c, image_url: data.image_url } : c));
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
        title="Iklan / Banner"
        desc="Banner pengumuman yang tampil di aplikasi"
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {cfg && (
        <Card className="max-w-2xl">
          <div className="space-y-4">
            <label className="flex min-h-[44px] items-center gap-3 text-sm text-slate-200">
              <input
                type="checkbox"
                checked={cfg.enabled}
                onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
                className="h-5 w-5 accent-blue-500"
              />
              Tampilkan banner
            </label>
            <Field label="Judul">
              <TextInput
                placeholder="cth: Promo pemasangan CCTV"
                value={cfg.title ?? ""}
                onChange={(e) => setCfg({ ...cfg, title: e.target.value || null })}
              />
            </Field>
            <Field label="Gambar">
              <div className="flex flex-wrap items-center gap-3">
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
                >
                  {uploading ? "Mengunggah…" : "Unggah gambar"}
                </Button>
                {cfg.image_url && (
                  <span className="max-w-full truncate text-xs text-slate-500">
                    {cfg.image_url}
                  </span>
                )}
              </div>
              {cfg.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={cfg.image_url}
                  alt="Pratinjau banner"
                  className="mt-3 max-h-40 rounded-lg border border-ink-700 object-contain"
                />
              )}
            </Field>
            <Field label="Tautan (opsional)" hint="Dibuka saat banner diklik">
              <TextInput
                placeholder="https://…"
                value={cfg.link_url ?? ""}
                onChange={(e) =>
                  setCfg({ ...cfg, link_url: e.target.value || null })
                }
              />
            </Field>
            <Field label="Posisi">
              <Select
                value={cfg.position ?? ""}
                onChange={(e) =>
                  setCfg({ ...cfg, position: e.target.value || null })
                }
              >
                <option value="">— Pilih —</option>
                <option value="top">Atas</option>
                <option value="bottom">Bawah</option>
                <option value="sidebar">Sidebar</option>
              </Select>
            </Field>
            <div className="flex items-center gap-3">
              <Button onClick={save} disabled={busy}>
                {busy ? "Menyimpan…" : "Simpan"}
              </Button>
              {saved && (
                <span className="text-sm text-ok-400">Tersimpan ✓</span>
              )}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
