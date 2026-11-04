"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { ErrorBox, Modal, Spinner } from "../../../components/ui";
import {
  NBBadge,
  NBButton,
  NBCard,
  NBConfirmModal,
  NBEmptyState,
  NBField,
  NBInput,
  NBTitle,
} from "../_nb";

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
      <NBTitle
        title="Tautan Folder Google Drive"
        desc="Tempel tautan folder yang sudah di-share dari Google Drive. Link 1 untuk akun A, link 2 untuk akun B, dst. Tiap kamera bisa memilih disimpan ke folder/akun mana."
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {/* Koneksi Google Drive */}
      <NBCard className="mb-6 max-w-2xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-lg font-bold tracking-tight text-white">Koneksi Google Drive</p>
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
              <NBBadge tone="ok">Terhubung</NBBadge>
              <NBButton variant="danger" onClick={disconnect} className="px-3">
                Putuskan
              </NBButton>
            </div>
          ) : (
            <NBButton onClick={openConnect} className="min-h-[44px]">
              Hubungkan Google Drive
            </NBButton>
          )}
        </div>
      </NBCard>

      {/* Daftar tautan */}
      <div className="mb-6 space-y-3">
        {data && data.folders.length === 0 && (
          <NBEmptyState text="Belum ada tautan. Tambahkan tautan folder Google Drive di bawah." />
        )}
        {data?.folders.map((f, i) => (
          <NBCard key={f.id} className="transition-colors hover:border-ink-500">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 font-medium">
                  <span className="truncate">
                    {f.folder_name || `Akun ${i + 1}`}
                  </span>
                  {i === 0 && <NBBadge tone="info">Default</NBBadge>}
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
              <NBButton
                variant="danger"
                onClick={() => setDeleting(f)}
                className="px-3"
              >
                Hapus
              </NBButton>
            </div>
          </NBCard>
        ))}
      </div>

      {/* Tambah tautan */}
      <NBCard className="max-w-2xl">
        <p className="mb-4 text-lg font-bold tracking-tight text-white">Tambah Tautan</p>
        <div className="space-y-4">
          <NBField
            label="Tautan Folder Google Drive"
            hint="Salin tautan folder dari Google Drive (tombol Bagikan → Salin link). ID folder dibaca otomatis dari tautan."
          >
            <NBInput
              placeholder="https://drive.google.com/drive/folders/..."
              value={folderUrl}
              onChange={(e) => setFolderUrl(e.target.value)}
            />
          </NBField>
          <NBField label="Nama / Label Akun (opsional)">
            <NBInput
              placeholder="mis. Akun A - CCTV-Gudang"
              value={folderName}
              onChange={(e) => setFolderName(e.target.value)}
            />
          </NBField>
          <NBField
            label="Path Lokal (mount rclone, opsional)"
            hint={
              data?.staging_default
                ? `Kosongkan untuk memakai default: ${data.staging_default}`
                : "Lokasi mount rclone untuk folder ini, mis. /mnt/gdrive-gudang"
            }
          >
            <NBInput
              placeholder="/mnt/gdrive-..."
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
            />
          </NBField>
          <div>
            <NBButton onClick={add} disabled={busy}>
              {busy ? "Menambah…" : "+ Tambah Tautan"}
            </NBButton>
          </div>
        </div>
      </NBCard>

      <NBCard className="mt-6 max-w-2xl">
        <p className="mb-2 text-lg font-bold tracking-tight text-white">Cara kerja</p>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-400">
          <li>Klik “Hubungkan Google Drive” di atas dan ikuti 3 langkahnya (sekali saja).</li>
          <li>Tempel tautan foldernya di atas (bisa banyak).</li>
          <li>
            Di modal kamera, pilih mode penyimpanan “Google Drive”/“Keduanya”
            lalu pilih folder tujuannya.
          </li>
          <li>Segmen rekaman yang sudah stabil ter-upload otomatis tiap menit.</li>
        </ol>
      </NBCard>

      {deleting && (
        <NBConfirmModal
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
            <NBField label="Token rclone" hint='Mulai dengan {"access_token": ...'>
              <textarea
                rows={4}
                className="w-full rounded-lg border border-ink-700 bg-ink-950 px-3.5 py-2.5 font-mono text-xs text-slate-100 placeholder:text-slate-400 outline-none transition-all focus:border-accent-500 focus:ring-4 focus:ring-accent-500/15"
                placeholder='{"access_token":"ya29...","token_type":"Bearer","refresh_token":"1//...","expiry":"..."}'
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </NBField>
          </div>
          {connectError && (
            <div className="mt-3">
              <ErrorBox message={connectError} />
            </div>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <NBButton variant="secondary" onClick={() => setShowConnect(false)}>
              Batal
            </NBButton>
            <NBButton onClick={connect} disabled={connectBusy} className="min-h-[44px]">
              {connectBusy ? "Menghubungkan…" : "Simpan & Hubungkan"}
            </NBButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
