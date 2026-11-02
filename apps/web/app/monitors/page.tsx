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
  SectionTitle,
  Spinner,
} from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import type { Stream } from "../../lib/types";

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
  3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
  4: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4",
};

function loadLayouts(): MonitorLayout[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
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

/* Pratinjau mini isi layout: sel kecil per kamera + status, sisa diringkas +N. */
function MiniPreview({
  layout,
  byId,
}: {
  layout: MonitorLayout;
  byId: Map<number, Stream>;
}) {
  const cells = layout.streamIds.slice(0, 3);
  const rest = layout.streamIds.length - cells.length;
  return (
    <div className="nv-stage mt-3 grid grid-cols-4 gap-1.5" aria-hidden>
      {cells.map((id) => {
        const s = byId.get(id);
        return (
          <div
            key={id}
            className="relative aspect-video overflow-hidden rounded-lg bg-ink-800 ring-1 ring-white/10"
          >
            <span
              className={`absolute left-1.5 top-1.5 h-1.5 w-1.5 rounded-full ${s?.is_online ? "bg-ok-400" : "bg-bad-400"}`}
            />
            <span className="absolute inset-x-1.5 bottom-1 truncate text-[9px] text-neutral-500">
              {s?.name ?? "—"}
            </span>
          </div>
        );
      })}
      {rest > 0 ? (
        <div className="flex aspect-video items-center justify-center rounded-lg bg-ink-800 text-[11px] font-semibold text-neutral-300 ring-1 ring-white/10">
          +{rest}
        </div>
      ) : (
        <div className="aspect-video rounded-lg border border-dashed border-white/10" />
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
  byId,
  layoutIds,
  colsClass,
  onExpand,
}: {
  groups: { id: number; name: string; stream_ids: number[] }[] | null;
  loading: boolean;
  error: string | null;
  byId: Map<number, Stream>;
  layoutIds: number[];
  colsClass: string;
  onExpand: (s: Stream) => void;
}) {
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
      <div className="rounded-2xl bg-ink-900 px-6 py-10 text-center text-sm text-neutral-400 ring-1 ring-white/10">
        {error}
        <p className="mt-1 text-xs text-neutral-500">
          Mode grup membutuhkan akses admin.
        </p>
      </div>
    );
  }
  const inLayout = new Set(layoutIds);
  const sections = groups
    .map((g) => ({
      name: g.name,
      streams: g.stream_ids
        .filter((id) => inLayout.has(id))
        .map((id) => byId.get(id))
        .filter((s): s is Stream => !!s),
    }))
    .filter((sec) => sec.streams.length > 0);
  const grouped = new Set(sections.flatMap((sec) => sec.streams.map((s) => s.id)));
  const rest = layoutIds
    .filter((id) => !grouped.has(id))
    .map((id) => byId.get(id))
    .filter((s): s is Stream => !!s);
  if (rest.length > 0) sections.push({ name: "Tanpa grup", streams: rest });

  if (sections.length === 0) {
    return (
      <div className="rounded-2xl bg-ink-900 px-6 py-10 text-center text-sm text-neutral-400 ring-1 ring-white/10">
        Tidak ada grup kamera untuk layout ini.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      {sections.map((sec) => (
        <section key={sec.name}>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <span className="h-2 w-2 rounded-full bg-accent-400" />
            {sec.name}
            <span className="text-xs font-normal text-neutral-500">
              {sec.streams.length} kamera
            </span>
          </h2>
          <div className={`grid gap-4 ${colsClass}`}>
            {sec.streams.map((s) => (
              <CameraTile key={s.id} stream={s} onExpand={onExpand} />
            ))}
          </div>
        </section>
      ))}
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
  const [groups, setGroups] = useState<{ id: number; name: string; stream_ids: number[] }[] | null>(null);
  const [groupsError, setGroupsError] = useState<string | null>(null);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [deleting, setDeleting] = useState<MonitorLayout | null>(null);
  const gridWrapRef = useRef<HTMLDivElement>(null);

  // form state
  const [formName, setFormName] = useState("");
  const [formCols, setFormCols] = useState(2);
  const [formIds, setFormIds] = useState<number[]>([]);

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
    setEditing({ id: "", name: "", streamIds: [], cols: 2 });
  };

  const startEdit = (l: MonitorLayout) => {
    setFormName(l.name);
    setFormCols(l.cols);
    setFormIds([...l.streamIds]);
    setEditing(l);
  };

  const cancelEdit = () => setEditing(null);

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
    if (!name || formIds.length === 0) return;
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
    try {
      const gs = await api.get<{ id: number; name: string }[]>("/admin/groups");
      const full = await Promise.all(
        gs.map(async (g) => {
          const r = await api.get<{ stream_ids: number[] }>(
            `/admin/groups/${encodeURIComponent(g.name)}/camera-grants`,
          );
          return { id: g.id, name: g.name, stream_ids: r.stream_ids };
        }),
      );
      setGroups(full);
    } catch (e) {
      setGroupsError(
        e instanceof ApiError ? e.message : "Gagal memuat grup kamera",
      );
      setGroups([]);
    } finally {
      setGroupsLoading(false);
    }
  }, []);

  const toggleGroupMode = () => {
    setGroupMode((v) => {
      if (!v && groups === null) loadGroups();
      return !v;
    });
  };

  const toggleFullscreen = () => {
    const el = gridWrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      el.requestFullscreen?.().catch(() => {});
    }
  };

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
              desc={`${openStreams.length} kamera · ${openLayout.cols} kolom${groupMode ? " · mode grup" : ""}`}
              action={
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setOpenId(null)}
                    className="flex h-11 min-w-[44px] items-center justify-center rounded-xl bg-ink-900 px-3 text-base text-neutral-200 ring-1 ring-white/10 transition hover:bg-ink-800 active:scale-95"
                    aria-label="Kembali ke daftar monitor"
                  >
                    ←
                  </button>
                  <Button
                    variant={groupMode ? "primary" : "subtle"}
                    onClick={toggleGroupMode}
                    aria-pressed={groupMode}
                  >
                    Grup
                  </Button>
                  <button
                    onClick={toggleFullscreen}
                    className="flex h-11 items-center gap-2 rounded-xl bg-ink-900 px-4 text-sm font-medium text-neutral-200 ring-1 ring-white/10 transition hover:bg-ink-800 active:scale-95"
                    aria-label="Layar penuh"
                    title="Layar penuh"
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
                    <span className="hidden sm:inline">Penuh</span>
                  </button>
                </div>
              }
            />
            <div ref={gridWrapRef} className="bg-ink-950">
              {fetching ? (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div
                      key={i}
                      className="aspect-video animate-pulse rounded-2xl bg-ink-800 motion-reduce:animate-none"
                    />
                  ))}
                </div>
              ) : openStreams.length === 0 ? (
                <div className="rounded-2xl bg-ink-900 p-8 text-center text-sm text-neutral-400 ring-1 ring-white/10">
                  Tidak ada kamera yang cocok — mungkin kamera sudah dihapus.
                </div>
              ) : groupMode ? (
                <GroupSections
                  groups={groups}
                  loading={groupsLoading}
                  error={groupsError}
                  byId={byId}
                  layoutIds={openLayout.streamIds}
                  colsClass={COLS_CLASS[openLayout.cols] ?? COLS_CLASS[2]}
                  onExpand={setFocus}
                />
              ) : (
                <div
                  className={`grid gap-4 ${COLS_CLASS[openLayout.cols] ?? COLS_CLASS[2]}`}
                >
                  {openStreams.map((s) => (
                    <CameraTile key={s.id} stream={s} onExpand={setFocus} />
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
            <div className="rounded-2xl bg-ink-900 p-5 ring-1 ring-white/10">
              <label className="mb-1.5 block text-sm font-medium text-neutral-300">
                Nama monitor
              </label>
              <input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="cth. Lantai 1"
                className="mb-5 h-11 w-full rounded-xl bg-ink-800 px-3.5 text-base text-white ring-1 ring-white/10 outline-none placeholder:text-neutral-500 focus:ring-2 focus:ring-accent-500"
              />

              <div className="mb-1.5 text-sm font-medium text-neutral-300">
                Jumlah kolom
              </div>
              <div className="mb-5 flex gap-2">
                {[1, 2, 3, 4].map((c) => (
                  <button
                    key={c}
                    onClick={() => setFormCols(c)}
                    aria-pressed={formCols === c}
                    className={`flex h-11 min-w-[52px] items-center justify-center rounded-xl text-sm font-semibold transition active:scale-95 ${
                      formCols === c
                        ? "bg-accent-600 text-onaccent"
                        : "bg-ink-800 text-neutral-300 ring-1 ring-white/10 hover:bg-ink-700"
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>

              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-sm font-medium text-neutral-300">
                  Pilih kamera ({formIds.length})
                </span>
                <span className="text-[11px] text-neutral-500">
                  Urutan bisa digeser
                </span>
              </div>
              <div className="mb-5 flex max-h-72 flex-col gap-1.5 overflow-y-auto rounded-xl bg-ink-950/60 p-2 ring-1 ring-white/5">
                {[...streams]
                  .sort((a, b) => {
                    const ia = formIds.indexOf(a.id);
                    const ib = formIds.indexOf(b.id);
                    if (ia >= 0 && ib >= 0) return ia - ib;
                    if (ia >= 0) return -1;
                    if (ib >= 0) return 1;
                    return a.name.localeCompare(b.name);
                  })
                  .map((s) => {
                  const checked = formIds.includes(s.id);
                  return (
                    <label
                      key={s.id}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl px-3.5 py-3 transition active:scale-[0.99] ${
                        checked
                          ? "bg-accent-600/15 ring-1 ring-accent-500/40"
                          : "hover:bg-white/5"
                      }`}
                    >
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
                      {checked && (
                        <span className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.preventDefault();
                              moveId(s.id, -1);
                            }}
                            disabled={formIds.indexOf(s.id) === 0}
                            className="flex h-11 w-11 items-center justify-center rounded-lg bg-white/5 text-neutral-300 transition hover:bg-white/10 active:scale-95 disabled:opacity-30"
                            aria-label={`Geser ${s.name} ke atas`}
                          >
                            ↑
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.preventDefault();
                              moveId(s.id, 1);
                            }}
                            disabled={formIds.indexOf(s.id) === formIds.length - 1}
                            className="flex h-11 w-11 items-center justify-center rounded-lg bg-white/5 text-neutral-300 transition hover:bg-white/10 active:scale-95 disabled:opacity-30"
                            aria-label={`Geser ${s.name} ke bawah`}
                          >
                            ↓
                          </button>
                        </span>
                      )}
                    </label>
                  );
                })}
                {streams.length === 0 && !fetching && (
                  <div className="p-3 text-center text-xs text-neutral-500">
                    Belum ada kamera.
                  </div>
                )}
              </div>

              <div className="flex gap-2">
                <Button variant="ghost" onClick={cancelEdit} className="flex-1">
                  Batal
                </Button>
                <Button
                  onClick={saveForm}
                  disabled={!formName.trim() || formIds.length === 0}
                  className="flex-1"
                >
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
                  Baru
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
              <div className="flex flex-col items-center gap-3 rounded-2xl bg-ink-900 px-6 py-16 text-center ring-1 ring-white/10">
                <svg
                  width="40"
                  height="40"
                  viewBox="0 0 24 24"
                  fill="none"
                  className="text-neutral-600"
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
                  Buat tata letak kisi kamera favoritmu — tersimpan di perangkat
                  ini.
                </p>
                <Button onClick={startCreate} className="mt-1">
                  Buat monitor pertama
                </Button>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {layouts.map((l) => {
                  const expanded = expandedId === l.id;
                  const count = l.streamIds.length;
                  const onlineN = l.streamIds.filter((id) => byId.get(id)?.is_online).length;
                  return (
                    <div
                      key={l.id}
                      className="overflow-hidden rounded-2xl bg-ink-900 ring-1 ring-white/10"
                    >
                      {/* Baris ringkasan + pratinjau — collapsed-first di mobile */}
                      <button
                        onClick={() => setExpandedId(expanded ? null : l.id)}
                        aria-expanded={expanded}
                        className="block w-full px-4 py-4 text-left transition hover:bg-white/[0.03] active:scale-[0.995] sm:px-5"
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
                      {/* Aksi — hanya setelah expand */}
                      {expanded && (
                        <div className="flex gap-2 border-t border-white/10 px-4 py-3 sm:px-5">
                          <Button onClick={() => setOpenId(l.id)} className="flex-1">
                            Buka
                          </Button>
                          <Button variant="ghost" onClick={() => startEdit(l)} className="flex-1">
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

      <FocusModal stream={focus} onClose={() => setFocus(null)} />

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
