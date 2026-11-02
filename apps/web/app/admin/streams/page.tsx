"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { useCameraStatus } from "../../../hooks/useCameraStatus";
import type { DriveAccount, ScanCandidate, Stream } from "../../../lib/types";
import {
  Accordion,
  Badge,
  Button,
  Card,
  ConfirmModal,
  ErrorBox,
  Field,
  Modal,
  SectionTitle,
  Select,
  Spinner,
  TextInput,
} from "../../../components/ui";

const BRANDS = [
  { slug: "auto", label: "Otomatis (coba semua)" },
  { slug: "hikvision", label: "Hikvision" },
  { slug: "dahua", label: "Dahua / Amcrest" },
  { slug: "uniview_ipc", label: "Uniview (kamera langsung)" },
  { slug: "uniview_nvr", label: "Uniview (NVR)" },
  { slug: "hanwha", label: "Hanwha / Samsung" },
  { slug: "axis", label: "Axis" },
  { slug: "tplink_vigi", label: "TP-Link Vigi" },
  { slug: "reolink", label: "Reolink" },
  { slug: "ezviz", label: "Ezviz" },
  { slug: "foscam", label: "Foscam" },
  { slug: "milesight", label: "Milesight" },
  { slug: "panasonic", label: "Panasonic" },
];

const STORAGE_LABEL: Record<string, string> = {
  local: "Lokal",
  drive: "Google Drive",
  both: "Keduanya",
};

function CameraIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      width="40"
      height="40"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
      <circle cx="12" cy="13" r="4" />
    </svg>
  );
}

function ListEmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-ink-700 bg-ink-900/50 px-4 py-12 text-center">
      <CameraIcon className="mx-auto text-slate-600" />
      <p className="mt-3 text-sm text-slate-500">{text}</p>
    </div>
  );
}

function StreamRow({
  s,
  online,
  onEdit,
  onDelete,
}: {
  s: Stream;
  online: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const summary = (
    <span className="flex items-center justify-between gap-3">
      <span className="min-w-0">
        <span className="block truncate font-medium text-white">{s.name}</span>
        <span className="mt-0.5 flex flex-wrap gap-1.5">
          <Badge tone={online ? "ok" : "bad"}>{online ? "Online" : "Offline"}</Badge>
          {s.brand && <Badge tone="muted">{s.brand}</Badge>}
          <Badge tone="info">{STORAGE_LABEL[s.storage_mode] ?? s.storage_mode}</Badge>
        </span>
      </span>
    </span>
  );
  const actions = (
    <div className="flex gap-2">
      <Button variant="subtle" onClick={onEdit} className="min-h-[40px] px-3">
        Ubah
      </Button>
      <Button variant="danger" onClick={onDelete} className="min-h-[40px] px-3">
        Hapus
      </Button>
    </div>
  );
  return (
    <>
      <div className="md:hidden">
        <Accordion summary={summary}>
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              Terakhir terlihat: {s.last_seen_at ?? "—"}
            </p>
            {actions}
          </div>
        </Accordion>
      </div>
      <div className="hidden items-center justify-between gap-3 rounded-xl border border-ink-700/60 bg-ink-900 px-4 py-3 transition-colors hover:border-ink-500 md:flex">
        {summary}
        {actions}
      </div>
    </>
  );
}

export default function AdminStreamsPage() {
  const { status } = useCameraStatus();
  const [streams, setStreams] = useState<Stream[] | null>(null);
  const [driveAccounts, setDriveAccounts] = useState<DriveAccount[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Stream | null>(null);
  const [deleting, setDeleting] = useState<Stream | null>(null);

  const load = () =>
    api
      .get<Stream[]>("/admin/streams")
      .then(setStreams)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "Gagal memuat kamera");
        setStreams([]);
      });

  useEffect(() => {
    load();
    /* Akun Drive opsional — sembunyikan field bila gagal dimuat. */
    api.get<DriveAccount[]>("/admin/drive-accounts").then(setDriveAccounts).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function doDelete() {
    if (!deleting) return;
    try {
      await api.del(`/admin/streams/${deleting.id}`);
      setDeleting(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus");
    }
  }

  return (
    <div>
      <SectionTitle
        title="Kamera"
        desc="Kelola stream CCTV dan koneksinya"
        action={
          <Button onClick={() => setShowAdd(true)}>+ Tambah Kamera</Button>
        }
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {streams === null ? (
        <Spinner />
      ) : streams.length === 0 ? (
        <ListEmptyState text="Belum ada kamera. Tambahkan yang pertama." />
      ) : (
        <div className="space-y-2">
          {streams.map((s) => (
            <StreamRow
              key={s.id}
              s={s}
              online={status.get(s.id) ?? s.is_online}
              onEdit={() => setEditing(s)}
              onDelete={() => setDeleting(s)}
            />
          ))}
        </div>
      )}

      {showAdd && (
        <AddStreamModal
          onClose={() => setShowAdd(false)}
          onDone={() => {
            setShowAdd(false);
            load();
          }}
        />
      )}
      {editing && (
        <EditStreamModal
          stream={editing}
          driveAccounts={driveAccounts}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            load();
          }}
        />
      )}
      {deleting && (
        <ConfirmModal
          title="Hapus kamera"
          message={`Hapus "${deleting.name}"? Path MediaMTX ikut dilepas.`}
          onCancel={() => setDeleting(null)}
          onConfirm={doDelete}
        />
      )}
    </div>
  );
}

function AddStreamModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("auto");
  const [host, setHost] = useState("");
  const [user, setUser] = useState("admin");
  const [password, setPassword] = useState("");
  const [port, setPort] = useState("554");
  const [channel, setChannel] = useState("1");
  const [rtspUrl, setRtspUrl] = useState("");
  const [useRtsp, setUseRtsp] = useState(false);
  const [candidates, setCandidates] = useState<ScanCandidate[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function doScan() {
    setError("");
    setBusy(true);
    setCandidates(null);
    try {
      const body = useRtsp
        ? { rtsp_url: rtspUrl.trim(), brand: "auto" }
        : {
            brand,
            host: host.trim(),
            username: user.trim(),
            password,
            port: parseInt(port, 10) || 554,
            channel: parseInt(channel, 10) || 1,
          };
      const res = await api.post<{ candidates: ScanCandidate[] }>(
        "/admin/scan",
        body,
      );
      setCandidates(res.candidates);
      if (res.candidates.length === 0) setError("Tidak ada kandidat ditemukan.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan gagal");
    } finally {
      setBusy(false);
    }
  }

  async function pick(c: ScanCandidate) {
    setError("");
    setBusy(true);
    try {
      await api.post<Stream>(
        "/admin/streams",
        {
          name: name.trim(),
          rtsp_url: c.main_url,
          brand: c.brand,
          storage_mode: "local",
        },
      );
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan kamera");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Tambah Kamera" onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="space-y-4">
        <Field label="Nama kamera">
          <TextInput
            placeholder="cth: Gerbang Depan"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

        <div
          className="grid grid-cols-2 gap-1 rounded-xl border border-ink-700 bg-ink-950 p-1"
          role="group"
          aria-label="Metode penambahan kamera"
        >
          {[
            { rtsp: false, label: "Brand + kredensial" },
            { rtsp: true, label: "URL RTSP langsung" },
          ].map((o) => (
            <button
              key={o.label}
              type="button"
              aria-pressed={useRtsp === o.rtsp}
              onClick={() => setUseRtsp(o.rtsp)}
              className={`min-h-[44px] rounded-lg px-3 text-sm font-medium transition-colors ${
                useRtsp === o.rtsp
                  ? "bg-ink-700 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>

        {useRtsp ? (
          <Field label="URL RTSP">
            <TextInput
              placeholder="rtsp://admin:pass@192.168.1.100:554/..."
              value={rtspUrl}
              onChange={(e) => setRtspUrl(e.target.value)}
            />
          </Field>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Brand">
                <Select value={brand} onChange={(e) => setBrand(e.target.value)}>
                  {BRANDS.map((b) => (
                    <option key={b.slug} value={b.slug}>
                      {b.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Host / IP">
                <TextInput
                  placeholder="192.168.1.100"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                />
              </Field>
              <Field label="Username">
                <TextInput
                  value={user}
                  onChange={(e) => setUser(e.target.value)}
                />
              </Field>
              <Field label="Password">
                <TextInput
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
              <Field label="Port RTSP">
                <TextInput
                  inputMode="numeric"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                />
              </Field>
              <Field label="Channel">
                <TextInput
                  inputMode="numeric"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value)}
                />
              </Field>
            </div>
            {brand === "ezviz" && (
              <p className="text-xs text-slate-500">
                Ezviz: password biasanya berupa device verification code (6
                karakter di stiker perangkat).
              </p>
            )}
          </>
        )}

        <Button
          onClick={doScan}
          disabled={busy || !name.trim() || (useRtsp ? !rtspUrl.trim() : !host.trim())}
          className="w-full"
        >
          {busy ? "Memindai…" : "Scan"}
        </Button>

        {candidates && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-slate-300">
              Kandidat ditemukan — pilih satu untuk disimpan:
            </p>
            {candidates.map((c, i) => (
              <button
                key={i}
                onClick={() => pick(c)}
                disabled={busy}
                className="w-full rounded-lg border border-ink-700 bg-ink-950 p-3 text-left transition-colors hover:border-accent-500"
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-white">{c.brand}</span>
                  <Badge tone="info">{c.method}</Badge>
                </span>
                <span className="mt-1 block truncate text-xs text-slate-500">
                  {c.main_url}
                </span>
                {c.sub_url && (
                  <span className="block truncate text-xs text-slate-600">
                    sub: {c.sub_url}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}

function EditStreamModal({
  stream,
  driveAccounts,
  onClose,
  onDone,
}: {
  stream: Stream;
  driveAccounts: DriveAccount[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState(stream.name);
  const [isActive, setIsActive] = useState(true);
  const [storageMode, setStorageMode] = useState(stream.storage_mode);
  const [driveAccountId, setDriveAccountId] = useState<string>(
    stream.drive_account_id ?? "",
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const connectedAccounts = driveAccounts.filter((a) => a.connected);
  const showDrive =
    connectedAccounts.length > 0 &&
    (storageMode === "drive" ||
      storageMode === "both" ||
      stream.drive_account_id != null);

  async function save() {
    setError("");
    setBusy(true);
    try {
      await api.put(`/admin/streams/${stream.id}`, {
        name: name.trim(),
        is_active: isActive,
        storage_mode: storageMode,
      });
      const next = driveAccountId || null;
      if (next !== (stream.drive_account_id ?? null)) {
        await api.patch(`/admin/streams/${stream.id}`, {
          drive_account_id: next,
        });
      }
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Ubah Kamera" onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="space-y-5">
        <div className="space-y-4">
          <p className="text-[13px] font-medium text-slate-400">Kamera</p>
          <Field label="Nama kamera">
            <TextInput value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <label className="flex min-h-[44px] items-center gap-3 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-5 w-5 accent-blue-500"
            />
            Kamera aktif
          </label>
        </div>
        <div className="space-y-4 border-t border-ink-700/60 pt-5">
          <p className="text-[13px] font-medium text-slate-400">
            Penyimpanan rekaman
          </p>
          <Field label="Mode penyimpanan rekaman">
            <Select
              value={storageMode}
              onChange={(e) => setStorageMode(e.target.value)}
            >
              <option value="local">Lokal</option>
              <option value="drive">Google Drive</option>
              <option value="both">Keduanya</option>
            </Select>
          </Field>
          {showDrive && (
            <Field
              label="Akun Google Drive"
              hint="Kamera ini mengunggah rekaman ke akun ini"
            >
              <Select
                value={driveAccountId}
                onChange={(e) => setDriveAccountId(e.target.value)}
              >
                <option value="">Ikuti bawaan (default)</option>
                {connectedAccounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {a.is_default ? " · default" : ""}
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>
        <Button onClick={save} disabled={busy || !name.trim()} className="w-full">
          {busy ? "Menyimpan…" : "Simpan"}
        </Button>
      </div>
    </Modal>
  );
}
