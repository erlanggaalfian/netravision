"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "../../components/AppShell";
import { CameraTile } from "../../components/CameraTile";
import { FocusModal } from "../../components/FocusModal";
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
  4: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
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

  // form state
  const [formName, setFormName] = useState("");
  const [formCols, setFormCols] = useState(2);
  const [formIds, setFormIds] = useState<Set<number>>(new Set());

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
    setFormIds(new Set());
    setEditing({ id: "", name: "", streamIds: [], cols: 2 });
  };

  const startEdit = (l: MonitorLayout) => {
    setFormName(l.name);
    setFormCols(l.cols);
    setFormIds(new Set(l.streamIds));
    setEditing(l);
  };

  const cancelEdit = () => setEditing(null);

  const toggleId = (id: number) => {
    setFormIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const saveForm = () => {
    const name = formName.trim();
    if (!name || formIds.size === 0) return;
    const cols = Math.min(4, Math.max(1, formCols));
    if (editing && editing.id) {
      persist(
        layouts.map((l) =>
          l.id === editing.id
            ? { ...l, name, cols, streamIds: [...formIds] }
            : l,
        ),
      );
    } else {
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `m-${Date.now()}`;
      persist([...layouts, { id, name, cols, streamIds: [...formIds] }]);
    }
    setEditing(null);
  };

  const removeLayout = (id: string) => {
    persist(layouts.filter((l) => l.id !== id));
    if (openId === id) setOpenId(null);
  };

  const openLayout = layouts.find((l) => l.id === openId) ?? null;
  const openStreams = openLayout
    ? openLayout.streamIds
        .map((id) => byId.get(id))
        .filter((s): s is Stream => !!s)
    : [];

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl p-4">
        {error && (
          <div className="mb-3 rounded-lg bg-bad-400/10 px-3 py-2 text-xs text-bad-400 ring-1 ring-bad-400/30">
            {error}
          </div>
        )}

        {openLayout ? (
          /* ===== Tampilan layout terbuka ===== */
          <div>
            <div className="mb-3 flex items-center gap-3">
              <button
                onClick={() => setOpenId(null)}
                className="flex h-10 min-w-[44px] items-center justify-center rounded-lg bg-white/5 px-3 text-sm text-neutral-200 transition hover:bg-white/10 active:scale-95"
                aria-label="Kembali ke daftar monitor"
              >
                ←
              </button>
              <div className="min-w-0">
                <h1 className="truncate text-base font-bold text-white">
                  {openLayout.name}
                </h1>
                <p className="text-xs text-neutral-400">
                  {openStreams.length} kamera · {openLayout.cols} kolom
                </p>
              </div>
            </div>
            {fetching ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div
                    key={i}
                    className="aspect-video animate-pulse rounded-lg bg-ink-800"
                  />
                ))}
              </div>
            ) : openStreams.length === 0 ? (
              <div className="rounded-xl bg-ink-900 p-8 text-center text-sm text-neutral-400 ring-1 ring-white/10">
                Tidak ada kamera yang cocok — mungkin kamera sudah dihapus.
              </div>
            ) : (
              <div
                className={`grid gap-3 ${COLS_CLASS[openLayout.cols] ?? COLS_CLASS[2]}`}
              >
                {openStreams.map((s) => (
                  <CameraTile
                    key={s.id}
                    stream={s}
                    onExpand={setFocus}
                  />
                ))}
              </div>
            )}
          </div>
        ) : editing ? (
          /* ===== Form buat/ubah ===== */
          <div className="mx-auto max-w-2xl">
            <h1 className="mb-4 text-base font-bold text-white">
              {editing.id ? "Ubah monitor" : "Monitor baru"}
            </h1>
            <div className="rounded-xl bg-ink-900 p-4 ring-1 ring-white/10">
              <label className="mb-1 block text-xs font-medium text-neutral-300">
                Nama monitor
              </label>
              <input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="cth. Lantai 1"
                className="mb-4 w-full rounded-lg bg-ink-800 px-3 py-2.5 text-sm text-white ring-1 ring-white/10 outline-none placeholder:text-neutral-500 focus:ring-accent-500"
              />

              <div className="mb-1 text-xs font-medium text-neutral-300">
                Jumlah kolom
              </div>
              <div className="mb-4 flex gap-2">
                {[1, 2, 3, 4].map((c) => (
                  <button
                    key={c}
                    onClick={() => setFormCols(c)}
                    className={`flex h-11 min-w-[48px] items-center justify-center rounded-lg text-sm font-semibold transition active:scale-95 ${
                      formCols === c
                        ? "bg-accent-600 text-white"
                        : "bg-ink-800 text-neutral-300 ring-1 ring-white/10 hover:bg-white/5"
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>

              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-medium text-neutral-300">
                  Pilih kamera ({formIds.size})
                </span>
              </div>
              <div className="mb-4 flex max-h-72 flex-col gap-1.5 overflow-y-auto rounded-lg bg-ink-950/50 p-2">
                {streams.map((s) => {
                  const checked = formIds.has(s.id);
                  return (
                    <label
                      key={s.id}
                      className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 transition active:scale-[0.99] ${
                        checked ? "bg-accent-600/15 ring-1 ring-accent-500/40" : "hover:bg-white/5"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleId(s.id)}
                        className="h-5 w-5 shrink-0 accent-[#4f46e5]"
                      />
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                      />
                      <span className="truncate text-sm text-neutral-200">
                        {s.name}
                      </span>
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
                <button
                  onClick={cancelEdit}
                  className="flex-1 rounded-lg bg-white/5 px-4 py-3 text-sm text-neutral-200 transition hover:bg-white/10 active:scale-[0.99]"
                >
                  Batal
                </button>
                <button
                  onClick={saveForm}
                  disabled={!formName.trim() || formIds.size === 0}
                  className="flex-1 rounded-lg bg-accent-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent-500 active:scale-[0.99] disabled:opacity-40"
                >
                  Simpan
                </button>
              </div>
            </div>
          </div>
        ) : (
          /* ===== Daftar layout ===== */
          <div>
            <div className="mb-4 flex items-center justify-between">
              <h1 className="text-base font-bold text-white">
                Monitor tersimpan
              </h1>
              <button
                onClick={startCreate}
                className="rounded-lg bg-accent-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-500 active:scale-95"
              >
                + Baru
              </button>
            </div>

            {fetching && layouts.length === 0 ? (
              <div className="flex flex-col gap-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-16 animate-pulse rounded-xl bg-ink-800"
                  />
                ))}
              </div>
            ) : layouts.length === 0 ? (
              <div className="rounded-xl bg-ink-900 p-8 text-center ring-1 ring-white/10">
                <div className="mb-1 text-sm font-medium text-white">
                  Belum ada monitor tersimpan
                </div>
                <p className="mb-4 text-xs text-neutral-400">
                  Buat tata letak kisi kamera favoritmu — tersimpan di perangkat
                  ini.
                </p>
                <button
                  onClick={startCreate}
                  className="rounded-lg bg-accent-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-500 active:scale-95"
                >
                  Buat monitor pertama
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {layouts.map((l) => {
                  const expanded = expandedId === l.id;
                  const count = l.streamIds.length;
                  return (
                    <div
                      key={l.id}
                      className="overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/10"
                    >
                      {/* Baris ringkasan — collapsed-first di mobile */}
                      <button
                        onClick={() =>
                          setExpandedId(expanded ? null : l.id)
                        }
                        className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition hover:bg-white/[0.03] active:scale-[0.995]"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-semibold text-white">
                            {l.name}
                          </div>
                          <div className="text-xs text-neutral-400">
                            {count} kamera · {l.cols} kolom
                          </div>
                        </div>
                        <Chevron open={expanded} />
                      </button>
                      {/* Aksi — hanya setelah expand */}
                      {expanded && (
                        <div className="flex gap-2 border-t border-white/10 px-4 py-3">
                          <button
                            onClick={() => setOpenId(l.id)}
                            className="flex-1 rounded-lg bg-accent-600 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-500 active:scale-[0.99]"
                          >
                            Buka
                          </button>
                          <button
                            onClick={() => startEdit(l)}
                            className="flex-1 rounded-lg bg-white/5 px-3 py-2.5 text-sm text-neutral-200 transition hover:bg-white/10 active:scale-[0.99]"
                          >
                            Ubah
                          </button>
                          <button
                            onClick={() => {
                              if (
                                window.confirm(
                                  `Hapus monitor "${l.name}"?`,
                                )
                              )
                                removeLayout(l.id);
                            }}
                            className="rounded-lg bg-bad-400/10 px-4 py-2.5 text-sm text-bad-400 ring-1 ring-bad-400/30 transition hover:bg-bad-400/20 active:scale-[0.99]"
                          >
                            Hapus
                          </button>
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
    </AppShell>
  );
}
