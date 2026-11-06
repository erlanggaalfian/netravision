"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { useCameraStatus } from "../../../hooks/useCameraStatus";
import type { DriveFolder, Group, ScanPath, ScanResult, Stream } from "../../../lib/types";
import { ShareModal } from "../../../components/ShareModal";
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
  NBSelect,
  NBTitle,
} from "../_nb";

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

type Tone = "ok" | "bad" | "warn" | "info" | "muted";
const SCAN_STATUS: Record<string, { label: string; tone: Tone }> = {
  video: { label: "Video", tone: "ok" },
  no_video: { label: "Tanpa video", tone: "warn" },
  auth_failed: { label: "Login salah", tone: "bad" },
  not_found: { label: "Tidak ada", tone: "muted" },
  timeout: { label: "Timeout", tone: "muted" },
  error: { label: "Gagal", tone: "muted" },
  unreachable: { label: "Tidak terjangkau", tone: "muted" },
};

function pathInfo(p: ScanPath): string {
  if (!p.width || !p.height) return "";
  const parts = [`${p.width}×${p.height}`];
  if (p.fps) parts.push(`${p.fps} fps`);
  if (p.gop_seconds) parts.push(`GOP ${p.gop_seconds}s`);
  return parts.join(" · ");
}

const PAGE_SIZE = 12;

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



function StreamRow({
  s,
  online,
  selected,
  onToggleSelect,
  onEdit,
  onDelete,
  onShare,
}: {
  s: Stream;
  online: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onShare: () => void;
}) {
  const checkbox = (
    <input
      type="checkbox"
      checked={selected}
      onChange={onToggleSelect}
      onClick={(e) => e.stopPropagation()}
      className="h-5 w-5 shrink-0 accent-accent-500"
      aria-label={`Pilih ${s.name}`}
    />
  );
  const summary = (
    <span className="flex min-w-0 flex-1 items-center gap-3">
      {checkbox}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-bold tracking-tight text-slate-100">{s.name}</span>
        <span className="mt-1 block">
          <NBBadge tone={online ? "ok" : "bad"}>{online ? "Online" : "Offline"}</NBBadge>
        </span>
      </span>
    </span>
  );
  const actions = (
    <div className="flex flex-wrap gap-2">
      <NBButton variant="secondary" onClick={onShare} className="px-3">
        Bagikan
      </NBButton>
      <NBButton variant="secondary" onClick={onEdit} className="px-3">
        Ubah
      </NBButton>
      <NBButton variant="danger" onClick={onDelete} className="px-3">
        Hapus
      </NBButton>
    </div>
  );
  const details = (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px]">
      {s.brand && (
        <>
          <dt className="text-slate-400">Brand</dt>
          <dd className="text-right font-medium text-slate-200">{s.brand}</dd>
        </>
      )}
      <dt className="text-slate-400">Penyimpanan</dt>
      <dd className="text-right font-medium text-slate-200">{STORAGE_LABEL[s.storage_mode] ?? s.storage_mode}</dd>
      <dt className="text-slate-400">Rekaman</dt>
      <dd className="text-right font-medium text-slate-200">{s.recording_enabled ? "Aktif" : "Mati"}</dd>
      <dt className="text-slate-400">Terakhir terlihat</dt>
      <dd className="text-right font-medium text-slate-200">{s.last_seen_at ? new Date(s.last_seen_at).toLocaleString("id-ID") : "—"}</dd>
    </dl>
  );
  return (
    <>
      <div className="md:hidden">
        <NBAccordion summary={summary}>
          <div className="space-y-4">
            {details}
            {actions}
          </div>
        </NBAccordion>
      </div>
      <div className="hidden items-center justify-between gap-3 rounded-xl bg-ink-800 shadow-sm px-4 py-3 transition-colors md:flex">
        {summary}
        {actions}
      </div>
    </>
  );
}

export default function AdminStreamsPage() {
  const { status } = useCameraStatus();
  const [streams, setStreams] = useState<Stream[] | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupMap, setGroupMap] = useState<Record<number, string[]>>({});
  const [driveFolders, setDriveFolders] = useState<DriveFolder[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Stream | null>(null);
  const [deleting, setDeleting] = useState<Stream | null>(null);
  const [shareFor, setShareFor] = useState<Stream | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [showCoords, setShowCoords] = useState(false);

  /* Filter */
  const [q, setQ] = useState("");
  const [statusF, setStatusF] = useState("all");
  const [groupF, setGroupF] = useState("all");
  /* Bulk */
  const [selected, setSelected] = useState<Set<number>>(new Set());
  /* Pagination */
  const [page, setPage] = useState(1);

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
    api.get<{ folders: DriveFolder[] }>("/admin/storage/google-drive").then((d) => setDriveFolders(d.folders ?? [])).catch(() => {});
    /* Grup untuk filter. */
    api
      .get<Group[]>("/admin/groups")
      .then(async (gs) => {
        setGroups(gs);
        const m: Record<number, string[]> = {};
        await Promise.all(
          gs.map(async (g) => {
            try {
              const r = await api.get<{ stream_ids: number[] }>(
                `/admin/groups/${encodeURIComponent(g.name)}/camera-grants`,
              );
              r.stream_ids.forEach((id) => {
                (m[id] = m[id] || []).push(g.name);
              });
            } catch {
              /* abaikan grup yang gagal dimuat */
            }
          }),
        );
        setGroupMap(m);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    if (!streams) return [];
    const needle = q.trim().toLowerCase();
    return streams.filter((s) => {
      if (needle && !s.name.toLowerCase().includes(needle)) return false;
      if (statusF !== "all") {
        const on = status.get(s.id) ?? s.is_online;
        if ((statusF === "online") !== on) return false;
      }
      if (groupF !== "all" && !(groupMap[s.id] || []).includes(groupF))
        return false;
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streams, q, statusF, groupF, groupMap, status]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const curPage = Math.min(page, totalPages);
  const pageItems = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);
  const filtersActive = q.trim() !== "" || statusF !== "all" || groupF !== "all";

  function clearFilters() {
    setQ("");
    setStatusF("all");
    setGroupF("all");
    setPage(1);
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllPage() {
    const ids = pageItems.map((s) => s.id);
    const allChecked = ids.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allChecked) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  async function doBulkDelete() {
    setError("");
    try {
      for (const id of selected) {
        await api.del(`/admin/streams/${id}`);
      }
      setSelected(new Set());
      setBulkDeleting(false);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus terpilih");
    }
  }

  return (
    <div>
      <NBTitle
        title="Kamera"
        desc="Kelola stream CCTV dan koneksinya"
        action={
          <NBButton onClick={() => setShowAdd(true)}>+ Tambah Kamera</NBButton>
        }
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {/* Filter */}
      <NBCard className="mb-4 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <NBField label="Cari kamera">
            <NBInput
              placeholder="Nama kamera…"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
            />
          </NBField>
          <NBField label="Grup">
            <NBSelect
              value={groupF}
              onChange={(e) => {
                setGroupF(e.target.value);
                setPage(1);
              }}
            >
              <option value="all">Semua grup</option>
              {groups.map((g) => (
                <option key={g.id} value={g.name}>
                  {g.name}
                </option>
              ))}
            </NBSelect>
          </NBField>
          <NBField label="Status">
            <NBSelect
              value={statusF}
              onChange={(e) => {
                setStatusF(e.target.value);
                setPage(1);
              }}
            >
              <option value="all">Semua status</option>
              <option value="online">Online</option>
              <option value="offline">Offline</option>
            </NBSelect>
          </NBField>
          <div className="flex items-end gap-2">
            <span className="tabular-nums">
              <NBBadge tone="info">
                {filtered.length} dari {(streams ?? []).length}
              </NBBadge>
            </span>
            {filtersActive && (
              <NBButton variant="secondary" onClick={clearFilters}>
                Bersihkan
              </NBButton>
            )}
          </div>
        </div>
      </NBCard>

      {/* Bulk bar */}
      {selected.size > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-ink-800 shadow-sm px-4 py-3">
          <span className="text-sm text-slate-300">
            {selected.size} dipilih
          </span>
          <NBButton
            variant="secondary"
            onClick={() => setShowCoords(true)}
           
          >
            Set koordinat ({selected.size})
          </NBButton>
          <NBButton
            variant="danger"
            onClick={() => setBulkDeleting(true)}
           
          >
            Hapus terpilih ({selected.size})
          </NBButton>
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            className="inline-flex min-h-[44px] items-center rounded-lg px-3 text-sm text-slate-400 hover:text-slate-200"
          >
            Batalkan pilihan
          </button>
        </div>
      )}

      {streams === null ? (
        <Spinner />
      ) : pageItems.length === 0 ? (
        <NBEmptyState
          icon={<CameraIcon className="h-8 w-8 text-slate-500" />}
          text={
            filtersActive
              ? "Tidak ada kamera yang cocok dengan filter."
              : "Belum ada kamera. Tambahkan yang pertama."
          }
        />
      ) : (
        <>
          <div className="mb-2 flex items-center gap-3 px-1">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-400">
              <input
                type="checkbox"
                checked={
                  pageItems.length > 0 &&
                  pageItems.every((s) => selected.has(s.id))
                }
                onChange={toggleSelectAllPage}
                className="h-5 w-5 accent-accent-500"
              />
              Pilih semua di halaman ini
            </label>
          </div>
          <div className="space-y-2">
            {pageItems.map((s) => (
              <StreamRow
                key={s.id}
                s={s}
                online={status.get(s.id) ?? s.is_online}
                selected={selected.has(s.id)}
                onToggleSelect={() => toggleSelect(s.id)}
                onEdit={() => setEditing(s)}
                onDelete={() => setDeleting(s)}
                onShare={() => setShareFor(s)}
              />
            ))}
          </div>
          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
              <NBButton
                variant="secondary"
                disabled={curPage <= 1}
                onClick={() => setPage(1)}
                className="px-3"
              >
                «
              </NBButton>
              <NBButton
                variant="secondary"
                disabled={curPage <= 1}
                onClick={() => setPage(curPage - 1)}
                className="px-3"
              >
                ‹
              </NBButton>
              <span className="px-2 text-sm tabular-nums text-slate-400">
                {curPage} / {totalPages}
              </span>
              <NBButton
                variant="secondary"
                disabled={curPage >= totalPages}
                onClick={() => setPage(curPage + 1)}
                className="px-3"
              >
                ›
              </NBButton>
              <NBButton
                variant="secondary"
                disabled={curPage >= totalPages}
                onClick={() => setPage(totalPages)}
                className="px-3"
              >
                »
              </NBButton>
            </div>
          )}
        </>
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
          driveFolders={driveFolders}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            load();
          }}
        />
      )}
      {shareFor && (
        <ShareModal
          streamId={shareFor.id}
          streamName={shareFor.name}
          onClose={() => setShareFor(null)}
        />
      )}
      {deleting && (
        <NBConfirmModal
          title="Hapus kamera"
          message={`Hapus "${deleting.name}"? Path MediaMTX ikut dilepas.`}
          onCancel={() => setDeleting(null)}
          onConfirm={async () => {
            setDeleting(null);
            try {
              await api.del(`/admin/streams/${deleting.id}`);
              load();
            } catch (e) {
              setError(e instanceof ApiError ? e.message : "Gagal menghapus");
            }
          }}
        />
      )}
      {bulkDeleting && (
        <NBConfirmModal
          title="Hapus kamera terpilih"
          message={`Hapus ${selected.size} kamera terpilih?`}
          onCancel={() => setBulkDeleting(false)}
          onConfirm={doBulkDelete}
        />
      )}
      {showCoords && (
        <BulkCoordsModal
          count={selected.size}
          onClose={() => setShowCoords(false)}
          onDone={async (lat, lon) => {
            setError("");
            try {
              for (const id of selected) {
                await api.put(`/admin/streams/${id}`, {
                  latitude: lat,
                  longitude: lon,
                });
              }
              setShowCoords(false);
              setSelected(new Set());
              load();
            } catch (e) {
              setError(
                e instanceof ApiError ? e.message : "Gagal menyimpan koordinat",
              );
            }
          }}
        />
      )}
    </div>
  );
}

function BulkCoordsModal({
  count,
  onClose,
  onDone,
}: {
  count: number;
  onClose: () => void;
  onDone: (lat: number, lon: number) => Promise<void>;
}) {
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const latN = parseFloat(lat);
  const lonN = parseFloat(lon);
  const valid =
    lat.trim() !== "" &&
    lon.trim() !== "" &&
    !Number.isNaN(latN) &&
    !Number.isNaN(lonN) &&
    latN >= -90 &&
    latN <= 90 &&
    lonN >= -180 &&
    lonN <= 180;

  return (
    <Modal title={`Set koordinat (${count} kamera)`} onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <NBField label="Latitude" hint="-90 s/d 90">
          <NBInput
            inputMode="decimal"
            placeholder="-6.2"
            value={lat}
            onChange={(e) => setLat(e.target.value)}
          />
        </NBField>
        <NBField label="Longitude" hint="-180 s/d 180">
          <NBInput
            inputMode="decimal"
            placeholder="106.8"
            value={lon}
            onChange={(e) => setLon(e.target.value)}
          />
        </NBField>
      </div>
      <NBButton
        className="mt-4 w-full"
        disabled={!valid || busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onDone(latN, lonN);
          } catch (e) {
            setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Menyimpan…" : "Terapkan ke semua terpilih"}
      </NBButton>
    </Modal>
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
  const [results, setResults] = useState<ScanResult | null>(null);
  const [picked, setPicked] = useState<ScanPath | null>(null);
  const [recordingEnabled, setRecordingEnabled] = useState(false);
  const [retentionDays, setRetentionDays] = useState("7");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function doScan() {
    setError("");
    setBusy(true);
    setResults(null);
    setPicked(null);
    try {
      const body = useRtsp
        ? { rtsp_url: rtspUrl.trim() }
        : {
            brand,
            host: host.trim(),
            user: user.trim(),
            password,
            port: parseInt(port, 10) || 554,
            channel: parseInt(channel, 10) || 1,
          };
      const res = await api.post<ScanResult>("/admin/scan", body);
      setResults(res);
      if (res.paths.length > 0 && res.best_main) {
        setPicked(res.paths.find((p) => p.role === "main") ?? null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan gagal");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!picked) return;
    setError("");
    setBusy(true);
    try {
      const lat = latitude.trim() === "" ? null : parseFloat(latitude);
      const lon = longitude.trim() === "" ? null : parseFloat(longitude);
      // force: path dipilih admin setelah diverifikasi video saat scan;
      // hindari sesi RTSP ganda ke kamera yang membatasi sesi.
      const res = await api.post<Stream & { mediamtx_registered?: boolean; mediamtx_error?: string | null }>(
        "/admin/streams",
        {
          name: name.trim(),
          rtsp_url: picked.url,
          storage_mode: "local",
          recording_enabled: recordingEnabled,
          retention_days: Math.min(365, Math.max(1, parseInt(retentionDays, 10) || 7)),
          latitude: lat !== null && !Number.isNaN(lat) ? lat : null,
          longitude: lon !== null && !Number.isNaN(lon) ? lon : null,
          force: true,
        },
      );
      if (res.mediamtx_registered === false) {
        setError(
          "Kamera tersimpan, tapi gagal didaftarkan ke MediaMTX" +
          (res.mediamtx_error ? `: ${res.mediamtx_error}` : "") +
          ". Path akan terdaftar otomatis saat MediaMTX pulih (sync berkala)."
        );
        return;
      }
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
        <NBField label="Nama kamera">
          <NBInput
            placeholder="cth: Gerbang Depan"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </NBField>

        <div
          className="grid grid-cols-2 gap-1 rounded-xl bg-ink-800 shadow-sm p-1"
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
              className={`min-h-[44px] rounded-full px-3 text-sm font-medium transition-colors ${
                useRtsp === o.rtsp
                  ? "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                  : "text-slate-400 hover:bg-ink-700 hover:text-slate-200"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>

        {useRtsp ? (
          <NBField label="URL RTSP">
            <NBInput
              placeholder="rtsp://admin:pass@192.168.1.100:554/..."
              value={rtspUrl}
              onChange={(e) => setRtspUrl(e.target.value)}
            />
          </NBField>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <NBField label="Brand">
                <NBSelect value={brand} onChange={(e) => setBrand(e.target.value)}>
                  {BRANDS.map((b) => (
                    <option key={b.slug} value={b.slug}>
                      {b.label}
                    </option>
                  ))}
                </NBSelect>
              </NBField>
              <NBField label="Host / IP">
                <NBInput
                  placeholder="192.168.1.100"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                />
              </NBField>
              <NBField label="Username">
                <NBInput
                  value={user}
                  onChange={(e) => setUser(e.target.value)}
                />
              </NBField>
              <NBField label="Password">
                <NBInput
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </NBField>
              <NBField label="Port RTSP">
                <NBInput
                  inputMode="numeric"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                />
              </NBField>
              <NBField label="Channel">
                <NBInput
                  inputMode="numeric"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value)}
                />
              </NBField>
            </div>
            {brand === "ezviz" && (
              <p className="text-xs text-slate-400">
                Ezviz: password biasanya berupa device verification code (6
                karakter di stiker perangkat).
              </p>
            )}
          </>
        )}

        <div className="space-y-4 rounded-xl bg-ink-800 shadow-sm p-4">
          <p className="text-[13px] font-medium text-slate-400">Rekaman & lokasi</p>
          <label className="flex min-h-[44px] items-center gap-3 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={recordingEnabled}
              onChange={(e) => setRecordingEnabled(e.target.checked)}
              className="h-5 w-5 accent-accent-500"
            />
            Simpan rekaman ke disk
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <NBField label="Retensi (hari)" hint="1–365">
              <NBInput
                inputMode="numeric"
                value={retentionDays}
                onChange={(e) => setRetentionDays(e.target.value)}
              />
            </NBField>
            <NBField label="Latitude">
              <NBInput
                inputMode="decimal"
                placeholder="-6.2"
                value={latitude}
                onChange={(e) => setLatitude(e.target.value)}
              />
            </NBField>
            <NBField label="Longitude">
              <NBInput
                inputMode="decimal"
                placeholder="106.8"
                value={longitude}
                onChange={(e) => setLongitude(e.target.value)}
              />
            </NBField>
          </div>
        </div>

        <NBButton
          onClick={doScan}
          disabled={busy || (useRtsp ? !rtspUrl.trim() : !host.trim())}
          variant="secondary"
          className="w-full"
        >
          {busy ? "Memindai…" : "Cari otomatis"}
        </NBButton>

        {results && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-slate-300">
              Path RTSP — pilih satu untuk dijadikan main:
            </p>
            <div className="max-h-72 space-y-1.5 overflow-y-auto">
              {[
                ...results.paths.filter((p) => p.status === "video"),
                ...results.paths.filter((p) => p.status !== "video"),
              ].map((p) => {
                const st = SCAN_STATUS[p.status] ?? SCAN_STATUS.error;
                const active = picked?.url === p.url;
                return (
                  <button
                    key={p.url}
                    type="button"
                    onClick={() => setPicked(p)}
                    aria-pressed={active}
                    className={`flex min-h-[44px] w-full items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors ${
                      active
                        ? "bg-accent-600/15"
                        : "bg-ink-800 shadow-sm hover:bg-ink-700"
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate font-mono text-[13px] text-white">
                          {p.path}
                        </span>
                        {p.role === "main" && <NBBadge tone="info">Main</NBBadge>}
                        {p.role === "sub" && <NBBadge tone="muted">Sub</NBBadge>}
                      </span>
                      {pathInfo(p) && (
                        <span className="mt-0.5 block text-xs text-slate-400">
                          {pathInfo(p)}
                        </span>
                      )}
                    </span>
                    <NBBadge tone={st.tone}>{st.label}</NBBadge>
                  </button>
                );
              })}
            </div>
            {results.paths.length === 0 && (
              <p className="text-xs text-slate-400">
                Tidak ada path yang bisa dicoba (host tidak terjangkau).
              </p>
            )}
            <NBButton
              onClick={save}
              disabled={busy || !name.trim() || !picked}
              className="w-full"
            >
              {busy ? "Menyimpan…" : "Simpan kamera"}
            </NBButton>
          </div>
        )}
      </div>
    </Modal>
  );
}

function EditStreamModal({
  stream,
  driveFolders,
  onClose,
  onDone,
}: {
  stream: Stream;
  driveFolders: DriveFolder[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState(stream.name);
  const [isActive, setIsActive] = useState(stream.is_active);
  const [storageMode, setStorageMode] = useState(stream.storage_mode);
  const [driveFolderId, setDriveFolderId] = useState<string>(
    stream.drive_folder_id != null ? String(stream.drive_folder_id) : "",
  );
  const [recordingEnabled, setRecordingEnabled] = useState(stream.recording_enabled);
  const [retentionDays, setRetentionDays] = useState(String(stream.retention_days));
  const [latitude, setLatitude] = useState(
    stream.latitude !== null ? String(stream.latitude) : "",
  );
  const [longitude, setLongitude] = useState(
    stream.longitude !== null ? String(stream.longitude) : "",
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const showDriveFolder =
    driveFolders.length > 0 &&
    (storageMode === "drive" ||
      storageMode === "both" ||
      stream.drive_folder_id != null);

  async function save() {
    setError("");
    setBusy(true);
    try {
      const lat = latitude.trim() === "" ? null : parseFloat(latitude);
      const lon = longitude.trim() === "" ? null : parseFloat(longitude);
      await api.put(`/admin/streams/${stream.id}`, {
        name: name.trim(),
        is_active: isActive,
        storage_mode: storageMode,
        recording_enabled: recordingEnabled,
        retention_days: Math.min(365, Math.max(1, parseInt(retentionDays, 10) || 7)),
        latitude: lat !== null && !Number.isNaN(lat) ? lat : null,
        longitude: lon !== null && !Number.isNaN(lon) ? lon : null,
        drive_folder_id: driveFolderId === "" ? null : parseInt(driveFolderId, 10),
      });
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
          <NBField label="Nama kamera">
            <NBInput value={name} onChange={(e) => setName(e.target.value)} />
          </NBField>
          <label className="flex min-h-[44px] items-center gap-3 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-5 w-5 accent-accent-500"
            />
            Kamera aktif
          </label>
        </div>
        <div className="space-y-4 border-t border-ink-800 pt-5">
          <p className="text-[13px] font-medium text-slate-400">
            Penyimpanan rekaman
          </p>
          <label className="flex min-h-[44px] items-center gap-3 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={recordingEnabled}
              onChange={(e) => setRecordingEnabled(e.target.checked)}
              className="h-5 w-5 accent-accent-500"
            />
            Simpan rekaman ke disk
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <NBField label="Retensi (hari)" hint="1–365">
              <NBInput
                inputMode="numeric"
                value={retentionDays}
                onChange={(e) => setRetentionDays(e.target.value)}
              />
            </NBField>
            <NBField label="Latitude">
              <NBInput
                inputMode="decimal"
                placeholder="-6.2"
                value={latitude}
                onChange={(e) => setLatitude(e.target.value)}
              />
            </NBField>
            <NBField label="Longitude">
              <NBInput
                inputMode="decimal"
                placeholder="106.8"
                value={longitude}
                onChange={(e) => setLongitude(e.target.value)}
              />
            </NBField>
          </div>
          <NBField label="Mode penyimpanan rekaman">
            <NBSelect
              value={storageMode}
              onChange={(e) => setStorageMode(e.target.value)}
            >
              <option value="local">Lokal</option>
              <option value="drive">Google Drive</option>
              <option value="both">Keduanya</option>
            </NBSelect>
          </NBField>
          {showDriveFolder && (
            <NBField
              label="Folder Google Drive tujuan"
              hint="Pilih folder tempat rekaman kamera ini disimpan"
            >
              <NBSelect
                value={driveFolderId}
                onChange={(e) => setDriveFolderId(e.target.value)}
              >
                <option value="">Default (folder pertama)</option>
                {driveFolders.map((f) => (
                  <option key={f.id} value={String(f.id)}>
                    {f.folder_name || f.folder_id}
                  </option>
                ))}
              </NBSelect>
            </NBField>
          )}
        </div>
        <NBButton onClick={save} disabled={busy || !name.trim()} className="w-full">
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}
