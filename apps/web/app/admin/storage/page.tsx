"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import {
  Button,
  Card,
  ErrorBox,
  Field,
  SectionTitle,
  Spinner,
  TextInput,
} from "../../../components/ui";

interface GDriveSetting {
  configured: boolean;
  folder_url: string;
  folder_id: string;
  folder_name: string;
  staging_path: string;
  quota_tb: number;
  updated_at: string | null;
  updated_by: string;
}

/* Halaman admin: Penyimpanan Google Drive (mode folder-link + rclone).
   Implementasi tambahan di samping OAuth multi-akun di tab Drive. */

export default function AdminStoragePage() {
  const [cfg, setCfg] = useState<GDriveSetting | null>(null);
  const [folderUrl, setFolderUrl] = useState("");
  const [folderName, setFolderName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .get<GDriveSetting>("/admin/storage/google-drive")
      .then((c) => {
        setCfg(c);
        setFolderUrl(c.folder_url);
        setFolderName(c.folder_name);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat pengaturan"),
      );
  }, []);

  async function save() {
    setError("");
    setBusy(true);
    setSaved(false);
    try {
      const res = await api.put<GDriveSetting>("/admin/storage/google-drive", {
        folder_url: folderUrl.trim(),
        folder_name: folderName.trim(),
      });
      setCfg(res);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  if (cfg === null && !error) return <Spinner />;

  return (
    <div>
      <SectionTitle
        title="Penyimpanan Google Drive"
        desc="Folder tujuan untuk rekaman mode Google Drive dan mode Keduanya. Untuk mengganti akun/folder, cukup tempel tautan folder Google Drive yang baru — akun tujuan mengikuti pemilik folder tersebut."
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {cfg && (
        <div className="space-y-4">
          <Card className="max-w-2xl">
            <div className="space-y-4">
              <div>
                <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Folder Tujuan Saat Ini
                </p>
                <p className="text-sm">
                  {cfg.configured
                    ? `${cfg.folder_name || "Tanpa label"} (${cfg.folder_id})`
                    : "—"}
                </p>
                {cfg.updated_at && (
                  <p className="mt-1 text-xs text-slate-500">
                    Diperbarui{" "}
                    {new Date(cfg.updated_at).toLocaleString("id-ID")}
                    {cfg.updated_by ? ` oleh ${cfg.updated_by}` : ""}
                  </p>
                )}
              </div>
              <Field
                label="Tautan Folder Google Drive"
                hint="Salin tautan folder dari Google Drive (tombol Bagikan → Salin link). ID folder dibaca otomatis dari tautan."
              >
                <TextInput
                  placeholder="https://drive.google.com/drive/folders/..."
                  value={folderUrl}
                  onChange={(e) => setFolderUrl(e.target.value)}
                />
              </Field>
              <Field label="Nama Folder (label, opsional)">
                <TextInput
                  placeholder="mis. CCTV"
                  value={folderName}
                  onChange={(e) => setFolderName(e.target.value)}
                />
              </Field>
              <div className="flex items-center gap-3">
                <Button onClick={save} disabled={busy}>
                  {busy ? "Menyimpan…" : "Simpan Pengaturan"}
                </Button>
                {saved && (
                  <span className="inline-flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
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
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500">
                Mengganti tautan hanya mengubah tujuan unggahan berikutnya;
                rekaman yang sudah berada di folder lama tidak ikut berpindah.
                Folder penampung lokal (staging):{" "}
                <span className="font-mono">{cfg.staging_path || "-"}</span>
              </p>
            </div>
          </Card>

          <Card className="max-w-2xl">
            <p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Cara Kerja (rclone)
            </p>
            <ol className="list-decimal space-y-2 pl-5 text-sm text-slate-600 dark:text-slate-300">
              <li>
                Install rclone di server, lalu jalankan{" "}
                <code className="font-mono text-xs">rclone config</code> untuk
                membuat remote bernama <code className="font-mono text-xs">gdrive</code>.
              </li>
              <li>
                Mount folder Drive ke folder staging:{" "}
                <code className="font-mono text-xs">
                  rclone mount gdrive: {"<staging_path>"} --daemon
                </code>
                .
              </li>
              <li>
                Set <code className="font-mono text-xs">GDRIVE_RECORD_PATH</code>{" "}
                di environment backend ke folder staging tersebut, lalu restart
                API.
              </li>
              <li>
                Atur <em>storage_mode</em> kamera ke “Keduanya” atau “Google
                Drive” — segmen yang sudah stabil otomatis dicerminkan ke folder
                Drive.
              </li>
            </ol>
            <p className="mt-3 text-xs text-slate-500">
              Mode ini melengkapi tab Drive (OAuth multi-akun) yang tetap
              tersedia — mirror rclone dipakai bila{" "}
              <code className="font-mono">GDRIVE_RECORD_PATH</code> diset.
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
