"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { filterStreamsForRole } from "../../../lib/scope";
import { useCameraStatus } from "../../../hooks/useCameraStatus";
import type { AdConfig, Disk, DriveFolder, Group, ScanPath, ScanResult, Stream } from "../../../lib/types";
import { ShareModal } from "../../../components/ShareModal";
import { FocusModal } from "../../../components/FocusModal";
import { LocationInput } from "../../../components/LocationInput";
import { ErrorBox, Modal, Pagination, Spinner, Switch } from "../../../components/ui";
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
  /* Sama seperti Camera Scanner: auth gagal = user perlu cek password. */
  auth_failed: { label: "Perlu cek password", tone: "bad" },
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

/* E-S7: validasi latitude/longitude, dipakai form Tambah dan Ubah. */
function coordError(lat: string, lon: string): string | null {
  const latN = lat.trim() === "" ? null : parseFloat(lat);
  const lonN = lon.trim() === "" ? null : parseFloat(lon);
  if (latN !== null && (Number.isNaN(latN) || latN < -90 || latN > 90)) {
    return "Latitude harus angka -90 sampai 90.";
  }
  if (lonN !== null && (Number.isNaN(lonN) || lonN < -180 || lonN > 180)) {
    return "Longitude harus angka -180 sampai 180.";
  }
  return null;
}

/* F6.7: validasi nama dan skema URL RTSP di frontend, sebelum kirim.
   Backend tetap otorisasi akhir; ini supaya admin tidak menyimpan nama
   kosong atau URL berskema aneh yang gagal di MediaMTX. */
function cameraNameError(name: string): string | null {
  const n = name.trim();
  if (!n) return "Nama kamera tidak boleh kosong.";
  if (n.length > 100) return "Nama kamera maksimal 100 karakter.";
  return null;
}

function rtspUrlError(url: string | null, label: string): string | null {
  if (url == null || url.trim() === "") return null;
  const u = url.trim();
  if (u.startsWith("rtsp://") || u.startsWith("rtsps://")) return null;
  return `${label} harus diawali rtsp:// atau rtsps://.`;
}

/* Sanitasi satu segmen path rekaman: hanya alnum, "-", "_", spasi jadi "_". */
function sanitizePathPart(v: string): string {
  return v.replace(/[^A-Za-z0-9\-_ ]/g, "_").replace(/ /g, "_");
}

/* Pilihan disk rekaman + info ketersediaan + path rekaman live.
   Dipakai form Tambah dan form Ubah. */
function DiskPicker({
  disks,
  value,
  onChange,
  groupNames,
  cameraName,
}: {
  disks: Disk[];
  value: string;
  onChange: (v: string) => void;
  groupNames: string[];
  cameraName: string;
}) {
  const selected = disks.find((d) => d.mount === value) ?? null;
  /* Remote rclone (mis. rclone:gdrive) BUKAN disk lokal dan BUKAN nilai
     record_disk yang valid: backend menolaknya karena bukan path absolut
     ke direktori yang ada. Jangan ditawarkan sebagai pilihan disk, karena
     tampil sebagai "disk" padahal itu tujuan Google Drive, dan itulah
     yang membuat kontrol penyimpanan tampak ganda dengan Mode
     penyimpanan. Hanya disk lokal yang ditawarkan; nilai lama yang
     sudah tersimpan tetap ditampilkan lewat showValueAsOption. */
  const localDisks = disks.filter((d) => !d.mount.startsWith("rclone:"));
  const defaultDisk = localDisks.find((d) => d.mount === "/") ?? null;
  /* Info disk terpilih; bila Default, info disk default ("/") bila ada,
     bila tidak ada sembunyikan baris ini. */
  const infoDisk = selected ?? (value === "" ? defaultDisk : null);
  const firstGroup = [...groupNames].sort((a, b) => a.localeCompare(b))[0] ?? "";
  const diskForPath = value === "" ? "/" : value;
  const path =
    `${diskForPath.replace(/\/$/, "")}/recordings/` +
    `${sanitizePathPart(firstGroup.trim() === "" ? "Default" : firstGroup)}/` +
    `${sanitizePathPart(cameraName.trim() === "" ? "stream" : cameraName)}/`;
  /* Nilai tersimpan yang sudah tidak ada di list disk tetap ditampilkan
     supaya data lama tidak hilang diam-diam. */
  const showValueAsOption = value !== "" && !selected;
  return (
    <div className="space-y-2">
      <NBField label="Save to disk">
        <NBSelect value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Default</option>
          {localDisks.map((d) => (
            <option key={d.mount} value={d.mount}>
              {d.mount} ({d.avail_human} free / {d.size_human})
            </option>
          ))}
          {showValueAsOption && <option value={value}>{value}</option>}
        </NBSelect>
      </NBField>
      {infoDisk && (
        <p className="text-xs text-slate-400">
          Available: {infoDisk.avail_human} | Usage: {infoDisk.usage_pct}%
        </p>
      )}
      {/* Path rekaman hanya info baca-saja (teks kecil abu-abu),
          bukan field input, supaya tidak membingungkan. */}
      <p className="text-xs leading-relaxed text-slate-400">
        <span className="font-semibold text-slate-300">Path rekaman: </span>
        <span className="break-all font-mono">{path}</span>
      </p>
    </div>
  );
}

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
  groups,
  selected,
  onToggleSelect,
  onEdit,
  onDelete,
  onShare,
  onView,
  canShare,
  isSuperAdmin,
}: {
  s: Stream;
  online: boolean;
  groups: string[];
  selected: boolean;
  onToggleSelect: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onShare: () => void;
  /* Buka popup live yang sama seperti di menu Live (FocusModal). */
  onView: () => void;
  /* Admin biasa hanya boleh membagikan kamera yang diizinkan
     superadmin (can_reshare); tambah/ubah/hapus hanya superadmin. */
  canShare: boolean;
  isSuperAdmin: boolean;
}) {
  const checkbox = (
    <input
      type="checkbox"
      checked={selected}
      onChange={onToggleSelect}
      onClick={(e) => e.stopPropagation()}
      className="h-5 w-5 shrink-0 accent-accent-500 p-2 -m-2"
      aria-label={`Pilih ${s.name}`}
    />
  );
  const summary = (
    <span className="flex min-w-0 flex-1 items-center gap-3">
      {isSuperAdmin && checkbox}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-bold tracking-tight text-slate-100">{s.name}</span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <NBBadge size="sm" tone={online ? "ok" : "bad"}>{online ? "Online" : "Offline"}</NBBadge>
          {s.recording_enabled ? (
            <NBBadge size="sm" tone="warn">Merekam</NBBadge>
          ) : (
            <NBBadge size="sm" tone="muted">Stream saja</NBBadge>
          )}
          {groups.map((g) => (
            <NBBadge key={g} tone="info">
              {g}
            </NBBadge>
          ))}
        </span>
      </span>
    </span>
  );
  const actions = (
    <div className="flex flex-wrap gap-2">
      <NBButton variant="secondary" onClick={onView} className="px-3">
        Lihat
      </NBButton>
      {canShare && (
        <NBButton variant="secondary" onClick={onShare} className="px-3">
          Bagikan
        </NBButton>
      )}
      {isSuperAdmin && (
        <>
          <NBButton variant="secondary" onClick={onEdit} className="px-3">
            Ubah
          </NBButton>
          <NBButton variant="danger" onClick={onDelete} className="px-3">
            Hapus
          </NBButton>
        </>
      )}
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
      <dt className="text-slate-400">Grup</dt>
      <dd className="text-right font-medium text-slate-200">{groups.length > 0 ? groups.join(", ") : "-"}</dd>
      <dt className="text-slate-400">Rekaman</dt>
      <dd className="text-right font-medium text-slate-200">{s.recording_enabled ? "Aktif" : "Mati"}</dd>
      <dt className="text-slate-400">Terakhir terlihat</dt>
      <dd className="text-right font-medium text-slate-200">{s.last_seen_at ? new Date(s.last_seen_at).toLocaleString("id-ID") : "-"}</dd>
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
      <div className="hidden items-center justify-between gap-3 rounded-xl bg-ink-900 shadow-sm px-4 py-3 transition-colors md:flex">
        {summary}
        {actions}
      </div>
    </>
  );
}

export default function AdminStreamsPage() {
  const { user: me } = useAuth();
  const isSuperAdmin = me?.role === "super_admin";
  const { status } = useCameraStatus();
  const [streams, setStreams] = useState<Stream[] | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupMap, setGroupMap] = useState<Record<number, string[]>>({});
  const [driveFolders, setDriveFolders] = useState<DriveFolder[]>([]);
  /* Daftar disk untuk pilihan Save to disk di form tambah/ubah. */
  const [disks, setDisks] = useState<Disk[]>([]);
  /* Kamera yang boleh dibagikan admin biasa (can_reshare dari
     superadmin). Superadmin boleh membagikan semua kamera. */
  const [reshareIds, setReshareIds] = useState<Set<number>>(new Set());
  /* Kamera yang boleh dilihat admin biasa (grant can_view milik
     sendiri); sinyal kedua untuk cakupan, lihat lib/scope.ts. */
  const [viewIds, setViewIds] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Stream | null>(null);
  const [deleting, setDeleting] = useState<Stream | null>(null);
  const [shareFor, setShareFor] = useState<Stream | null>(null);
  /* Kamera yang dibuka di popup live (FocusModal, sama seperti Live). */
  const [focus, setFocus] = useState<Stream | null>(null);
  const [ad, setAd] = useState<AdConfig | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  /* Hapus (tunggal/massal) berjalan async: modal konfirmasi nonaktif
     selama proses, sama seperti hapus di Pengguna/API Key/Penyimpanan. */
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [showCoords, setShowCoords] = useState(false);
  const [showGroup, setShowGroup] = useState(false);

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

  /* Grup untuk filter (dipakai ulang setelah set grup massal).
     Admin biasa TIDAK meminta camera-grants per grup: endpoint itu
     mengembalikan anggota semua grup, termasuk grup lain. Nama grup
     saja yang dimuat; peta grup admin diturunkan dari group_name
     tiap kamera yang terlihat (lihat adminGroupMap di bawah). */
  const loadGroups = () =>
    api
      .get<Group[]>("/admin/groups")
      .then(async (gs) => {
        setGroups(gs);
        if (!isSuperAdmin) return;
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

  useEffect(() => {
    load();
    /* Config iklan untuk popup live (FocusModal), sama seperti Live. */
    api.get<AdConfig>("/ad-config").then(setAd).catch(() => {});
    /* Akun Drive opsional, sembunyikan field bila gagal dimuat. */
    api.get<{ folders: DriveFolder[] }>("/admin/storage/google-drive").then((d) => setDriveFolders(d.folders ?? [])).catch(() => {});
    /* Daftar disk untuk pilihan Save to disk; diam bila gagal
       (mis. bukan superadmin, endpoint super_admin-only). */
    api.get<Disk[]>("/admin/disks").then(setDisks).catch(() => setDisks([]));
    loadGroups();
    /* Admin biasa: muat grant can_reshare agar tombol Bagikan hanya
       tampil di kamera yang diizinkan superadmin untuk dibagikan,
       dan grant can_view sebagai sinyal kedua cakupan kamera. */
    if (me && !isSuperAdmin) {
      api
        .get<{
          grants: {
            stream_id: number;
            can_view: boolean;
            can_reshare: boolean;
          }[];
        }>(`/admin/admins/${me.id}/camera-grants`)
        .then((d) => {
          const gs = d.grants ?? [];
          setReshareIds(
            new Set(
              gs.filter((g) => g.can_reshare).map((g) => g.stream_id),
            ),
          );
          setViewIds(
            new Set(gs.filter((g) => g.can_view).map((g) => g.stream_id)),
          );
        })
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.id]);

  /* Cakupan admin biasa: hanya kamera sendiri atau yang di-grant
     can_view (lib/scope.ts). Semua tampilan di halaman ini memakai
     visibleStreams, bukan streams mentah, supaya tidak ada kamera
     grup lain yang tampil, dicari, atau dihitung. */
  const visibleStreams = useMemo(
    () => filterStreamsForRole(me, streams ?? [], viewIds),
    [me, streams, viewIds],
  );
  /* Peta grup admin biasa: dari group_name cache tiap kamera yang
     terlihat, tanpa meminta camera-grants grup lain. */
  const adminGroupMap = useMemo(() => {
    const m: Record<number, string[]> = {};
    for (const s of visibleStreams) {
      if (s.group_name) m[s.id] = [s.group_name];
    }
    return m;
  }, [visibleStreams]);
  const effectiveGroupMap = isSuperAdmin ? groupMap : adminGroupMap;
  /* Pilihan filter grup: admin hanya melihat grup yang berisi
     sedikitnya satu kamera yang terlihat. */
  const filterGroups = useMemo(() => {
    if (isSuperAdmin) return groups;
    const names = new Set(
      visibleStreams.map((s) => s.group_name).filter((n): n is string => !!n),
    );
    return groups.filter((g) => names.has(g.name));
  }, [isSuperAdmin, groups, visibleStreams]);

  const filtered = useMemo(() => {
    if (!streams) return [];
    const needle = q.trim().toLowerCase();
    return visibleStreams.filter((s) => {
      if (needle && !s.name.toLowerCase().includes(needle)) return false;
      if (statusF !== "all") {
        const on = status.get(s.id) ?? s.is_online;
        if ((statusF === "online") !== on) return false;
      }
      if (groupF === "none") {
        /* "Tanpa grup": hanya kamera yang tidak punya grup sama sekali.
           Untuk admin biasa hasilnya kosong (scoping per grup menyembunyikan
           kamera tanpa grup), jadi opsi ini praktis hanya berguna untuk
           super_admin. */
        if ((effectiveGroupMap[s.id] || []).length > 0) return false;
      } else if (
        groupF !== "all" &&
        !(effectiveGroupMap[s.id] || []).includes(groupF)
      )
        return false;
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streams, visibleStreams, q, statusF, groupF, effectiveGroupMap, status]);

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
    if (bulkBusy) return;
    setBulkBusy(true);
    setError("");
    /* E-S6: laporkan hasil per kamera, bersihkan selected hanya
       untuk yang berhasil, yang gagal tetap terpilih. */
    const failed: { id: number; name: string }[] = [];
    const succeeded: number[] = [];
    for (const id of selected) {
      try {
        await api.del(`/admin/streams/${id}`);
        succeeded.push(id);
      } catch {
        failed.push({
          id,
          name: streams?.find((s) => s.id === id)?.name ?? `#${id}`,
        });
      }
    }
    setSelected(new Set(failed.map((f) => f.id)));
    load();
    setBulkBusy(false);
    if (failed.length === 0) {
      setBulkDeleting(false);
      return;
    }
    setError(
      `Gagal menghapus ${failed.length} kamera: ${failed.map((f) => f.name).join(", ")}. ${succeeded.length} kamera berhasil dihapus.`,
    );
    /* Modal tetap terbuka supaya yang gagal bisa dicoba lagi. */
  }

  return (
    <div>
      <NBTitle
        title="Kamera"
        desc="Kelola stream CCTV dan koneksinya"
        action={
          isSuperAdmin ? (
            <NBButton onClick={() => setShowAdd(true)}>+ Tambah Kamera</NBButton>
          ) : undefined
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
              <option value="none">Tanpa grup</option>
              {filterGroups.map((g) => (
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
          {/* Sel jumlah sejajar kotak input: pelabel tak terlihat setinggi
              label field, isi baris setinggi input (h-11) dan lencana
              di tengah vertikal, supaya tidak jatuh ke bawah. */}
          <div className="flex flex-col">
            <span
              className="mb-1.5 block text-sm font-semibold invisible select-none"
              aria-hidden="true"
            >
              Jumlah
            </span>
            <div className="flex h-11 items-center gap-2">
              <span className="tabular-nums">
                <NBBadge tone="info">
                  {filtered.length} dari {visibleStreams.length}
                </NBBadge>
              </span>
              {filtersActive && (
                <NBButton variant="secondary" onClick={clearFilters}>
                  Bersihkan
                </NBButton>
              )}
            </div>
          </div>
        </div>
      </NBCard>

      {/* Bulk bar: hanya superadmin (tambah/ubah/hapus massal kamera). */}
      {isSuperAdmin && selected.size > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-ink-900 shadow-sm px-4 py-3">
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
            variant="secondary"
            onClick={() => setShowGroup(true)}
          >
            Set grup ({selected.size})
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
              : isSuperAdmin
                ? "Belum ada kamera. Tambahkan yang pertama."
                : "Belum ada kamera di grup Anda."
          }
        />
      ) : (
        <>
          {isSuperAdmin && (
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
          )}
          <div className="space-y-2">
            {pageItems.map((s) => (
              <StreamRow
                key={s.id}
                s={s}
                online={status.get(s.id) ?? s.is_online}
                groups={effectiveGroupMap[s.id] ?? []}
                selected={selected.has(s.id)}
                onToggleSelect={() => toggleSelect(s.id)}
                onEdit={() => setEditing(s)}
                onDelete={() => setDeleting(s)}
                onShare={() => setShareFor(s)}
                onView={() => setFocus(s)}
                canShare={isSuperAdmin || reshareIds.has(s.id)}
                isSuperAdmin={isSuperAdmin}
              />
            ))}
          </div>
          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4">
              <Pagination
                page={curPage}
                totalPages={totalPages}
                onChange={setPage}
              />
            </div>
          )}
        </>
      )}

      {showAdd && (
        <AddStreamModal
          driveFolders={driveFolders}
          disks={disks}
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
          disks={disks}
          groupNames={groupMap[editing.id] ?? []}
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
      {/* Popup live yang sama seperti di menu Live. */}
      <FocusModal stream={focus} onClose={() => setFocus(null)} ad={ad} />
      {deleting && (
        <NBConfirmModal
          title="Hapus kamera"
          message={`Hapus "${deleting.name}"? Path MediaMTX ikut dilepas.`}
          busy={deleteBusy}
          onCancel={() => setDeleting(null)}
          onConfirm={async () => {
            /* Tutup hanya bila berhasil (sama seperti hapus pengguna/
               key/folder): gagal tetap membuka modal supaya bisa coba
               lagi, error tampil di atas halaman. */
            if (deleteBusy) return;
            setDeleteBusy(true);
            try {
              await api.del(`/admin/streams/${deleting.id}`);
              setDeleting(null);
              load();
            } catch (e) {
              setError(e instanceof ApiError ? e.message : "Gagal menghapus");
            } finally {
              setDeleteBusy(false);
            }
          }}
        />
      )}
      {bulkDeleting && (
        <NBConfirmModal
          title="Hapus kamera terpilih"
          message={`Hapus ${selected.size} kamera terpilih?`}
          busy={bulkBusy}
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
            /* E-S6: laporkan hasil per kamera; lempar error supaya
               BulkCoordsModal menampilkannya di dalam modal. */
            const failed: string[] = [];
            const succeeded: number[] = [];
            for (const id of selected) {
              try {
                await api.put(`/admin/streams/${id}`, {
                  latitude: lat,
                  longitude: lon,
                });
                succeeded.push(id);
              } catch {
                failed.push(
                  streams?.find((s) => s.id === id)?.name ?? `#${id}`,
                );
              }
            }
            setSelected(new Set(
              [...selected].filter((id) => !succeeded.includes(id)),
            ));
            load();
            if (failed.length === 0) {
              setShowCoords(false);
              setSelected(new Set());
              return;
            }
            throw new Error(
              `Gagal menyimpan koordinat untuk ${failed.length} kamera: ${failed.join(", ")}. ${succeeded.length} kamera berhasil.`,
            );
          }}
        />
      )}
      {showGroup && (
        <BulkGroupModal
          count={selected.size}
          groups={groups}
          onClose={() => setShowGroup(false)}
          onDone={async (groupName) => {
            setError("");
            try {
              /* Buat grup dulu bila belum ada. */
              if (!groups.some((g) => g.name === groupName)) {
                await api.put(`/admin/groups/${encodeURIComponent(groupName)}`, {
                  name: groupName,
                  description: null,
                });
              }
              /* POST camera-grants mengganti seluruh anggota grup, jadi
                 gabung dulu dengan anggota yang sudah ada supaya tidak
                 ada kamera yang terhapus dari grup. */
              let current: number[] = [];
              try {
                const r = await api.get<{ stream_ids: number[] }>(
                  `/admin/groups/${encodeURIComponent(groupName)}/camera-grants`,
                );
                current = r.stream_ids;
              } catch {
                /* grup baru: mulai dari kosong */
              }
              const merged = [...new Set([...current, ...selected])];
              await api.post(
                `/admin/groups/${encodeURIComponent(groupName)}/camera-grants`,
                { stream_ids: merged },
              );
              setShowGroup(false);
              setSelected(new Set());
              load();
              loadGroups();
            } catch (e) {
              const msg =
                e instanceof ApiError ? e.message : "Gagal menyimpan grup";
              setError(msg);
              throw e;
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
      <div className="mb-3">
        <LocationInput
          lat={lat}
          lng={lon}
          onChange={(la, lo) => {
            setLat(la);
            setLon(lo);
          }}
        />
      </div>
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
            setError(
              e instanceof ApiError
                ? e.message
                : e instanceof Error
                  ? e.message
                  : "Gagal menyimpan",
            );
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

function BulkGroupModal({
  count,
  groups,
  onClose,
  onDone,
}: {
  count: number;
  groups: Group[];
  onClose: () => void;
  onDone: (groupName: string) => Promise<void>;
}) {
  const NEW = "__baru__";
  const [picked, setPicked] = useState(groups[0]?.name ?? NEW);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const name = picked === NEW ? newName.trim() : picked;
  const valid = name !== "";

  return (
    <Modal title={`Set grup (${count} kamera)`} onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <NBField label="Grup">
        <NBSelect value={picked} onChange={(e) => setPicked(e.target.value)}>
          {groups.map((g) => (
            <option key={g.id} value={g.name}>
              {g.name}
            </option>
          ))}
          <option value={NEW}>+ Grup baru…</option>
        </NBSelect>
      </NBField>
      {picked === NEW && (
        <div className="mt-3">
          <NBField label="Nama grup baru">
            <NBInput
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="cth. Lantai 1"
            />
          </NBField>
        </div>
      )}
      <p className="mt-3 text-xs leading-relaxed text-slate-400">
        Kamera terpilih ditambahkan ke grup. Kamera yang sudah ada di grup
        tetap dipertahankan.
      </p>
      <NBButton
        className="mt-4 w-full"
        disabled={!valid || busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onDone(name);
          } catch (e) {
            setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Menyimpan…" : "Tambahkan ke grup"}
      </NBButton>
    </Modal>
  );
}

function AddStreamModal({
  driveFolders,
  disks,
  onClose,
  onDone,
}: {
  driveFolders: DriveFolder[];
  disks: Disk[];
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
  const [recordDisk, setRecordDisk] = useState("");
  const [retentionDays, setRetentionDays] = useState("7");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  /* E-S8: selector mode penyimpanan + folder Drive seperti Edit. */
  const [storageMode, setStorageMode] = useState("local");
  const [driveFolderId, setDriveFolderId] = useState("");
  const showDriveFolder = storageMode === "drive" || storageMode === "both";
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
    /* E-S7: validasi latitude/longitude sebelum kirim. */
    const badCoord = coordError(latitude, longitude);
    if (badCoord) {
      setError(badCoord);
      return;
    }
    /* F6.7: nama wajib isi (maks 100 karakter) dan path hasil scan
       wajib RTSP. */
    const badName = cameraNameError(name);
    if (badName) {
      setError(badName);
      return;
    }
    const badRtsp = rtspUrlError(picked.url, "URL RTSP");
    if (badRtsp) {
      setError(badRtsp);
      return;
    }
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
          // 4.6: picked.url kini TEREDAKSI (password ****); scan_ref
          // memberitahu backend memulihkan URL asli dari brankas
          // server (termasuk password default hasil discovery).
          scan_ref: results?.scan_id ?? undefined,
          storage_mode: storageMode,
          drive_folder_id:
            storageMode === "local" || driveFolderId === ""
              ? null
              : parseInt(driveFolderId, 10),
          recording_enabled: recordingEnabled,
          record_disk: recordDisk,
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

        <div className="space-y-5 rounded-xl bg-ink-800 shadow-sm p-4">
          <div className="space-y-4">
            <p className="text-[13px] font-medium text-slate-400">Rekaman</p>
            <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 text-sm text-slate-300">
              <span>Simpan rekaman ke disk</span>
              <Switch
                checked={recordingEnabled}
                onChange={setRecordingEnabled}
                label="Simpan rekaman ke disk"
              />
            </label>
            <NBField label="Retensi (hari)" hint="1-365">
              <NBInput
                inputMode="numeric"
                value={retentionDays}
                onChange={(e) => setRetentionDays(e.target.value)}
              />
            </NBField>
          </div>
          <div className="space-y-4 border-t border-ink-700 pt-4">
            <p className="text-[13px] font-medium text-slate-400">Lokasi</p>
            <LocationInput
              lat={latitude}
              lng={longitude}
              onChange={(la, lo) => {
                setLatitude(la);
                setLongitude(lo);
              }}
            />
            <div className="grid grid-cols-2 gap-3">
              <NBField label="Latitude" hint="-90 s/d 90">
                <NBInput
                  inputMode="decimal"
                  placeholder="-6.2"
                  value={latitude}
                  onChange={(e) => setLatitude(e.target.value)}
                />
              </NBField>
              <NBField label="Longitude" hint="-180 s/d 180">
                <NBInput
                  inputMode="decimal"
                  placeholder="106.8"
                  value={longitude}
                  onChange={(e) => setLongitude(e.target.value)}
                />
              </NBField>
            </div>
          </div>
          <div className="space-y-4 border-t border-ink-700 pt-4">
            <p className="text-[13px] font-medium text-slate-400">
              Penyimpanan
            </p>
            <NBField label="Mode penyimpanan rekaman">
              <NBSelect
                value={storageMode}
                onChange={(e) => {
                  const v = e.target.value;
                  setStorageMode(v);
                  if (v === "local") setDriveFolderId("");
                }}
              >
                <option value="local">Lokal</option>
                <option value="drive">Google Drive</option>
                <option value="both">Keduanya</option>
              </NBSelect>
            </NBField>
            {/* Pilih disk HANYA bila mode memakai penyimpanan lokal.
                Bila mode Google Drive saja, rekaman ditulis ke disk
                default lalu diunggah, jadi pilihan disk disembunyikan
                supaya tidak ada dua kontrol untuk tujuan yang sama.
                Nilai recordDisk yang tersimpan tidak diubah saat
                disembunyikan, jadi data lama tetap utuh. */}
            {storageMode !== "drive" && (
              <DiskPicker
                disks={disks}
                value={recordDisk}
                onChange={setRecordDisk}
                groupNames={[]}
                cameraName={name}
              />
            )}
            {storageMode === "drive" && (
              <p className="text-xs leading-relaxed text-slate-400">
                Rekaman ditulis ke disk default lalu diunggah ke Google
                Drive.
              </p>
            )}
            {showDriveFolder && (
              <NBField
                label="Folder Google Drive tujuan"
                hint="Folder tujuan di Google Drive"
              >
                {driveFolders.length === 0 ? (
                  <p className="rounded-xl bg-ink-800 px-4 py-3 text-sm leading-relaxed text-slate-300">
                    Belum ada folder Google Drive. Tambah akun Google dulu di
                    menu Penyimpanan, lalu pilih di sini.
                  </p>
                ) : (
                  <NBSelect
                    value={driveFolderId}
                    onChange={(e) => setDriveFolderId(e.target.value)}
                  >
                    <option value="">Default (folder pertama)</option>
                    {driveFolders.map((f) => (
                      <option key={f.id} value={String(f.id)}>
                        {f.remote_name
                          ? f.remote_label || f.remote_name
                          : f.folder_name || f.folder_id}
                      </option>
                    ))}
                  </NBSelect>
                )}
              </NBField>
            )}
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
              Path RTSP, pilih satu untuk dijadikan main:
            </p>
            {/* Penanda deteksi kredensial (perintah user 2026-11-14):
                kamera tanpa password / password default tetap bisa
                ditambah. Bila terdeteksi password default, password
                itu akan disimpan bersama kamera bila Simpan diklik. */}
            {results.auth_mode === "default" && (
              <div className="rounded-xl bg-warn-500/10 p-3 text-xs leading-relaxed text-warn-200">
                Kamera terdeteksi memakai password default pabrik (bukan
                password yang diisi saat scan). Password default itu akan
                disimpan bersama kamera bila Simpan diklik. Sebaiknya
                ganti password kamera setelah ditambah.
              </div>
            )}
            {(results.auth_mode === "none" ||
              results.auth_mode === "empty") && (
              <p className="text-xs leading-relaxed text-slate-400">
                Kamera terdeteksi tanpa password (atau password kosong)
                dan akan ditambah tanpa password.
              </p>
            )}
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
            <div className="mt-5 grid gap-2.5 sm:flex sm:justify-end">
              <NBButton
                onClick={save}
                disabled={busy || !name.trim() || !picked}
                className="min-h-[48px] w-full sm:w-auto"
              >
                {busy ? "Menyimpan…" : "Simpan kamera"}
              </NBButton>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

/* Sembunyikan password di URL RTSP (perintah user 2026-11-14):
   tampilkan sebagai ****, jangan pernah tampilkan password asli di
   input. Saat simpan, **** diganti kembali dengan password asli dari
   URL semula, supaya tidak tertimpa. Bila user mengetik password baru
   (bukan ****), yang diketik itulah yang dipakai. */
function maskRtspPassword(url: string): string {
  return url.replace(/:\/\/([^:/@]+):[^@]*@/, "://$1:****@");
}
function extractRtspPassword(url: string): string | null {
  const m = url.match(/:\/\/[^:/@]+:([^@]*)@/);
  return m ? m[1] : null;
}
function unmaskRtspPassword(displayUrl: string, originalUrl: string): string {
  if (!displayUrl.includes("****")) return displayUrl;
  const pw = extractRtspPassword(originalUrl);
  if (pw === null) return displayUrl;
  return displayUrl.replace(/:\/\/([^:/@]+):\*\*\*@/, `://$1:${pw}@`);
}

function EditStreamModal({
  stream,
  driveFolders,
  disks,
  groupNames,
  onClose,
  onDone,
}: {
  stream: Stream;
  driveFolders: DriveFolder[];
  disks: Disk[];
  groupNames: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState(stream.name);
  const [isActive, setIsActive] = useState(stream.is_active);
  /* Mainstream/substream bisa diedit (perintah user 2026-11-14).
     Substream kosong = tanpa sub (frontend fallback ke main).
     Password di URL SELALU disembunyikan (****); password asli disimpan
     di ref supaya saat simpan bisa dikembalikan. */
  const origMainUrlRef = useRef(stream.main_url ?? "");
  const origSubUrlRef = useRef(stream.sub_url ?? "");
  const [mainUrl, setMainUrl] = useState(
    maskRtspPassword(stream.main_url ?? ""),
  );
  const [subUrl, setSubUrl] = useState(
    maskRtspPassword(stream.sub_url ?? ""),
  );
  const [storageMode, setStorageMode] = useState(stream.storage_mode);
  const [driveFolderId, setDriveFolderId] = useState<string>(
    stream.drive_folder_id != null ? String(stream.drive_folder_id) : "",
  );
  const [recordingEnabled, setRecordingEnabled] = useState(stream.recording_enabled);
  const [recordDisk, setRecordDisk] = useState(stream.record_disk ?? "");
  const [retentionDays, setRetentionDays] = useState(String(stream.retention_days));
  const [latitude, setLatitude] = useState(
    stream.latitude !== null ? String(stream.latitude) : "",
  );
  const [longitude, setLongitude] = useState(
    stream.longitude !== null ? String(stream.longitude) : "",
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /* Selector folder tampil HANYA bila mode penyimpanan memakai Drive
     (perintah user 2026-11-14: saat pakai Lokal, folder Google Drive
     tidak boleh tampil). Sebelumnya ada kondisi tambahan
     `stream.drive_folder_id != null` yang membuat folder tetap tampil
     bila kamera punya folder lama, walau modenya sudah Lokal. */
  const showDriveFolder =
    storageMode === "drive" || storageMode === "both";

  async function save() {
    setError("");
    /* E-S7: validasi latitude/longitude sebelum kirim. */
    const badCoord = coordError(latitude, longitude);
    if (badCoord) {
      setError(badCoord);
      return;
    }
    if (!mainUrl.trim()) {
      setError("Mainstream tidak boleh kosong.");
      return;
    }
    /* Kembalikan password asli dari **** sebelum kirim, supaya password
       tidak tertimpa mask. Bila user mengetik password baru, yang
       diketik itu yang terkirim. */
    const realMain = unmaskRtspPassword(mainUrl.trim(), origMainUrlRef.current);
    const realSub =
      subUrl.trim() === ""
        ? null
        : unmaskRtspPassword(subUrl.trim(), origSubUrlRef.current);
    /* F6.7: nama wajib isi (maks 100 karakter); mainstream wajib RTSP,
       substream boleh kosong tapi bila diisi wajib RTSP. */
    const badName = cameraNameError(name);
    if (badName) {
      setError(badName);
      return;
    }
    const badMain = rtspUrlError(realMain, "Mainstream");
    if (badMain) {
      setError(badMain);
      return;
    }
    const badSub = rtspUrlError(realSub, "Substream");
    if (badSub) {
      setError(badSub);
      return;
    }
    setBusy(true);
    try {
      const lat = latitude.trim() === "" ? null : parseFloat(latitude);
      const lon = longitude.trim() === "" ? null : parseFloat(longitude);
      await api.put(`/admin/streams/${stream.id}`, {
        name: name.trim(),
        main_url: realMain,
        sub_url: realSub,
        is_active: isActive,
        storage_mode: storageMode,
        recording_enabled: recordingEnabled,
        record_disk: recordDisk,
        retention_days: Math.min(365, Math.max(1, parseInt(retentionDays, 10) || 7)),
        latitude: lat !== null && !Number.isNaN(lat) ? lat : null,
        longitude: lon !== null && !Number.isNaN(lon) ? lon : null,
        /* E-R1: mode Lokal tidak menyimpan folder lama. */
        drive_folder_id:
          storageMode === "local" || driveFolderId === ""
            ? null
            : parseInt(driveFolderId, 10),
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
          <NBField
            label="Mainstream (RTSP)"
            hint="URL RTSP stream utama; password selalu disembunyikan (****)"
          >
            <NBInput
              value={mainUrl}
              onChange={(e) => setMainUrl(e.target.value)}
              placeholder="rtsp://…"
            />
          </NBField>
          <NBField
            label="Substream (RTSP)"
            hint="URL RTSP stream rendah; kosongkan bila kamera tidak punya substream (tampilan memakai mainstream)"
          >
            <NBInput
              value={subUrl}
              onChange={(e) => setSubUrl(e.target.value)}
              placeholder="rtsp://… (boleh kosong)"
            />
          </NBField>
          <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 text-sm text-slate-300">
            <span>Kamera aktif</span>
            <Switch
              checked={isActive}
              onChange={setIsActive}
              label="Kamera aktif"
            />
          </label>
        </div>
        {/* Bagian bawah ditata ulang (perintah user 2026-11-14) jadi
            tiga seksi: Rekaman, Lokasi, Penyimpanan. Tidak ada field
            yang dihapus atau diubah logikanya, hanya susunan dan teks
            bantuan yang dipersingkat. */}
        <div className="space-y-5 border-t border-ink-800 pt-5">
          <div className="space-y-4">
            <p className="text-[13px] font-medium text-slate-400">Rekaman</p>
            <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 text-sm text-slate-300">
              <span>Simpan rekaman ke disk</span>
              <Switch
                checked={recordingEnabled}
                onChange={setRecordingEnabled}
                label="Simpan rekaman ke disk"
              />
            </label>
            <NBField label="Retensi (hari)" hint="1-365">
              <NBInput
                inputMode="numeric"
                value={retentionDays}
                onChange={(e) => setRetentionDays(e.target.value)}
              />
            </NBField>
          </div>
          <div className="space-y-4 border-t border-ink-800 pt-5">
            <p className="text-[13px] font-medium text-slate-400">Lokasi</p>
            <LocationInput
              lat={latitude}
              lng={longitude}
              onChange={(la, lo) => {
                setLatitude(la);
                setLongitude(lo);
              }}
            />
            <div className="grid grid-cols-2 gap-3">
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
          <div className="space-y-4 border-t border-ink-800 pt-5">
            <p className="text-[13px] font-medium text-slate-400">
              Penyimpanan
            </p>
            <NBField label="Mode penyimpanan rekaman">
              <NBSelect
                value={storageMode}
                onChange={(e) => {
                  const v = e.target.value;
                  setStorageMode(v);
                  /* E-R1: ganti ke Lokal langsung reset folder lama. */
                  if (v === "local") setDriveFolderId("");
                }}
              >
                <option value="local">Lokal</option>
                <option value="drive">Google Drive</option>
                <option value="both">Keduanya</option>
              </NBSelect>
            </NBField>
            {/* Pilih disk HANYA bila mode memakai penyimpanan lokal.
                Bila mode Google Drive saja, rekaman ditulis ke disk
                default lalu diunggah, jadi pilihan disk disembunyikan
                supaya tidak ada dua kontrol untuk tujuan yang sama.
                Nilai recordDisk yang tersimpan tidak diubah saat
                disembunyikan, jadi data lama tetap utuh. */}
            {storageMode !== "drive" && (
              <DiskPicker
                disks={disks}
                value={recordDisk}
                onChange={setRecordDisk}
                groupNames={groupNames}
                cameraName={name}
              />
            )}
            {storageMode === "drive" && (
              <p className="text-xs leading-relaxed text-slate-400">
                Rekaman ditulis ke disk default lalu diunggah ke Google
                Drive.
              </p>
            )}
            {showDriveFolder && (
              <NBField
                label="Folder Google Drive tujuan"
                hint="Folder tujuan di Google Drive"
              >
                {driveFolders.length === 0 ? (
                  <p className="rounded-xl bg-ink-800 px-4 py-3 text-sm leading-relaxed text-slate-300">
                    Belum ada folder Google Drive. Tambah akun Google dulu di
                    menu Penyimpanan, lalu pilih di sini.
                  </p>
                ) : (
                  <NBSelect
                    value={driveFolderId}
                    onChange={(e) => setDriveFolderId(e.target.value)}
                  >
                    <option value="">Default (folder pertama)</option>
                    {driveFolders.map((f) => (
                      <option key={f.id} value={String(f.id)}>
                        {f.remote_name
                          ? f.remote_label || f.remote_name
                          : f.folder_name || f.folder_id}
                      </option>
                    ))}
                  </NBSelect>
                )}
              </NBField>
            )}
          </div>
        </div>
        <div className="mt-5 grid gap-2.5 sm:flex sm:justify-end">
          <NBButton onClick={save} disabled={busy || !name.trim()} className="min-h-[48px] w-full sm:w-auto">
            {busy ? "Menyimpan…" : "Simpan"}
          </NBButton>
        </div>
      </div>
    </Modal>
  );
}
