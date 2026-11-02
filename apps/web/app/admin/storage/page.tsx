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
  // Modal hubungkan: 2 langkah (start -> buka URL -> finish dengan kode)
  const [showConnect, setShowConnect] = useState(false);
  const [connStep, setConnStep] = useState<"start" | "code">("start");
  const [sessionId, setSessionId] = useState("");
  const [authUrl, setAuthUrl] = useState("");
  const [code, setCode] = useState("");
  const [connectBusy, setConnectBusy] = useState(false);
  const [connectError, setConnectError] = useState("");

  function openConnect() {
    setConnectError("");
    setCode("");
    setConnStep("start");
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

  async function connectStart() {
    setConnectError("");
    setConnectBusy(true);
    try {
      const r = await api.post<{ session_id: string; auth_url: string }>(
        "/admin/storage/google-drive/connect/start",
        {},
      );
      setSessionId(r.session_id);
      setAuthUrl(r.auth_url);
      setConnStep("code");
    } catch (e) {
      setConnectError(e instanceof ApiError ? e.message : "Gagal memulai");
    } finally {
      setConnectBusy(false);
    }
  }

  async function connectFinish() {
    if (!code.trim()) {
      setConnectError("Tempel dulu kode verifikasi dari Google.");
      return;
    }
    setConnectError("");
    setConnectBusy(true);
    try {
      await api.post("/admin/storage/google-drive/connect/finish", {
        session_id: sessionId,
        code: code.trim(),
      });
      setCode("");
      setSessionId("");
      setAuthUrl("");
      setConnStep("start");
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
            <p className="font-medium">Koneksi Google Drive</p>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {conn?.connected ? (
                <>
                  Terhubung{conn.email && conn.email !== "terhubung" ? ` sebagai ${conn.email}` : ""} — rekaman ter-upload otomatis.
                </>
              ) : (
                "Belum terhubung. Hubungkan sekali, lalu rekaman ter-upload otomatis tanpa SSH."
              )}
            </p>
            {conn && !conn.rclone_found && (
              <p className="mt-1 text-sm text-amber-600 dark:text-amber-400">
                rclone belum terinstal di server — hubungi admin server.
              </p>
            )}
          </div>
          {conn?.connected ? (
            <div className="flex items-center gap-2">
              <Badge tone="ok">Terhubung</Badge>
              <Button variant="danger" onClick={disconnect} className="min-h-[40px] px-3">
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
          <li>Klik “Hubungkan Google Drive” di atas — buka link Google di browser Anda, tempel kodenya (sekali saja).</li>
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

      {/* Modal Hubungkan Google Drive — 2 langkah */}
      {showConnect && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900">
            <p className="text-lg font-semibold">Hubungkan Google Drive</p>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Sekali saja — tanpa instal apa pun, tanpa SSH.
            </p>

            {connStep === "start" ? (
              <>
                <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-slate-600 dark:text-slate-300">
                  <li>Klik tombol di bawah — server menyiapkan koneksi.</li>
                  <li>Buka link Google yang muncul di <b>browser HP/laptop Anda</b>, login dan izinkan.</li>
                  <li>Salin <b>kode verifikasi</b> dari Google, tempel di sini.</li>
                </ol>
                {connectError && (
                  <div className="mt-3">
                    <ErrorBox message={connectError} />
                  </div>
                )}
                <div className="mt-4 flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => setShowConnect(false)}>
                    Batal
                  </Button>
                  <Button onClick={connectStart} disabled={connectBusy} className="min-h-[44px]">
                    {connectBusy ? "Menyiapkan…" : "Mulai Hubungkan"}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-slate-600 dark:text-slate-300">
                  <li>
                    Buka link ini di browser Anda dan izinkan akses:
                    <a
                      href={authUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 block break-all rounded bg-slate-100 px-2 py-1 font-mono text-xs text-blue-600 underline dark:bg-slate-800 dark:text-blue-400"
                    >
                      {authUrl.slice(0, 60)}…
                    </a>
                  </li>
                  <li>Salin kode verifikasi yang diberikan Google, tempel di bawah.</li>
                </ol>
                <Field label="Kode verifikasi Google">
                  <TextInput
                    placeholder="4/0AbC..."
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                  />
                </Field>
                {connectError && (
                  <div className="mt-3">
                    <ErrorBox message={connectError} />
                  </div>
                )}
                <div className="mt-4 flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => setShowConnect(false)}>
                    Batal
                  </Button>
                  <Button onClick={connectFinish} disabled={connectBusy} className="min-h-[44px]">
                    {connectBusy ? "Menghubungkan…" : "Selesaikan"}
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
