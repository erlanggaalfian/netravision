"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import {
  Badge,
  Button,
  Card,
  ConfirmModal,
  ErrorBox,
  Field,
  SectionTitle,
  Spinner,
  TextInput,
} from "../../../components/ui";

interface GDriveFolder {
  id: number;
  folder_url: string;
  folder_id: string;
  folder_name: string;
  local_path: string;
  local_path_custom: boolean;
  updated_at: string | null;
  updated_by: string;
}

interface GDriveList {
  folders: GDriveFolder[];
  staging_default: string;
  quota_tb: number;
}

/* Halaman admin: Tautan Folder Google Drive (mode folder-link + rclone).
   Bisa menampung BANYAK tautan — tiap folder punya mount rclone sendiri.
   Kamera memilih folder tujuan di modal kamera (mode Drive/Keduanya). */

export default function AdminStoragePage() {
  const [data, setData] = useState<GDriveList | null>(null);
  const [folderUrl, setFolderUrl] = useState("");
  const [folderName, setFolderName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<GDriveFolder | null>(null);

  async function load() {
    try {
      setData(await api.get<GDriveList>("/admin/storage/google-drive"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat daftar folder");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function add() {
    if (!folderUrl.trim()) {
      setError("Tempel dulu tautan folder Google Drive.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await api.post("/admin/storage/google-drive", {
        folder_url: folderUrl.trim(),
        folder_name: folderName.trim(),
        local_path: localPath.trim(),
      });
      setFolderUrl("");
      setFolderName("");
      setLocalPath("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menambah tautan");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!deleting) return;
    setError("");
    try {
      await api.del(`/admin/storage/google-drive/${deleting.id}`);
      setDeleting(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus");
    }
  }

  if (data === null && !error) return <Spinner />;

  return (
    <div>
      <SectionTitle
        title="Tautan Folder Google Drive"
        desc="Daftar folder tujuan untuk rekaman mode Google Drive dan mode Keduanya. Tambah beberapa tautan bila perlu — tiap kamera bisa memilih disimpan ke folder mana."
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {/* Daftar tautan */}
      <div className="mb-6 space-y-3">
        {data && data.folders.length === 0 && (
          <Card>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Belum ada tautan. Tambahkan tautan folder Google Drive di bawah.
            </p>
          </Card>
        )}
        {data?.folders.map((f, i) => (
          <Card key={f.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 font-medium">
                  <span className="truncate">
                    {f.folder_name || `Folder ${i + 1}`}
                  </span>
                  {i === 0 && <Badge tone="info">Default</Badge>}
                </p>
                <p className="mt-1 break-all font-mono text-xs text-slate-500 dark:text-slate-400">
                  ID: {f.folder_id}
                </p>
                <p className="mt-0.5 break-all text-xs text-slate-500 dark:text-slate-400">
                  Mount: {f.local_path || "—"}
                  {!f.local_path_custom && data.staging_default && (
                    <span> (default)</span>
                  )}
                </p>
                {f.updated_at && (
                  <p className="mt-1 text-xs text-slate-500">
                    Diperbarui {new Date(f.updated_at).toLocaleString("id-ID")}
                    {f.updated_by ? ` oleh ${f.updated_by}` : ""}
                  </p>
                )}
              </div>
              <Button
                variant="danger"
                onClick={() => setDeleting(f)}
                className="min-h-[40px] px-3"
              >
                Hapus
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {/* Tambah tautan */}
      <Card className="max-w-2xl">
        <p className="mb-4 font-medium">Tambah Tautan</p>
        <div className="space-y-4">
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
              placeholder="mis. CCTV-Gudang"
              value={folderName}
              onChange={(e) => setFolderName(e.target.value)}
            />
          </Field>
          <Field
            label="Path Lokal (mount rclone, opsional)"
            hint={
              data?.staging_default
                ? `Kosongkan untuk memakai default: ${data.staging_default}`
                : "Lokasi mount rclone untuk folder ini, mis. /mnt/gdrive-gudang"
            }
          >
            <TextInput
              placeholder="/mnt/gdrive-..."
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
            />
          </Field>
          <div>
            <Button onClick={add} disabled={busy}>
              {busy ? "Menambah…" : "+ Tambah Tautan"}
            </Button>
          </div>
        </div>
      </Card>

      <Card className="mt-6 max-w-2xl">
        <p className="mb-2 font-medium">Cara kerja</p>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-400">
          <li>Mount tiap folder dengan rclone ke path lokal masing-masing.</li>
          <li>Tempel tautan foldernya di atas (bisa banyak).</li>
          <li>
            Di modal kamera, pilih mode penyimpanan “Google Drive”/“Keduanya”
            lalu pilih folder tujuannya.
          </li>
          <li>Segmen rekaman yang sudah stabil disalin otomatis tiap 30 detik.</li>
        </ol>
      </Card>

      {deleting && (
        <ConfirmModal
          title="Hapus tautan"
          message={`Hapus "${deleting.folder_name || deleting.folder_id}"? Kamera yang memakai folder ini kembali ke default.`}
          onCancel={() => setDeleting(null)}
          onConfirm={remove}
        />
      )}
    </div>
  );
}
