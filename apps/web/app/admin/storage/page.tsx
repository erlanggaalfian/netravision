"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { ErrorBox, Modal, Spinner } from "../../../components/ui";
import {
  NBAccordion,
  NBBadge,
  NBButton,
  NBCard,
  NBConfirmModal,
  NBEmptyState,
  NBField,
  NBInput,
  NBTextArea,
  NBTitle,
} from "../_nb";

interface GDriveFolder {
  id: number;
  folder_url: string;
  folder_id: string;
  folder_name: string;
  local_path: string;
  local_path_custom: boolean;
  retention_days: number | null;
  updated_at: string | null;
  updated_by: string;
}

interface RcloneRemote {
  id: number | null;
  remote_name: string;
  label: string | null;
  connected: boolean;
  error?: string;
  total_bytes?: number;
  used_bytes?: number;
  free_bytes?: number;
  in_conf?: boolean;
  in_db?: boolean;
}

interface UploadQueue {
  pending: number;
  last_success_at: string | null;
  remotes: { remote_name: string; connected: boolean }[];
}

function fmtBytes(n: number | undefined | null): string {
  if (n == null) return "-";
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
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
   Bisa menampung BANYAK tautan, tiap folder punya mount rclone sendiri.
   Kamera memilih folder tujuan di modal kamera (mode Drive/Keduanya).
   Tombol "Hubungkan Google Drive": tempel token dari `rclone authorize`,
   tanpa SSH, tanpa Cloud Console, upload otomatis via rclone copyto. */

export default function AdminStoragePage() {
  const [data, setData] = useState<GDriveList | null>(null);
  const [conn, setConn] = useState<GDriveConn | null>(null);
  const [folderUrl, setFolderUrl] = useState("");
  const [folderName, setFolderName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<GDriveFolder | null>(null);
  /* E-S9: Putuskan koneksi butuh konfirmasi dulu. */
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  // Modal hubungkan: tempel token dari `rclone authorize "drive"`
  const [showConnect, setShowConnect] = useState(false);
  const [token, setToken] = useState("");
  const [connectBusy, setConnectBusy] = useState(false);
  const [connectError, setConnectError] = useState("");
  // Akun rclone multi-remote + antrean upload
  const [remotes, setRemotes] = useState<RcloneRemote[]>([]);
  const [queue, setQueue] = useState<UploadQueue | null>(null);
  const [remoteToken, setRemoteToken] = useState("");
  const [remoteName, setRemoteName] = useState("");
  const [remoteLabel, setRemoteLabel] = useState("");
  const [remoteBusy, setRemoteBusy] = useState(false);
  const [remoteError, setRemoteError] = useState("");
  const [deletingRemote, setDeletingRemote] = useState<RcloneRemote | null>(null);
  const [retention, setRetention] = useState<Record<number, string>>({});
  const [retentionBusy, setRetentionBusy] = useState<number | null>(null);

  function openConnect() {
    setConnectError("");
    setToken("");
    setShowConnect(true);
  }

  async function load() {
    try {
      const res = await api.get<GDriveList>("/admin/storage/google-drive");
      setData(res);
      setRetention(
        Object.fromEntries(
          res.folders.map((f) => [
            f.id,
            f.retention_days != null ? String(f.retention_days) : "",
          ]),
        ),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat daftar folder");
    }
  }

  async function loadRemotes() {
    try {
      setRemotes(await api.get<RcloneRemote[]>("/admin/drive-remotes"));
    } catch {
      setRemotes([]);
    }
  }

  async function loadQueue() {
    try {
      setQueue(await api.get<UploadQueue>("/admin/drive/upload-queue"));
    } catch {
      setQueue(null);
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
    loadRemotes();
    loadQueue();
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
    setConfirmDisconnect(false);
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

  async function addRemote() {
    if (!remoteToken.trim() || !remoteName.trim()) {
      setRemoteError("Isi nama remote dan tempel token dari `rclone authorize`.");
      return;
    }
    setRemoteError("");
    setRemoteBusy(true);
    try {
      await api.post("/admin/drive-remotes", {
        token: remoteToken.trim(),
        remote_name: remoteName.trim(),
        label: remoteLabel.trim() || undefined,
      });
      setRemoteToken("");
      setRemoteName("");
      setRemoteLabel("");
      await loadRemotes();
      await loadQueue();
    } catch (e) {
      setRemoteError(e instanceof ApiError ? e.message : "Gagal menambah akun");
    } finally {
      setRemoteBusy(false);
    }
  }

  async function removeRemote() {
    if (!deletingRemote) return;
    setError("");
    try {
      await api.del(`/admin/drive-remotes/${deletingRemote.remote_name}`);
      setDeletingRemote(null);
      await loadRemotes();
      await loadQueue();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus akun");
    }
  }

  async function saveRetention(f: GDriveFolder) {
    const raw = (retention[f.id] ?? "").trim();
    const days = raw === "" ? null : Number(raw);
    if (days !== null && (!Number.isInteger(days) || days < 1)) {
      setError("Retention harus angka bulat minimal 1 hari, atau kosong.");
      return;
    }
    setError("");
    setRetentionBusy(f.id);
    try {
      await api.put(`/admin/storage/google-drive/${f.id}`, {
        folder_url: f.folder_url,
        folder_name: f.folder_name,
        local_path: f.local_path,
        retention_days: days,
      });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan retention");
    } finally {
      setRetentionBusy(null);
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
      <NBCard className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-lg font-bold tracking-tight text-white">Koneksi Google Drive</p>
            <p className="mt-1 text-sm text-slate-400">
              {conn?.connected ? (
                <>
                  Terhubung{conn.email && conn.email !== "terhubung" ? ` sebagai ${conn.email}` : ""}, rekaman ter-upload otomatis.
                </>
              ) : (
                "Belum terhubung. Hubungkan sekali, lalu rekaman ter-upload otomatis tanpa SSH."
              )}
            </p>
            {conn && !conn.rclone_found && (
              <p className="mt-1 text-sm text-warn-400">
                rclone belum terinstal di server, hubungi admin server.
              </p>
            )}
          </div>
          {conn?.connected ? (
            <div className="flex items-center gap-2">
              <NBBadge tone="ok">Terhubung</NBBadge>
              <NBButton variant="danger" onClick={() => setConfirmDisconnect(true)} className="px-3">
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

      {/* Antrean upload segmen ke Drive */}
      <NBCard className="mb-6">
        <p className="text-lg font-bold tracking-tight text-white">Antrean Upload</p>
        {queue === null ? (
          <p className="mt-1 text-sm text-slate-400">Status antrean belum bisa dimuat.</p>
        ) : (
          <>
            <p className="mt-1 text-sm text-slate-400">
              {queue.pending} segmen menunggu upload. Terakhir berhasil upload:{" "}
              {queue.last_success_at
                ? new Date(queue.last_success_at).toLocaleString("id-ID")
                : "belum pernah"}
              .
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {queue.remotes.length === 0 && (
                <span className="text-sm text-slate-400">Belum ada remote rclone.</span>
              )}
              {queue.remotes.map((r) => (
                <NBBadge key={r.remote_name} tone={r.connected ? "ok" : "warn"}>
                  {r.remote_name}: {r.connected ? "terhubung" : "putus"}
                </NBBadge>
              ))}
            </div>
          </>
        )}
      </NBCard>

      {/* Akun Rclone multi-remote */}
      <NBCard className="mb-6">
        <p className="text-lg font-bold tracking-tight text-white">Akun Rclone</p>
        <p className="mt-1 text-sm text-slate-400">
          Satu remote rclone per akun Google Drive. Tempel token dari `rclone
          authorize &quot;drive&quot;` untuk menambah akun.
        </p>
        {remotes.length === 0 ? (
          <div className="mt-4">
            <NBEmptyState text="Belum ada akun rclone. Tambahkan di bawah." />
          </div>
        ) : (
          <div className="mt-4 space-y-2">
            {remotes.map((r) => (
              <div
                key={r.remote_name}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-ink-800 px-3.5 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-100">
                    {r.remote_name}
                    {r.label ? (
                      <span className="font-normal text-slate-400"> ({r.label})</span>
                    ) : (
                      ""
                    )}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-400">
                    {r.connected
                      ? "Terhubung"
                      : `Putus${r.error ? `: ${r.error}` : ""}`}
                    {r.total_bytes != null && r.used_bytes != null
                      ? `, terpakai ${fmtBytes(r.used_bytes)} dari ${fmtBytes(r.total_bytes)}`
                      : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <NBBadge tone={r.connected ? "ok" : "warn"}>
                    {r.connected ? "Terhubung" : "Putus"}
                  </NBBadge>
                  <NBButton
                    variant="danger"
                    onClick={() => setDeletingRemote(r)}
                    className="px-3"
                  >
                    Hapus
                  </NBButton>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-5 space-y-4 border-t border-slate-200/10 pt-4">
          <p className="text-sm font-semibold text-slate-200">Tambah Akun</p>
          <NBField
            label="Nama Remote"
            hint="Huruf, angka, '-' dan '_' saja, mis. gdrive-2."
          >
            <NBInput
              placeholder="gdrive-2"
              value={remoteName}
              onChange={(e) => setRemoteName(e.target.value)}
            />
          </NBField>
          <NBField label="Label (opsional)">
            <NBInput
              placeholder="mis. akun2@mail.com"
              value={remoteLabel}
              onChange={(e) => setRemoteLabel(e.target.value)}
            />
          </NBField>
          <NBField label="Token rclone" hint='Mulai dengan {"access_token": ...'>
            <NBTextArea
              rows={3}
              placeholder='{"access_token":"ya29...","token_type":"Bearer","refresh_token":"1//...","expiry":"..."}'
              value={remoteToken}
              onChange={(e) => setRemoteToken(e.target.value)}
            />
          </NBField>
          {remoteError && (
            <div>
              <ErrorBox message={remoteError} />
            </div>
          )}
          <div>
            <NBButton onClick={addRemote} disabled={remoteBusy}>
              {remoteBusy ? "Menambah…" : "+ Tambah Akun"}
            </NBButton>
          </div>
        </div>
      </NBCard>

      {/* Daftar tautan: list ringkas ala menu Admin, detail di accordion */}
      <div className="mb-6">
        <h2 className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-[0.08em] text-slate-400">
          Daftar Tautan{data ? ` (${data.folders.length})` : ""}
        </h2>
        {data && data.folders.length === 0 && (
          <NBEmptyState text="Belum ada tautan. Tambahkan tautan folder Google Drive di bawah." />
        )}
        {data && data.folders.length > 0 && (
          <div className="nv-panel-modern divide-y divide-slate-200/10 overflow-hidden !p-0">
            {data.folders.map((f, i) => (
              <NBAccordion
                key={f.id}
                summary={
                  <span className="flex min-h-[48px] items-center gap-3">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden className="shrink-0 text-slate-400">
                      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                    </svg>
                    <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-slate-200">
                      {f.folder_name || `Akun ${i + 1}`}
                    </span>
                    {i === 0 && <NBBadge size="sm" tone="info">Default</NBBadge>}
                  </span>
                }
              >
                <div className="space-y-1.5 px-4 pb-4 text-xs text-slate-400">
                  <p className="break-all font-mono">ID: {f.folder_id}</p>
                  <p className="break-all">
                    Mount: {f.local_path || "-"}
                    {!f.local_path_custom && data.staging_default && (
                      <span> (default)</span>
                    )}
                  </p>
                  {f.updated_at && (
                    <p>
                      Diperbarui {new Date(f.updated_at).toLocaleString("id-ID")}
                      {f.updated_by ? ` oleh ${f.updated_by}` : ""}
                    </p>
                  )}
                  <div className="pt-2">
                    <NBField
                      label="Retention (hari)"
                      hint="Kosongkan bila tidak ada hapus otomatis. File .mp4 di folder Drive ini yang lebih tua dari nilai ini dihapus otomatis."
                    >
                      <div className="flex items-center gap-2">
                        <div className="w-28">
                          <NBInput
                            type="number"
                            min={1}
                            placeholder="mis. 30"
                            value={retention[f.id] ?? ""}
                            onChange={(e) =>
                              setRetention((prev) => ({
                                ...prev,
                                [f.id]: e.target.value,
                              }))
                            }
                          />
                        </div>
                        <NBButton
                          variant="secondary"
                          onClick={() => saveRetention(f)}
                          disabled={retentionBusy === f.id}
                          className="px-3"
                        >
                          {retentionBusy === f.id ? "Menyimpan…" : "Simpan"}
                        </NBButton>
                      </div>
                    </NBField>
                  </div>
                  <div className="pt-2">
                    <NBButton
                      variant="danger"
                      onClick={() => setDeleting(f)}
                      className="px-3"
                    >
                      Hapus
                    </NBButton>
                  </div>
                </div>
              </NBAccordion>
            ))}
          </div>
        )}
      </div>

      {/* Tambah tautan */}
      <NBCard>
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

      <NBCard className="mt-6">
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

      {deletingRemote && (
        <NBConfirmModal
          title="Hapus akun rclone"
          message={`Hapus remote "${deletingRemote.remote_name}"? Token di server ikut dihapus dan upload ke akun ini berhenti.`}
          onCancel={() => setDeletingRemote(null)}
          onConfirm={removeRemote}
        />
      )}

      {confirmDisconnect && (
        <NBConfirmModal
          title="Putuskan Google Drive"
          message="Putuskan koneksi Google Drive? Upload rekaman otomatis akan berhenti sampai dihubungkan lagi."
          onCancel={() => setConfirmDisconnect(false)}
          onConfirm={disconnect}
        />
      )}

      {/* Modal Hubungkan Google Drive */}
      {showConnect && (
        <Modal title="Hubungkan Google Drive" onClose={() => setShowConnect(false)}>
          <p className="text-sm text-slate-400">
            Sekali saja, tanpa SSH, tanpa Cloud Console.
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
                className="w-full rounded-lg bg-ink-800 px-3.5 py-2.5 font-mono text-xs text-slate-100 shadow-sm placeholder:text-slate-400 outline-none transition-all focus:ring-2 focus:ring-accent-500/30"
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
