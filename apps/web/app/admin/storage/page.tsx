"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { ErrorBox, Spinner } from "../../../components/ui";
import {
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

function fmtBytes(n: number | undefined | null): string {
  if (n == null) return "-";
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

function usagePct(r: RcloneRemote): number | null {
  if (r.total_bytes == null || r.used_bytes == null || r.total_bytes <= 0) {
    return null;
  }
  return Math.min(100, Math.round((r.used_bytes / r.total_bytes) * 100));
}

const RETENTION_CHOICES: { label: string; days: number | null }[] = [
  { label: "7 hari", days: 7 },
  { label: "30 hari", days: 30 },
  { label: "90 hari", days: 90 },
  { label: "Selamanya", days: null },
];

function retentionLabel(days: number | null | undefined): string {
  if (days == null) return "Selamanya";
  return `${days} hari`;
}

/* Halaman admin: Penyimpanan Google Drive, dibuat sesimpel mungkin.
   Bahasa awam: "Akun Google" (bukan "remote rclone"), "Folder" (bukan
   "tautan"), "Simpan rekaman selama" (bukan "retention"). Detail teknis
   (ID folder, path mount, nama remote) disembunyikan di balik "Detail".
   Nama remote dibuat otomatis (gdrive, gdrive-2, ...), pengguna hanya
   mengisi nama akun yang mudah dibaca dan menempel kode. */

export default function AdminStoragePage() {
  const [data, setData] = useState<GDriveList | null>(null);
  const [conn, setConn] = useState<GDriveConn | null>(null);
  const [remotes, setRemotes] = useState<RcloneRemote[]>([]);
  const [queue, setQueue] = useState<UploadQueue | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Tambah folder
  const [folderUrl, setFolderUrl] = useState("");
  const [folderName, setFolderName] = useState("");
  const [newRetention, setNewRetention] = useState<number | null>(30);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [localPath, setLocalPath] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [deleting, setDeleting] = useState<GDriveFolder | null>(null);
  const [openDetail, setOpenDetail] = useState<Record<number, boolean>>({});
  const [retentionBusy, setRetentionBusy] = useState<number | null>(null);

  // Tambah akun
  const [showAddAccount, setShowAddAccount] = useState(false);
  const [accountLabel, setAccountLabel] = useState("");
  const [accountToken, setAccountToken] = useState("");
  const [showHowTo, setShowHowTo] = useState(false);
  const [showManual, setShowManual] = useState(false);
  const [accountBusy, setAccountBusy] = useState(false);
  const [accountError, setAccountError] = useState("");
  const [deletingRemote, setDeletingRemote] = useState<RcloneRemote | null>(null);

  // Hubungkan akun via `rclone authorize` di server
  interface AuthorizeJob {
    job_id: string;
    remote_name: string;
    label: string;
    status: "waiting" | "done" | "error" | "cancelled";
    auth_url: string | null;
    token: string | null;
    error: string | null;
  }
  const [authJob, setAuthJob] = useState<AuthorizeJob | null>(null);
  const [authBusy, setAuthBusy] = useState(false);
  const authLabelRef = useRef("");

  async function cancelAuthorize() {
    if (authJob) {
      try {
        await api.del(`/admin/drive-remotes/authorize/${authJob.job_id}`);
      } catch {
        // Abaikan, job mungkin sudah selesai sendiri.
      }
    }
    setAuthJob(null);
  }

  async function startAuthorize() {
    if (!accountLabel.trim()) {
      setAccountError("Isi dulu nama akun, mis. disk1.");
      return;
    }
    setAccountError("");
    setAuthBusy(true);
    try {
      const res = await api.post<{
        job_id: string;
        remote_name: string;
        label: string;
      }>("/admin/drive-remotes/authorize", { label: accountLabel.trim() });
      authLabelRef.current = res.label;
      setAuthJob({
        ...res,
        status: "waiting",
        auth_url: null,
        token: null,
        error: null,
      });
    } catch (e) {
      setAccountError(e instanceof ApiError ? e.message : "Gagal memulai hubungkan akun");
    } finally {
      setAuthBusy(false);
    }
  }

  // Poll status authorize; bila done, simpan token lewat endpoint yang ada.
  useEffect(() => {
    if (!authJob || authJob.status !== "waiting") return;
    const jobId = authJob.job_id;
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await api.get<AuthorizeJob>(
          `/admin/drive-remotes/authorize/${jobId}`,
        );
        if (cancelled) return;
        setAuthJob(res);
        if (res.status === "done" && res.token) {
          try {
            await api.post("/admin/drive-remotes", {
              token: res.token,
              remote_name: res.remote_name,
              label: authLabelRef.current,
            });
            setNotice(`Akun "${authLabelRef.current}" berhasil terhubung.`);
            setAccountLabel("");
            setAccountToken("");
            setAuthJob(null);
            setShowAddAccount(false);
            await loadRemotes();
            await loadQueue();
          } catch (e) {
            setAccountError(
              e instanceof ApiError ? e.message : "Gagal menyimpan akun",
            );
            setAuthJob((prev) =>
              prev ? { ...prev, status: "error", error: "Gagal menyimpan akun" } : prev,
            );
          }
        }
      } catch {
        // Abaikan satu poll gagal, coba lagi.
      }
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authJob?.job_id, authJob?.status]);

  async function load() {
    try {
      const res = await api.get<GDriveList>("/admin/storage/google-drive");
      setData(res);
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

  function refreshAll() {
    load();
    loadRemotes();
    loadQueue();
    loadConn();
  }

  async function loadActiveAuthorize() {
    // Pulihkan job authorize yang masih menunggu (mis. setelah refresh),
    // supaya link + tombol Batalkan tetap tampil dan job tidak menggantung.
    try {
      const res = await api.get<{
        job_id: string | null;
        remote_name?: string;
        label?: string;
        status?: string;
        auth_url?: string | null;
      }>("/admin/drive-remotes/authorize/active");
      if (res.job_id) {
        authLabelRef.current = res.label ?? "";
        setAccountLabel(res.label ?? "");
        setShowAddAccount(true);
        setAuthJob({
          job_id: res.job_id,
          remote_name: res.remote_name ?? "",
          label: res.label ?? "",
          status: "waiting",
          auth_url: res.auth_url ?? null,
          token: null,
          error: null,
        });
      }
    } catch {
      // Abaikan, tidak ada job aktif.
    }
  }

  useEffect(() => {
    refreshAll();
    loadActiveAuthorize();
  }, []);

  function nextRemoteName(): string {
    const taken = new Set(remotes.map((r) => r.remote_name));
    if (!taken.has("gdrive")) return "gdrive";
    let i = 2;
    while (taken.has(`gdrive-${i}`)) i += 1;
    return `gdrive-${i}`;
  }

  async function addAccount() {
    if (!accountLabel.trim()) {
      setAccountError("Isi dulu nama akun, mis. disk1.");
      return;
    }
    if (!accountToken.trim()) {
      setAccountError("Tempel dulu kode dari rclone.");
      return;
    }
    setAccountError("");
    setAccountBusy(true);
    try {
      await api.post("/admin/drive-remotes", {
        token: accountToken.trim(),
        remote_name: nextRemoteName(),
        label: accountLabel.trim(),
      });
      setAccountLabel("");
      setAccountToken("");
      setShowAddAccount(false);
      setNotice("Akun Google berhasil ditambahkan.");
      await loadRemotes();
      await loadQueue();
    } catch (e) {
      setAccountError(e instanceof ApiError ? e.message : "Gagal menambah akun");
    } finally {
      setAccountBusy(false);
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

  async function addFolder() {
    if (!folderUrl.trim()) {
      setError("Tempel dulu tautan folder Google Drive.");
      return;
    }
    setError("");
    setNotice("");
    setAddBusy(true);
    try {
      await api.post("/admin/storage/google-drive", {
        folder_url: folderUrl.trim(),
        folder_name: folderName.trim(),
        local_path: localPath.trim(),
        retention_days: newRetention,
      });
      setFolderUrl("");
      setFolderName("");
      setLocalPath("");
      setNewRetention(30);
      setShowAdvanced(false);
      setNotice("Folder berhasil ditambahkan.");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menambah folder");
    } finally {
      setAddBusy(false);
    }
  }

  async function removeFolder() {
    if (!deleting) return;
    setError("");
    try {
      await api.del(`/admin/storage/google-drive/${deleting.id}`);
      setDeleting(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus folder");
    }
  }

  async function saveRetention(f: GDriveFolder, days: number | null) {
    if (f.retention_days === days) return;
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
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan lama simpan");
    } finally {
      setRetentionBusy(null);
    }
  }

  if (data === null && !error) return <Spinner />;

  const connectedCount = remotes.filter((r) => r.connected).length;
  const folderCount = data?.folders.length ?? 0;

  return (
    <div>
      <NBTitle
        title="Penyimpanan Google Drive"
        desc="Simpan rekaman CCTV ke Google Drive secara otomatis. Hubungkan akun Google, lalu tempel tautan folder."
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-xl bg-ok-400/15 px-4 py-3 text-sm font-medium text-ok-400 ring-1 ring-ok-400/30">
          {notice}
        </div>
      )}
      {conn && !conn.rclone_found && (
        <div className="mb-4 rounded-xl bg-warn-400/15 px-4 py-3 text-sm font-medium text-warn-400 ring-1 ring-warn-400/30">
          rclone belum terinstal di server, hubungi admin server.
        </div>
      )}

      {/* Ringkasan status, satu baris */}
      <NBCard className="mb-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <span className="flex items-center gap-2">
            <span
              className={`h-2.5 w-2.5 rounded-full ${connectedCount > 0 ? "bg-ok-400" : "bg-bad-400"}`}
            />
            <span className="font-semibold text-slate-100">
              {connectedCount > 0
                ? `${connectedCount} akun Google terhubung`
                : "Belum ada akun Google terhubung"}
            </span>
          </span>
          <span className="text-slate-400">
            {folderCount} folder
          </span>
          <span className="text-slate-400">
            {queue === null
              ? "Status upload belum bisa dimuat."
              : queue.pending > 0
                ? `${queue.pending} rekaman menunggu upload`
                : "Tidak ada rekaman menunggu upload"}
          </span>
          <span className="ml-auto">
            <NBButton variant="secondary" onClick={refreshAll} className="px-3">
              Muat ulang
            </NBButton>
          </span>
        </div>
      </NBCard>

      {/* Akun Google */}
      <div className="mb-6">
        <h2 className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-[0.08em] text-slate-400">
          Akun Google
        </h2>
        {remotes.length === 0 ? (
          <NBEmptyState text="Belum ada akun Google. Tambahkan akun di bawah supaya rekaman bisa di-upload." />
        ) : (
          <div className="space-y-3">
            {remotes.map((r) => {
              const pct = usagePct(r);
              return (
                <NBCard key={r.remote_name} className="!p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`h-2.5 w-2.5 shrink-0 rounded-full ${r.connected ? "bg-ok-400" : "bg-bad-400"}`}
                        />
                        <p className="truncate text-[15px] font-bold text-slate-100">
                          {r.label || r.remote_name}
                        </p>
                        <NBBadge tone={r.connected ? "ok" : "bad"}>
                          {r.connected ? "Terhubung" : "Putus"}
                        </NBBadge>
                      </div>
                      <p className="mt-1 text-sm text-slate-400">
                        {r.connected
                          ? pct !== null && r.total_bytes != null
                            ? `Terpakai ${fmtBytes(r.used_bytes)} dari ${fmtBytes(r.total_bytes)}`
                            : "Terhubung"
                          : r.error
                            ? `Putus: ${r.error}`
                            : "Putus, periksa akun ini."}
                      </p>
                      {pct !== null && (
                        <div className="mt-2 h-2 w-full max-w-xs overflow-hidden rounded-full bg-ink-800">
                          <div
                            className={`h-full rounded-full ${pct >= 90 ? "bg-bad-400" : pct >= 75 ? "bg-warn-400" : "bg-ok-400"}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      )}
                    </div>
                    <NBButton
                      variant="danger"
                      onClick={() => setDeletingRemote(r)}
                      className="px-3"
                    >
                      Hapus
                    </NBButton>
                  </div>
                </NBCard>
              );
            })}
          </div>
        )}

        {!showAddAccount ? (
          <div className="mt-3">
            <NBButton onClick={() => setShowAddAccount(true)}>
              + Tambah Akun Google
            </NBButton>
          </div>
        ) : (
          <NBCard className="mt-3">
            <p className="text-lg font-bold tracking-tight text-white">Tambah Akun Google</p>
            <p className="mt-1 text-sm text-slate-400">
              Satu akun untuk satu Google Drive. Nanti bisa tambah akun lagi.
            </p>
            <div className="mt-4 space-y-4">
              <NBField label="Nama akun" hint="Nama yang mudah dikenali, mis. disk1.">
                <NBInput
                  placeholder="disk1"
                  value={accountLabel}
                  onChange={(e) => setAccountLabel(e.target.value)}
                />
              </NBField>

              {authJob === null ? (
                <div>
                  <NBButton onClick={startAuthorize} disabled={authBusy}>
                    {authBusy ? "Menyiapkan…" : "Hubungkan dengan Google"}
                  </NBButton>
                  <p className="mt-2 text-xs text-slate-400">
                    Server menjalankan rclone authorize, Anda tinggal klik link
                    yang muncul lalu login Google.
                  </p>
                </div>
              ) : authJob.status === "waiting" ? (
                <div className="rounded-xl bg-ink-800 p-4">
                  <p className="text-sm font-semibold text-slate-200">
                    {authJob.auth_url
                      ? "Klik link di bawah, lalu login Google:"
                      : "Menyiapkan link login Google…"}
                  </p>
                  {authJob.auth_url && (
                    <a
                      href={authJob.auth_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 block break-all rounded-lg bg-ink-900 px-3 py-2 font-mono text-xs text-accent-400 underline underline-offset-2"
                    >
                      {authJob.auth_url}
                    </a>
                  )}
                  <p className="mt-2 text-xs text-slate-400">
                    Link mengarah ke port 53682 di server. Bila browser tidak
                    bisa membukanya, teruskan port itu lewat SSH ke server ini
                    (127.0.0.1 di perintah itu adalah localhost di server,
                    tempat rclone jalan):
                    <code className="mt-1 block rounded bg-ink-900 px-2 py-1 font-mono text-xs">
                      ssh -L 53682:127.0.0.1:53682 root@{typeof window !== "undefined" ? window.location.hostname : "alamat-server"}
                    </code>
                    Perintah di atas butuh akses SSH ke server. Bila server
                    tidak bisa di-SSH (mis. demo ini), pakai cara tempel kode
                    manual di bawah. Setelah Anda izinkan di Google, akun
                    terhubung otomatis di sini.
                  </p>
                  <div className="mt-3">
                    <NBButton variant="secondary" onClick={cancelAuthorize}>
                      Batalkan
                    </NBButton>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl bg-bad-400/15 p-4 text-sm font-medium text-bad-400 ring-1 ring-bad-400/30">
                  {authJob.error || "Gagal menghubungkan akun."}
                  <div className="mt-3">
                    <NBButton variant="secondary" onClick={() => setAuthJob(null)}>
                      Coba lagi
                    </NBButton>
                  </div>
                </div>
              )}

              <div>
                <button
                  type="button"
                  onClick={() => setShowManual((v) => !v)}
                  className="text-sm font-medium text-slate-400 underline underline-offset-2"
                >
                  {showManual ? "Sembunyikan cara manual" : "atau tempel kode manual"}
                </button>
                {showManual && (
                  <div className="mt-3 space-y-4">
                    <NBField
                      label="Kode dari rclone"
                      hint='Tempel seluruh kode yang muncul setelah menjalankan rclone authorize. Kode dimulai dengan {"access_token": ...'
                    >
                      <NBTextArea
                        rows={3}
                        placeholder='{"access_token":"ya29...","token_type":"Bearer","refresh_token":"1//...","expiry":"..."}'
                        value={accountToken}
                        onChange={(e) => setAccountToken(e.target.value)}
                      />
                    </NBField>
                    <div>
                      <button
                        type="button"
                        onClick={() => setShowHowTo((v) => !v)}
                        className="text-sm font-medium text-accent-400 underline underline-offset-2"
                      >
                        {showHowTo ? "Sembunyikan cara mendapatkan kode" : "Cara mendapatkan kode"}
                      </button>
                      {showHowTo && (
                        <ol className="mt-3 list-decimal space-y-2 rounded-xl bg-ink-800 p-4 pl-8 text-sm text-slate-400">
                          <li>
                            Di <b>komputer/laptop Anda</b>, pasang rclone sekali dari{" "}
                            <a
                              href="https://rclone.org/downloads/"
                              target="_blank"
                              rel="noreferrer"
                              className="text-accent-400 underline"
                            >
                              rclone.org/downloads
                            </a>
                            .
                          </li>
                          <li>
                            Jalankan perintah ini, lalu izinkan di browser:
                            <code className="mt-1 block rounded bg-ink-900 px-2 py-1 font-mono text-xs">
                              rclone authorize &quot;drive&quot;
                            </code>
                          </li>
                          <li>
                            Salin <b>seluruh kode</b> yang muncul, tempel di atas, lalu Simpan.
                          </li>
                        </ol>
                      )}
                    </div>
                    <div>
                      <NBButton onClick={addAccount} disabled={accountBusy}>
                        {accountBusy ? "Menyimpan…" : "Simpan Akun"}
                      </NBButton>
                    </div>
                  </div>
                )}
              </div>
              {accountError && (
                <div>
                  <ErrorBox message={accountError} />
                </div>
              )}
              <div className="flex gap-2">
                <NBButton
                  variant="secondary"
                  onClick={() => {
                    cancelAuthorize();
                    setShowAddAccount(false);
                  }}
                >
                  Tutup
                </NBButton>
              </div>
            </div>
          </NBCard>
        )}
      </div>

      {/* Folder Google Drive */}
      <div className="mb-6">
        <h2 className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-[0.08em] text-slate-400">
          Folder Google Drive{data ? ` (${folderCount})` : ""}
        </h2>
        {data && folderCount === 0 ? (
          <NBEmptyState text="Belum ada folder. Tempel tautan folder Google Drive di bawah." />
        ) : (
          <div className="space-y-3">
            {data?.folders.map((f, i) => (
              <NBCard key={f.id} className="!p-4">
                <div className="flex items-start gap-3">
                  <svg
                    width="22"
                    height="22"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.8}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden
                    className="mt-0.5 shrink-0 text-slate-400"
                  >
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                  </svg>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-[15px] font-bold text-slate-100">
                        {f.folder_name || `Folder ${i + 1}`}
                      </p>
                      {i === 0 && (
                        <NBBadge size="sm" tone="info">
                          Default
                        </NBBadge>
                      )}
                    </div>
                    <p className="mt-0.5 text-sm text-slate-400">
                      Simpan rekaman: {retentionLabel(f.retention_days)}
                    </p>
                    <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                      {RETENTION_CHOICES.map((c) => {
                        const active =
                          (c.days === null && f.retention_days == null) ||
                          c.days === f.retention_days;
                        return (
                          <button
                            key={c.label}
                            type="button"
                            disabled={retentionBusy === f.id}
                            onClick={() => saveRetention(f, c.days)}
                            className={`min-h-[36px] rounded-full px-3 text-xs font-semibold transition-all ${
                              active
                                ? "bg-accent-500 text-white shadow-sm"
                                : "bg-ink-800 text-slate-300 hover:bg-ink-700"
                            }`}
                          >
                            {c.label}
                          </button>
                        );
                      })}
                    </div>
                    <div className="mt-2.5 flex flex-wrap items-center gap-3 text-sm">
                      <a
                        href={f.folder_url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-accent-400 underline underline-offset-2"
                      >
                        Buka di Drive
                      </a>
                      <button
                        type="button"
                        onClick={() =>
                          setOpenDetail((prev) => ({ ...prev, [f.id]: !prev[f.id] }))
                        }
                        className="font-medium text-slate-400 underline underline-offset-2"
                      >
                        {openDetail[f.id] ? "Sembunyikan detail" : "Detail"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleting(f)}
                        className="font-medium text-bad-400 underline underline-offset-2"
                      >
                        Hapus
                      </button>
                    </div>
                    {openDetail[f.id] && (
                      <div className="mt-2 space-y-1 rounded-lg bg-ink-800 p-3 text-xs text-slate-400">
                        <p className="break-all font-mono">ID: {f.folder_id}</p>
                        <p className="break-all font-mono">
                          Mount: {f.local_path || "-"}
                          {!f.local_path_custom && data.staging_default && " (default)"}
                        </p>
                        {f.updated_at && (
                          <p>
                            Diperbarui {new Date(f.updated_at).toLocaleString("id-ID")}
                            {f.updated_by ? ` oleh ${f.updated_by}` : ""}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </NBCard>
            ))}
          </div>
        )}

        {/* Tambah folder */}
        <NBCard className="mt-3">
          <p className="text-lg font-bold tracking-tight text-white">Tambah Folder</p>
          <p className="mt-1 text-sm text-slate-400">
            Tempel tautan folder yang sudah dibagikan dari Google Drive. Nama
            folder terisi otomatis bila dikosongkan.
          </p>
          <div className="mt-4 space-y-4">
            <NBField
              label="Tautan folder Google Drive"
              hint="Di Google Drive: klik kanan folder, Bagikan, Salin link, lalu tempel di sini."
            >
              <NBInput
                placeholder="https://drive.google.com/drive/folders/..."
                value={folderUrl}
                onChange={(e) => setFolderUrl(e.target.value)}
              />
            </NBField>
            <NBField label="Nama folder (opsional)" hint="Kosongkan bila ingin nama diambil dari Drive.">
              <NBInput
                placeholder="mis. folder 1"
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
              />
            </NBField>
            <div>
              <p className="mb-1.5 block text-sm font-semibold text-slate-200">
                Simpan rekaman selama
              </p>
              <div className="flex flex-wrap items-center gap-1.5">
                {RETENTION_CHOICES.map((c) => {
                  const active =
                    (c.days === null && newRetention == null) || c.days === newRetention;
                  return (
                    <button
                      key={c.label}
                      type="button"
                      onClick={() => setNewRetention(c.days)}
                      className={`min-h-[36px] rounded-full px-3 text-xs font-semibold transition-all ${
                        active
                          ? "bg-accent-500 text-white shadow-sm"
                          : "bg-ink-800 text-slate-300 hover:bg-ink-700"
                      }`}
                    >
                      {c.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-xs text-slate-400">
                Rekaman yang lebih tua dari pilihan ini dihapus otomatis dari folder ini.
              </p>
            </div>
            <div>
              <button
                type="button"
                onClick={() => setShowAdvanced((v) => !v)}
                className="text-sm font-medium text-slate-400 underline underline-offset-2"
              >
                {showAdvanced ? "Sembunyikan pengaturan lanjutan" : "Pengaturan lanjutan"}
              </button>
              {showAdvanced && (
                <div className="mt-3">
                  <NBField
                    label="Path lokal (mount)"
                    hint={
                      data?.staging_default
                        ? `Kosongkan untuk memakai default: ${data.staging_default}`
                        : "Lokasi mount untuk folder ini, mis. /mnt/gdrive-1"
                    }
                  >
                    <NBInput
                      placeholder="/mnt/gdrive-..."
                      value={localPath}
                      onChange={(e) => setLocalPath(e.target.value)}
                    />
                  </NBField>
                </div>
              )}
            </div>
            <div>
              <NBButton onClick={addFolder} disabled={addBusy}>
                {addBusy ? "Menambah…" : "+ Tambah Folder"}
              </NBButton>
            </div>
          </div>
        </NBCard>
      </div>

      {/* Cara kerja, singkat */}
      <NBCard>
        <p className="mb-2 text-lg font-bold tracking-tight text-white">Cara kerja</p>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-400">
          <li>Tambahkan akun Google di atas (sekali per akun).</li>
          <li>Tempel tautan foldernya (bisa banyak).</li>
          <li>
            Di menu Kamera, pilih penyimpanan “Google Drive” atau “Keduanya”
            lalu pilih folder tujuannya.
          </li>
          <li>Rekaman ter-upload otomatis. Bila Drive sedang mati, rekaman disimpan di server dulu lalu di-upload begitu Drive online lagi.</li>
        </ol>
      </NBCard>

      {deleting && (
        <NBConfirmModal
          title="Hapus folder"
          message={`Hapus "${deleting.folder_name || deleting.folder_id}"? Kamera yang memakai folder ini kembali ke default.`}
          onCancel={() => setDeleting(null)}
          onConfirm={removeFolder}
        />
      )}

      {deletingRemote && (
        <NBConfirmModal
          title="Hapus akun Google"
          message={`Hapus akun "${deletingRemote.label || deletingRemote.remote_name}"? Upload ke akun ini berhenti dan token di server ikut dihapus.`}
          onCancel={() => setDeletingRemote(null)}
          onConfirm={removeRemote}
        />
      )}

      {/* Modal lama "Hubungkan Google Drive" dihapus: tambah akun sekarang
          lewat form "Tambah Akun Google" di atas (nama remote dibuat otomatis). */}
    </div>
  );
}
