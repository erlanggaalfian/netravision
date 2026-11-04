"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import {
  Badge,
  Button,
  Card,
  ConfirmModal,
  EmptyState,
  ErrorBox,
  Field,
  Modal,
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

interface GDriveConn {
  connected: boolean;
  email: string;
  rclone_found: boolean;
  error?: string;
}

/* Halaman admin: Tautan Folder Google Drive (mode folder-link + rclone).
   Bisa menampung BANYAK tautan — tiap folder punya mount rclone sendiri.
   Kamera memilih folder tujuan di modal kamera (mode Drive/Keduanya).
   Tombol "Hubungkan Google Drive": tempel token dari `rclone authorize`,
   tanpa SSH, tanpa Cloud Console — upload otomatis via rclone copyto. */

export default function AdminStoragePage() {
  const [data, setData] = useState<GDriveList | null>(null);
  const [conn, setConn] = useState<GDriveConn | null>(null);
  const [folderUrl, setFolderUrl] = useState("");
  const [folderName, setFolderName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<GDriveFolder | null>(null);
  // Modal hubungkan: tempel token dari `rclone authorize "drive"`
  const [showConnect, setShowConnect] = useState(false);
  const [token, setToken] = useState("");
  const [connectBusy, setConnectBusy] = useState(false);
  const [connectError, setConnectError] = useState("");

  function openConnect() {
    setConnectError("");
    setToken("");
    setShowConnect(true);
  }

  async function load() {
    try {
      setData(await api.get<GDriveList>("/admin/storage/google-drive"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat daftar folder");
    }
  }

  async function loadConn() {
    try {
      setConn(await api.get<GDriveConn>("/admin/storage/google-drive/connection"));
    } catch {
      setConn(null);
    }
  }

  useEffect(() => {
    load();
    loadConn();
  }, []);

  async function connect() {
    if (!token.trim()) {
      setConnectError("Tempel dulu token dari `rclone authorize`.");
      return;
    }
    setConnectError("");
    setConnectBusy(true);
    try {
      await api.post("/admin/storage/google-drive/connect", { token: token.trim() });
      setToken("");
      setShowConnect(false);
      await loadConn();
    } catch (e) {
      setConnectError(e instanceof ApiError ? e.message : "Gagal menghubungkan");
    } finally {
      setConnectBusy(false);
    }
  }

  async function disconnect() {
    setError("");
    try {
      await api.del("/admin/storage/google-drive/connection");
      await loadConn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memutuskan");
    }
  }

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

      {/* Koneksi Google Drive */}
      <Card className="mb-6 max-w-2xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-white">Koneksi Google Drive</p>
            <p className="mt-1 text-sm text-slate-400">
              {conn?.connected ? (
                <>
                  Terhubung{conn.email && conn.email !== "terhubung" ? ` sebagai ${conn.email}` : ""} — rekaman ter-upload otomatis.
                </>
              ) : (
                "Belum terhubung. Hubungkan sekali, lalu rekaman ter-upload otomatis tanpa SSH."
              )}
            </p>
            {conn && !conn.rclone_found && (
              <p className="mt-1 text-sm text-warn-400">
                rclone belum terinstal di server — hubungi admin server.
              </p>
            )}
          </div>
          {conn?.connected ? (
            <div className="flex items-center gap-2">
              <Badge tone="ok">Terhubung</Badge>
              <Button variant="danger" onClick={disconnect} className="px-3">
                Putuskan
              </Button>
            </div>
          ) : (
            <Button onClick={openConnect} className="min-h-[44px]">
              Hubungkan Google Drive
            </Button>
          )}
        </div>
      </Card>

      {/* Daftar tautan */}
      <div className="mb-6 space-y-3">
        {data && data.folders.length === 0 && (
          <EmptyState text="Belum ada tautan. Tambahkan tautan folder Google Drive di bawah." />
        )}
        {data?.folders.map((f, i) => (
          <Card key={f.id} className="transition-colors hover:border-ink-500">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 font-medium">
                  <span className="truncate">
                    {f.folder_name || `Folder ${i + 1}`}
                  </span>
                  {i === 0 && <Badge tone="info">Default</Badge>}
                </p>
                <p className="mt-1 break-all font-mono text-xs text-slate-400">
                  ID: {f.folder_id}
                </p>
                <p className="mt-0.5 break-all text-xs text-slate-400">
                  Mount: {f.local_path || "—"}
                  {!f.local_path_custom && data.staging_default && (
                    <span> (default)</span>
                  )}
                </p>
                {f.updated_at && (
                  <p className="mt-1 text-xs text-slate-400">
                    Diperbarui {new Date(f.updated_at).toLocaleString("id-ID")}
                    {f.updated_by ? ` oleh ${f.updated_by}` : ""}
                  </p>
                )}
              </div>
              <Button
                variant="danger"
                onClick={() => setDeleting(f)}
                className="px-3"
              >
                Hapus
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {/* Tambah tautan */}
      <Card className="max-w-2xl">
        <p className="mb-4 text-sm font-semibold text-white">Tambah Tautan</p>
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
        <p className="mb-2 text-sm font-semibold text-white">Cara kerja</p>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-400">
          <li>Klik “Hubungkan Google Drive” di atas dan ikuti 3 langkahnya (sekali saja).</li>
          <li>Tempel tautan foldernya di atas (bisa banyak).</li>
          <li>
            Di modal kamera, pilih mode penyimpanan “Google Drive”/“Keduanya”
            lalu pilih folder tujuannya.
          </li>
          <li>Segmen rekaman yang sudah stabil ter-upload otomatis tiap menit.</li>
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

      {/* Modal Hubungkan Google Drive */}
      {showConnect && (
        <Modal title="Hubungkan Google Drive" onClose={() => setShowConnect(false)}>
          <p className="text-sm text-slate-400">
            Sekali saja — tanpa SSH, tanpa Cloud Console.
          </p>
          <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-slate-400">
            <li>
              Di <b>komputer/laptop Anda</b>, pasang rclone sekali dari{" "}
              <a href="https://rclone.org/downloads/" target="_blank" rel="noreferrer" className="text-accent-400 underline">
                rclone.org/downloads
              </a>
              .
            </li>
            <li>
              Jalankan perintah ini, lalu izinkan di browser:
              <code className="mt-1 block rounded bg-slate-100 px-2 py-1 font-mono text-xs">
                rclone authorize &quot;drive&quot;
              </code>
            </li>
            <li>
              Salin <b>seluruh token JSON</b> yang muncul, tempel di bawah, lalu Simpan.
            </li>
          </ol>
          <div className="mt-4">
            <Field label="Token rclone" hint='Mulai dengan {"access_token": ...'>
              <textarea
                rows={4}
                className="w-full rounded-xl border border-white/10 bg-ink-950 px-3.5 py-2.5 font-mono text-xs text-slate-100 placeholder:text-slate-400 outline-none transition-colors focus:border-accent-400"
                placeholder='{"access_token":"ya29...","token_type":"Bearer","refresh_token":"1//...","expiry":"..."}'
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </Field>
          </div>
          {connectError && (
            <div className="mt-3">
              <ErrorBox message={connectError} />
            </div>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowConnect(false)}>
              Batal
            </Button>
            <Button onClick={connect} disabled={connectBusy} className="min-h-[44px]">
              {connectBusy ? "Menghubungkan…" : "Simpan & Hubungkan"}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
