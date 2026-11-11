"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "../../components/AppShell";
import { CameraTile } from "../../components/CameraTile";
import { FocusModal } from "../../components/FocusModal";
import {
  Button,
  ConfirmModal,
  ErrorBox,
  GridIcon,
  SectionTitle,
  Spinner,
} from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { isAdminRole, useAuth } from "../../lib/auth";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import { useFullscreen } from "../../hooks/useFullscreen";
import type { RefObject } from "react";
import type { AdConfig, Stream } from "../../lib/types";

/* Monitor kustom: tata letak kisi tersimpan (pengganti custom-monitor v2.0).
   Disimpan di localStorage key "nv_monitors". */

const LS_KEY = "nv_monitors";

interface MonitorLayout {
  id: string;
  name: string;
  streamIds: number[];
  cols: number;
}

const COLS_CLASS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-1 sm:grid-cols-2",
  3: "grid-cols-1 sm:grid-cols-2 md:grid-cols-3",
  4: "grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4",
};

const MINI_COLS_CLASS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  3: "grid-cols-3",
  4: "grid-cols-4",
};

function loadLayouts(): MonitorLayout[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    /* D-R1: validasi per item; satu entri rusak dibuang, bukan membuat
       seluruh halaman crash. */
    return parsed.filter(
      (item): item is MonitorLayout =>
        !!item &&
        typeof item === "object" &&
        typeof item.id === "string" &&
        typeof item.name === "string" &&
        Array.isArray(item.streamIds) &&
        item.streamIds.every((n: unknown) => typeof n === "number") &&
        typeof item.cols === "number",
    );
  } catch {
    return [];
  }
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      className={`shrink-0 text-neutral-400 transition-transform ${open ? "rotate-180" : ""}`}
      aria-hidden
    >
      <path
        d="M4 6l4 4 4-4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* Pratinjau mini isi layout: sel kecil per kamera + status, sisa diringkas +N.
   Jumlah kolom mengikuti cols layout; tidak ada sel kosong. */
function MiniPreview({
  layout,
  byId,
}: {
  layout: MonitorLayout;
  byId: Map<number, Stream>;
}) {
  const streamIds = Array.isArray(layout.streamIds) ? layout.streamIds : [];
  const total = streamIds.length;
  const maxCells = Math.max(1, layout.cols || 2);
  /* D-R2: pratinjau 1 kolom dengan >1 kamera harus menampilkan kamera:
     minimal 1 sel, bukan 0. */
  const shownCount = total > maxCells ? Math.max(1, maxCells - 1) : total;
  const cells = streamIds.slice(0, shownCount);
  const rest = total - cells.length;
  const names = streamIds
    .map((id) => byId.get(id)?.name ?? "Tanpa nama")
    .join(", ");
  return (
    <div
      className={`nv-stage mt-3 grid gap-1.5 ${MINI_COLS_CLASS[layout.cols] ?? MINI_COLS_CLASS[2]}`}
      aria-hidden
      title={`${layout.name}: ${total} kamera${names ? `, ${names}` : ""}`}
    >
      {cells.map((id) => {
        const s = byId.get(id);
        return (
          <div
            key={id}
            title={s?.name ?? "Tanpa nama"}
            className="relative aspect-video overflow-hidden rounded-lg bg-ink-800"
          >
            <span
              className={`absolute left-1.5 top-1.5 h-1.5 w-1.5 rounded-full ${s?.is_online ? "bg-ok-400" : "bg-bad-400"}`}
            />
            <span className="absolute inset-x-1.5 bottom-1 truncate text-xs text-neutral-400">
              {s?.name ?? "Tanpa nama"}
            </span>
          </div>
        );
      })}
      {rest > 0 && (
        <div
          title={`+${rest} kamera lagi`}
          className="flex aspect-video items-center justify-center rounded-lg bg-ink-800 text-sm font-semibold text-neutral-300"
        >
          +{rest}
        </div>
      )}
    </div>
  );
}

/* Mode grup: kamera dikelompokkan per grup kamera (admin).
   Hanya grup yang punya kamera di layout ini yang ditampilkan;
   kamera tanpa grup masuk "Tanpa grup". */
function GroupSections({
  groups,
  loading,
  error,
  warning,
  byId,
  layoutIds,
  colsClass,
  onExpand,
  onRetry,
  ad,
}: {
  groups: { id: number; name: string; stream_ids: number[] }[] | null;
  loading: boolean;
  error: string | null;
  warning?: string | null;
  byId: Map<number, Stream>;
  layoutIds: number[];
  colsClass: string;
  onExpand: (s: Stream) => void;
  onRetry: () => void;
  ad?: AdConfig | null;
}) {
  const [openSections, setOpenSections] = useState<Set<number>>(new Set());
  /* D-S7: seksi grup terbuka secara default (kunci = daftar id seksi,
     supaya tidak dibuka ulang tiap render/status berubah). */
  const openedForRef = useRef("");
  const toggleSection = (id: number) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  /* D-S7: buka semua seksi secara default. Dihitung dari groups +
     layoutIds (tanpa byId) supaya hook ini bisa ditaruh sebelum
     early-return loading/error. */
  const sectionKey = useMemo(() => {
    if (!groups) return "";
    const inLayout = new Set(layoutIds);
    const ids = groups
      .filter((g) => g.stream_ids.some((id) => inLayout.has(id)))
      .map((g) => g.id);
    if (
      layoutIds.some((id) => !groups.some((g) => g.stream_ids.includes(id)))
    ) {
      ids.push(0);
    }
    return ids.join(",");
  }, [groups, layoutIds]);
  useEffect(() => {
    if (!sectionKey) return;
    if (openedForRef.current === sectionKey) return;
    openedForRef.current = sectionKey;
    setOpenSections(new Set(sectionKey.split(",").map(Number)));
  }, [sectionKey]);
  if (loading || groups === null) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-neutral-400">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-ink-700 border-t-accent-400 motion-reduce:animate-none" />
        Memuat grup…
      </div>
    );
  }
  if (error) {
    return (
      <div className="nv-panel-modern flex flex-col items-center gap-3 px-6 py-10 text-center text-sm text-neutral-400">
        <p>{error}</p>
        <p className="text-xs text-neutral-400">
          Mode grup membutuhkan akses admin.
        </p>
        <Button variant="subtle" onClick={onRetry}>
          Coba lagi
        </Button>
      </div>
    );
  }
  const inLayout = new Set(layoutIds);
  /* D-S8: dedup lintas grup, satu tile per kamera (grup pertama menang). */
  const seen = new Set<number>();
  const sections = groups
    .map((g) => ({
      id: g.id,
      name: g.name,
      streams: g.stream_ids
        .filter((id) => inLayout.has(id))
        .map((id) => byId.get(id))
        .filter((s): s is Stream => !!s)
        .filter((s) => {
          if (seen.has(s.id)) return false;
          seen.add(s.id);
          return true;
        }),
    }))
    .filter((sec) => sec.streams.length > 0);
  const grouped = new Set(sections.flatMap((sec) => sec.streams.map((s) => s.id)));
  const rest = layoutIds
    .filter((id) => !grouped.has(id))
    .map((id) => byId.get(id))
    .filter((s): s is Stream => !!s);
  if (rest.length > 0)
    sections.push({ id: 0, name: "Tanpa grup", streams: rest });

  if (sections.length === 0) {
    return (
      <div className="nv-panel-modern px-6 py-10 text-center text-sm text-neutral-400">
        Tidak ada grup kamera untuk layout ini.
      </div>
    );
  }
  const allOpen = sections.every((sec) => openSections.has(sec.id));
  return (
    <div className="flex flex-col gap-6">
      {warning && (
        <div className="nv-panel-modern px-4 py-3 text-xs leading-relaxed text-neutral-400">
          {warning}
        </div>
      )}
      <div className="flex justify-end">
        <Button
          variant="subtle"
          onClick={() =>
            setOpenSections(
              allOpen
                ? new Set()
                : new Set(sections.map((sec) => sec.id)),
            )
          }
          className="min-h-11 px-3 text-xs"
        >
          {allOpen ? "Tutup semua" : "Buka semua"}
        </Button>
      </div>
      {sections.map((sec) => {
        const open = openSections.has(sec.id);
        return (
          <section key={sec.id}>
            <button
              type="button"
              onClick={() => toggleSection(sec.id)}
              aria-expanded={open}
              className="mb-3 flex min-h-[44px] w-full cursor-pointer items-center gap-2 text-left active:scale-[0.99]"
            >
              <span className="h-2 w-2 shrink-0 rounded-full bg-accent-400" />
              <span className="min-w-0 flex-1 truncate text-sm font-semibold text-white">
                {sec.name}
              </span>
              <span className="shrink-0 text-xs font-normal text-neutral-400">
                {sec.streams.length} kamera
              </span>
              <Chevron open={open} />
            </button>
            {open && (
              <div className={`grid gap-4 ${colsClass}`}>
                {sec.streams.map((s) => (
                  <CameraTile key={s.id} stream={s} onExpand={onExpand} ad={ad} />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

export default function MonitorsPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const { status } = useCameraStatus();

  const [streams, setStreams] = useState<Stream[]>([]);
  const [layouts, setLayouts] = useState<MonitorLayout[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<MonitorLayout | null>(null);
  const [focus, setFocus] = useState<Stream | null>(null);
  const [groupMode, setGroupMode] = useState(false);
  const [ad, setAd] = useState<AdConfig | null>(null);
  const [groups, setGroups] = useState<{ id: number; name: string; stream_ids: number[] }[] | null>(null);
  const [groupsError, setGroupsError] = useState<string | null>(null);
  const [groupsWarning, setGroupsWarning] = useState<string | null>(null);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [deleting, setDeleting] = useState<MonitorLayout | null>(null);
  const gridWrapRef = useRef<HTMLDivElement>(null);
  /* D-S9: fullscreen lewat hook (fallback webkit iOS), bukan
     requestFullscreen mentah. */
  const { fs: isFullscreen, toggle: toggleFullscreen } = useFullscreen(
    gridWrapRef as RefObject<HTMLElement | null>,
  );

  // form state
  const [formName, setFormName] = useState("");
  const [formCols, setFormCols] = useState(2);
  const [formIds, setFormIds] = useState<number[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const data = await api.get<Stream[]>("/streams");
      setStreams(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat kamera");
    } finally {
      setFetching(false);
    }
  }, []);

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
      return;
    }
    if (user) {
      load();
      setLayouts(loadLayouts());
    }
  }, [loading, user, router, load]);

  /* Config iklan: sekali per halaman, dipakai semua tile. */
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    api
      .get<AdConfig>("/ad-config")
      .then((c) => {
        if (!cancelled) setAd(c);
      })
      .catch(() => {
        /* iklan opsional; abaikan bila gagal */
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  const persist = (next: MonitorLayout[]) => {
    setLayouts(next);
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(next));
    } catch {
      /* abaikan */
    }
  };

  const merged = useMemo(
    () =>
      streams.map((s) =>
        status.has(s.id) ? { ...s, is_online: status.get(s.id)! } : s,
      ),
    [streams, status],
  );

  const byId = useMemo(() => new Map(merged.map((s) => [s.id, s])), [merged]);

  const startCreate = () => {
    setFormName("");
    setFormCols(2);
    setFormIds([]);
    setFormError(null);
    setEditing({ id: "", name: "", streamIds: [], cols: 2 });
  };

  const startEdit = (l: MonitorLayout) => {
    setFormName(l.name);
    setFormCols(l.cols);
    setFormIds([...l.streamIds]);
    setFormError(null);
    setEditing(l);
  };

  const cancelEdit = () => {
    setEditing(null);
    setFormError(null);
  };

  const toggleId = (id: number) => {
    setFormIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  /* Geser urutan kamera terpilih (atas/bawah). */
  const moveId = (id: number, dir: -1 | 1) => {
    setFormIds((prev) => {
      const i = prev.indexOf(id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const saveForm = () => {
    const name = formName.trim();
    if (!name && formIds.length === 0) {
      setFormError("Isi nama monitor dan pilih minimal satu kamera.");
      return;
    }
    if (!name) {
      setFormError("Isi nama monitor.");
      return;
    }
    if (formIds.length === 0) {
      setFormError("Pilih minimal satu kamera.");
      return;
    }
    setFormError(null);
    const cols = Math.min(4, Math.max(1, formCols));
    if (editing && editing.id) {
      persist(
        layouts.map((l) =>
          l.id === editing.id
            ? { ...l, name, cols, streamIds: formIds }
            : l,
        ),
      );
    } else {
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `m-${Date.now()}`;
      persist([...layouts, { id, name, cols, streamIds: formIds }]);
    }
    setEditing(null);
  };

  const removeLayout = (id: string) => {
    persist(layouts.filter((l) => l.id !== id));
    if (openId === id) setOpenId(null);
  };

  const loadGroups = useCallback(async () => {
    setGroupsLoading(true);
    setGroupsError(null);
    setGroupsWarning(null);
    try {
      const gs = await api.get<{ id: number; name: string }[]>("/admin/groups");
      /* D-R4: satu grup gagal jangan menggugurkan semua (allSettled). */
      const results = await Promise.allSettled(
        gs.map(async (g) => {
          const r = await api.get<{ stream_ids: number[] }>(
            `/admin/groups/${encodeURIComponent(g.name)}/camera-grants`,
          );
          return { id: g.id, name: g.name, stream_ids: r.stream_ids };
        }),
      );
      const full = results
        .filter(
          (
            r,
          ): r is PromiseFulfilledResult<{
            id: number;
            name: string;
            stream_ids: number[];
          }> => r.status === "fulfilled",
        )
        .map((r) => r.value);
      const failedN = results.length - full.length;
      if (full.length === 0 && results.length > 0) {
        const first = results.find((r) => r.status === "rejected") as
          | PromiseRejectedResult
          | undefined;
        throw new Error(
          first?.reason instanceof ApiError
            ? first.reason.message
            : "Gagal memuat grup kamera",
        );
      }
      setGroups(full);
      if (failedN > 0) {
        /* Peringatan non-blocking: grup yang berhasil tetap tampil. */
        setGroupsWarning(
          `${failedN} grup gagal dimuat, menampilkan yang berhasil.`,
        );
      }
    } catch (e) {
      setGroupsError(
        e instanceof ApiError ? e.message : "Gagal memuat grup kamera",
      );
      /* groups tetap null supaya gagal bisa coba lagi (toggle / tombol). */
    } finally {
      setGroupsLoading(false);
    }
  }, []);

  /* D-R4: jangan panggil loadGroups di dalam fungsi updater setState
     (React boleh memanggil updater dua kali di StrictMode). */
  const toggleGroupMode = () => {
    if (!groupMode && groups === null) loadGroups();
    setGroupMode((v) => !v);
  };

  /* D-S9: toggleFullscreen kini dari hook useFullscreen (lihat atas). */

  const openLayout = layouts.find((l) => l.id === openId) ?? null;
  const openStreams = openLayout
    ? openLayout.streamIds
        .map((id) => byId.get(id))
        .filter((s): s is Stream => !!s)
    : [];

  if (loading || (!user && !loading)) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-ink-950">
        <Spinner />
      </div>
    );
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-4 py-5 md:px-6 md:py-7">
        {error && (
          <div className="mb-4">
            <ErrorBox message={error} />
          </div>
        )}

        {openLayout ? (
          /* ===== Tampilan layout terbuka ===== */
          <div>
            <SectionTitle
              title={openLayout.name}
              desc={`${openStreams.length} kamera · ${openLayout.cols} kolom${groupMode ? " · Mode grup" : ""}`}
              action={
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="subtle"
                    onClick={() => setOpenId(null)}
                    aria-label="Kembali ke daftar monitor"
                  >
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                      <path
                        d="M10 3L5 8l5 5"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    Kembali
                  </Button>
                  <Button
                    variant="subtle"
                    onClick={() => {
                      const l = openLayout;
                      setOpenId(null);
                      startEdit(l);
                    }}
                  >
                    Ubah
                  </Button>
                  {/* D-S10: Mode grup hanya admin/super_admin; user/guest
                      selalu 403 di /admin/groups. */}
                  {isAdminRole(user?.role) && (
                    <Button
                      variant={groupMode ? "primary" : "subtle"}
                      onClick={toggleGroupMode}
                      aria-pressed={groupMode}
                    >
                      Mode grup
                    </Button>
                  )}
                  <Button
                    variant="subtle"
                    onClick={toggleFullscreen}
                    aria-label={isFullscreen ? "Keluar layar penuh" : "Layar penuh"}
                    title={isFullscreen ? "Keluar layar penuh" : "Layar penuh"}
                  >
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                      <path
                        d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    {isFullscreen ? "Keluar layar penuh" : "Layar penuh"}
                  </Button>
                </div>
              }
            />
            <div
              ref={gridWrapRef}
              className="relative bg-transparent fullscreen:bg-ink-950"
            >
              {isFullscreen && (
                <div className="absolute right-3 top-3 z-10">
                  <Button variant="subtle" onClick={toggleFullscreen}>
                    Keluar layar penuh
                  </Button>
                </div>
              )}
              {fetching ? (
                <div
                  className={`grid gap-4 ${COLS_CLASS[openLayout.cols] ?? COLS_CLASS[2]}`}
                >
                  {Array.from({
                    length: Math.min(Math.max(openLayout.streamIds.length, 1), 8),
                  }).map((_, i) => (
                    <div
                      key={i}
                      className="aspect-video animate-pulse rounded-2xl bg-ink-800 motion-reduce:animate-none"
                    />
                  ))}
                </div>
              ) : openStreams.length === 0 ? (
                <div className="nv-panel-modern p-8 text-center text-sm text-neutral-400">
                  Tidak ada kamera yang cocok, mungkin kamera sudah dihapus.
                </div>
              ) : groupMode ? (
                <GroupSections
                  groups={groups}
                  loading={groupsLoading}
                  error={groupsError}
                  warning={groupsWarning}
                  byId={byId}
                  layoutIds={openLayout.streamIds}
                  colsClass={COLS_CLASS[openLayout.cols] ?? COLS_CLASS[2]}
                  onExpand={setFocus}
                  onRetry={loadGroups}
                  ad={ad}
                />
              ) : (
                <div
                  className={`grid gap-4 ${COLS_CLASS[openLayout.cols] ?? COLS_CLASS[2]}`}
                >
                  {openStreams.map((s) => (
                    <CameraTile key={s.id} stream={s} onExpand={setFocus} ad={ad} />
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : editing ? (
          /* ===== Form buat/ubah ===== */
          <div className="mx-auto max-w-2xl">
            <SectionTitle
              title={editing.id ? "Ubah monitor" : "Monitor baru"}
            />
            <div className="nv-panel-modern p-5">
              <label className="mb-1.5 block text-sm font-medium text-neutral-300">
                Nama monitor
              </label>
              <input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="cth. Lantai 1"
                className="mb-5 h-11 w-full rounded-xl bg-ink-800 px-3.5 text-base text-white shadow-sm outline-none placeholder:text-neutral-400 focus:ring-2 focus:ring-accent-500/30"
              />

              <div className="mb-5 flex flex-wrap items-center gap-2">
                <span className="flex min-h-11 items-center text-sm font-medium text-neutral-300">
                  Kolom:
                </span>
                {[1, 2, 3, 4].map((c) => (
                  <button
                    key={c}
                    onClick={() => setFormCols(c)}
                    aria-pressed={formCols === c}
                    aria-label={`${c} kolom`}
                    title={`${c} kolom`}
                    className={`flex h-11 min-w-[52px] items-center justify-center rounded-full text-sm font-semibold transition active:scale-95 ${
                      formCols === c
                        ? "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                        : "bg-ink-800 text-neutral-300 shadow-sm hover:bg-ink-700"
                    }`}
                  >
                    <GridIcon cols={c} />
                  </button>
                ))}
              </div>

              <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-neutral-300">
                    Pilih kamera ({formIds.length})
                  </span>
                  <Button
                    type="button"
                    variant="subtle"
                    onClick={() => setFormIds(streams.map((s) => s.id))}
                    disabled={streams.length === 0 || formIds.length === streams.length}
                    className="min-h-11 px-3 text-xs"
                  >
                    Pilih semua
                  </Button>
                  <Button
                    type="button"
                    variant="subtle"
                    onClick={() => setFormIds([])}
                    disabled={formIds.length === 0}
                    className="min-h-11 px-3 text-xs"
                  >
                    Bersihkan
                  </Button>
                </span>
                <span className="text-[11px] text-neutral-400">
                  Urutan bisa digeser
                </span>
              </div>
              <div className="mb-5 flex max-h-72 flex-col gap-1.5 overflow-y-auto rounded-xl bg-ink-800 p-2 shadow-sm">
                {/* D-R3: titik status memakai merged (override WebSocket),
                    bukan snapshot API lama. */}
                {merged.map((s) => {
                  const checked = formIds.includes(s.id);
                  return (
                    <div
                      key={s.id}
                      className={`flex items-center gap-3 rounded-xl px-3.5 py-3 transition active:scale-[0.99] ${
                        checked
                          ? "bg-accent-600/15"
                          : "hover:bg-ink-700"
                      }`}
                    >
                      <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleId(s.id)}
                          className="h-5 w-5 shrink-0 accent-accent-500"
                        />
                        <span
                          className={`h-2 w-2 shrink-0 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                        />
                        <span className="min-w-0 flex-1 truncate text-sm text-neutral-200">
                          {s.name}
                        </span>
                      </label>
                      {checked && (
                        <span className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            onClick={() => moveId(s.id, -1)}
                            disabled={formIds.indexOf(s.id) === 0}
                            className="flex h-11 w-11 items-center justify-center rounded-lg bg-ink-700 text-neutral-300 transition hover:bg-ink-600 active:scale-95 disabled:opacity-30"
                            aria-label={`Geser ${s.name} ke atas`}
                          >
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                              <path
                                d="M8 13V3M4 7l4-4 4 4"
                                stroke="currentColor"
                                strokeWidth="1.8"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              />
                            </svg>
                          </button>
                          <button
                            type="button"
                            onClick={() => moveId(s.id, 1)}
                            disabled={formIds.indexOf(s.id) === formIds.length - 1}
                            className="flex h-11 w-11 items-center justify-center rounded-lg bg-ink-700 text-neutral-300 transition hover:bg-ink-600 active:scale-95 disabled:opacity-30"
                            aria-label={`Geser ${s.name} ke bawah`}
                          >
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                              <path
                                d="M8 3v10M4 9l4 4 4-4"
                                stroke="currentColor"
                                strokeWidth="1.8"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              />
                            </svg>
                          </button>
                        </span>
                      )}
                    </div>
                  );
                })}
                {streams.length === 0 && !fetching && (
                  <div className="p-3 text-center text-xs text-neutral-400">
                    Belum ada kamera.
                  </div>
                )}
              </div>

              {formError && (
                <div className="mb-4">
                  <ErrorBox message={formError} />
                </div>
              )}
              <div className="flex gap-2">
                <Button variant="subtle" onClick={cancelEdit} className="flex-1">
                  Batal
                </Button>
                <Button onClick={saveForm} className="flex-1">
                  Simpan
                </Button>
              </div>
            </div>
          </div>
        ) : (
          /* ===== Daftar layout ===== */
          <div>
            <SectionTitle
              title="Monitor tersimpan"
              action={
                <Button onClick={startCreate}>
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
                    <path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                  Monitor baru
                </Button>
              }
            />

            {fetching && layouts.length === 0 ? (
              <div className="flex flex-col gap-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-24 animate-pulse rounded-2xl bg-ink-800 motion-reduce:animate-none"
                  />
                ))}
              </div>
            ) : layouts.length === 0 ? (
              <div className="nv-panel-modern flex flex-col items-center gap-3 px-6 py-16 text-center">
                <svg
                  width="40"
                  height="40"
                  viewBox="0 0 24 24"
                  fill="none"
                  className="text-neutral-400"
                  aria-hidden
                >
                  <path
                    d="M3 5.5A1.5 1.5 0 014.5 4h15A1.5 1.5 0 0121 5.5v13a1.5 1.5 0 01-1.5 1.5h-15A1.5 1.5 0 013 18.5v-13z"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <path d="M3 9.5h18M9.5 9.5V20" stroke="currentColor" strokeWidth="1.6" />
                </svg>
                <div className="text-sm font-medium text-white">
                  Belum ada monitor tersimpan
                </div>
                <p className="max-w-xs text-xs leading-relaxed text-neutral-400">
                  Buat tata letak kisi kamera favoritmu, tersimpan di perangkat
                  ini.
                </p>
                <Button onClick={startCreate} className="mt-1">
                  Monitor baru
                </Button>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {layouts.map((l) => {
                  const expanded = expandedId === l.id;
                  const existing = l.streamIds
                    .map((id) => byId.get(id))
                    .filter((s): s is Stream => !!s);
                  const count = existing.length;
                  const onlineN = existing.filter((s) => s.is_online).length;
                  return (
                    <div
                      key={l.id}
                      className="nv-panel-modern overflow-hidden"
                    >
                      {/* Baris ringkasan + pratinjau, collapsed-first di mobile */}
                      <button
                        onClick={() => setExpandedId(expanded ? null : l.id)}
                        aria-expanded={expanded}
                        className="block w-full px-4 py-4 text-left transition hover:bg-ink-800 active:scale-[0.995] sm:px-5"
                      >
                        <div className="flex items-center gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-base font-semibold text-white">
                              {l.name}
                            </div>
                            <div className="mt-0.5 text-xs text-neutral-400">
                              {count} kamera ·{" "}
                              <span className="text-ok-400">{onlineN} online</span>{" "}
                              · {l.cols} kolom
                            </div>
                          </div>
                          <Chevron open={expanded} />
                        </div>
                        <MiniPreview layout={l} byId={byId} />
                      </button>
                      {/* Aksi, hanya setelah expand */}
                      {expanded && (
                        <div className="flex gap-2 border-t border-ink-800 px-4 py-3 sm:px-5">
                          <Button onClick={() => setOpenId(l.id)} className="flex-1">
                            Buka
                          </Button>
                          <Button variant="subtle" onClick={() => startEdit(l)} className="flex-1">
                            Ubah
                          </Button>
                          <Button variant="danger" onClick={() => setDeleting(l)} className="flex-1">
                            Hapus
                          </Button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      <FocusModal stream={focus} onClose={() => setFocus(null)} ad={ad} />

      {deleting && (
        <ConfirmModal
          title="Hapus monitor"
          message={`Hapus monitor "${deleting.name}"?`}
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            removeLayout(deleting.id);
            setDeleting(null);
          }}
        />
      )}
    </AppShell>
  );
}
