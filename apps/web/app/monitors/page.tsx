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
import { api, ApiError, usePosterUrl } from "../../lib/api";
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

/* Satu sel pratinjau mini: poster terbaru kamera + titik status + nama.
   Komponen sendiri supaya usePosterUrl dipanggil per sel (hook tidak
   boleh dipanggil di dalam loop .map). Bila tidak ada poster, sel
   tetap gelap seperti sebelumnya. */
function MiniPreviewCell({ stream }: { stream: Stream | undefined }) {
  const posterSrc = usePosterUrl(stream?.poster_url);
  return (
    <div
      title={stream?.name ?? "Tanpa nama"}
      className="relative aspect-video overflow-hidden rounded-lg bg-ink-800"
    >
      {posterSrc && (
        <img
          src={posterSrc}
          alt=""
          aria-hidden
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
      {/* Gradasi bawah supaya nama terbaca di atas gambar. */}
      {posterSrc && (
        <div
          className="absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-black/75 to-transparent"
          aria-hidden
        />
      )}
      <span
        className={`absolute left-1.5 top-1.5 h-1.5 w-1.5 rounded-full ring-1 ring-black/40 ${stream?.is_online ? "bg-ok-400" : "bg-bad-400"}`}
      />
      <span className="absolute inset-x-1.5 bottom-1 truncate text-xs font-medium text-white">
        {stream?.name ?? "Tanpa nama"}
      </span>
    </div>
  );
}

/* Satu thumbnail kecil di dalam sel sisa: poster kamera saja, tanpa
   label nama dan titik status (terlalu kecil untuk itu). Komponen
   sendiri supaya usePosterUrl dipanggil per thumbnail (hook tidak
   boleh dipanggil di dalam loop .map). Bila tidak ada poster,
   thumbnail tetap gelap seperti sel biasa. */
function MiniPreviewRestThumb({ stream }: { stream: Stream | undefined }) {
  const posterSrc = usePosterUrl(stream?.poster_url);
  return (
    <div
      title={stream?.name ?? "Tanpa nama"}
      className="relative overflow-hidden bg-ink-800"
    >
      {posterSrc && (
        <img
          src={posterSrc}
          alt=""
          aria-hidden
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
    </div>
  );
}

/* Sel sisa "+N": bukan hitam polos lagi, melainkan mini-grid berisi
   poster kamera-kamera berikutnya (maks 4), dengan lencana jumlah
   sisa total di sudut kanan bawah supaya fotonya tetap terlihat dan
   jumlah sisanya tetap jelas. Grid menyesuaikan jumlah foto: 1 foto
   penuh, 2 foto berdampingan, 3-4 foto jadi 2x2. */
function MiniPreviewRestCell({
  streamIds,
  byId,
  rest,
}: {
  streamIds: number[];
  byId: Map<number, Stream>;
  rest: number;
}) {
  const thumbs = streamIds.slice(0, 4);
  const gridClass =
    thumbs.length <= 1
      ? "grid-cols-1 grid-rows-1"
      : thumbs.length === 2
        ? "grid-cols-2 grid-rows-1"
        : "grid-cols-2 grid-rows-2";
  return (
    <div
      title={`+${rest} kamera lagi`}
      className="relative aspect-video overflow-hidden rounded-lg bg-ink-800"
    >
      <div className={`grid h-full w-full gap-px ${gridClass}`}>
        {thumbs.map((id) => (
          <MiniPreviewRestThumb key={id} stream={byId.get(id)} />
        ))}
      </div>
      <span className="absolute bottom-1 right-1 rounded-full bg-black/70 px-1.5 py-0.5 text-[11px] font-semibold leading-none text-white ring-1 ring-white/25">
        +{rest}
      </span>
    </div>
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
      {cells.map((id) => (
        <MiniPreviewCell key={id} stream={byId.get(id)} />
      ))}
      {rest > 0 && (
        <MiniPreviewRestCell
          streamIds={streamIds.slice(shownCount)}
          byId={byId}
          rest={rest}
        />
      )}
    </div>
  );
}

/* Mode grup: kamera dikelompokkan per grup kamera (admin).
   Hanya grup yang punya kamera di layout ini yang ditampilkan;
   kamera tanpa grup masuk "Tanpa grup". */
export default function MonitorsPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const { status } = useCameraStatus();

  const [streams, setStreams] = useState<Stream[]>([]);
  const [layouts, setLayouts] = useState<MonitorLayout[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  /* Layout grup yang dibuka dari daftar (bukan monitor tersimpan):
     sementara, tidak disimpan ke localStorage. */
  const [openGroupLayout, setOpenGroupLayout] =
    useState<MonitorLayout | null>(null);
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedGroupId, setExpandedGroupId] = useState<number | null>(null);
  const [editing, setEditing] = useState<MonitorLayout | null>(null);
  const [focus, setFocus] = useState<Stream | null>(null);
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

  /* Buka satu grup kamera sebagai monitor (layout sementara, tidak
     tersimpan): tampilkan semua kamera grup itu dalam kisi. */
  const openGroup = (g: { id: number; name: string; stream_ids: number[] }) => {
    setOpenGroupLayout({
      id: `group-${g.id}`,
      name: g.name,
      cols: 2,
      streamIds: g.stream_ids,
    });
    setOpenId(`group-${g.id}`);
  };

  /* Grup kamera di daftar (sebelum buka monitor tersimpan): muat sekali
     saat halaman dibuka, hanya untuk admin/super_admin. */
  useEffect(() => {
    if (!user) return;
    if (!isAdminRole(user.role)) return;
    if (groups !== null) return;
    loadGroups();
  }, [user, groups, loadGroups]);

  /* D-S9: toggleFullscreen kini dari hook useFullscreen (lihat atas). */

  const openLayout =
    openGroupLayout ?? layouts.find((l) => l.id === openId) ?? null;
  const openStreams = openLayout
    ? openLayout.streamIds
        .map((id) => byId.get(id))
        .filter((s): s is Stream => !!s)
    : [];

  /* Paginasi grid layout terbuka (sama seperti Live): per halaman tampil
     cols x cols kamera (2x2 = 4, 3x3 = 9, 4x4 = 16). */
  const perPage = (openLayout?.cols || 2) * (openLayout?.cols || 2);
  const totalPages = Math.max(1, Math.ceil(openStreams.length / perPage));
  const safePage = Math.min(page, totalPages);
  const visibleStreams = openStreams.slice(
    (safePage - 1) * perPage,
    safePage * perPage,
  );

  /* Ganti monitor atau isi monitor berubah: kembali ke halaman 1. */
  useEffect(() => {
    setPage(1);
  }, [openId, openGroupLayout, openStreams.length]);

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
              desc={`${openStreams.length} kamera · ${openLayout.cols} kolom`}
              action={
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="subtle"
                    onClick={() => {
                      setOpenId(null);
                      setOpenGroupLayout(null);
                    }}
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
                    length: perPage,
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
              ) : (
                <div
                  className={isFullscreen ? "flex h-dvh flex-col" : undefined}
                >
                  <div
                    className={`grid gap-4 ${COLS_CLASS[openLayout.cols] ?? COLS_CLASS[2]} ${isFullscreen ? "min-h-0 flex-1" : ""}`}
                    style={
                      isFullscreen
                        ? {
                            gridTemplateRows: `repeat(${Math.max(1, Math.ceil(visibleStreams.length / (openLayout.cols || 2)))}, minmax(0, 1fr))`,
                          }
                        : undefined
                    }
                  >
                    {visibleStreams.map((s) => (
                      <CameraTile
                        key={s.id}
                        stream={s}
                        onExpand={setFocus}
                        ad={ad}
                        adInFrame={isFullscreen}
                        fillCell={isFullscreen}
                      />
                    ))}
                  </div>
                  {totalPages > 1 && (
                    <div className="mt-4 flex items-center justify-center gap-2">
                      <Button
                        variant="subtle"
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                        disabled={safePage <= 1}
                        aria-label="Halaman sebelumnya"
                        className="rounded-full"
                      >
                        ‹ Sebelumnya
                      </Button>
                      <span className="text-sm font-semibold text-slate-300">
                        Halaman {safePage} dari {totalPages}
                      </span>
                      <Button
                        variant="subtle"
                        onClick={() =>
                          setPage((p) => Math.min(totalPages, p + 1))
                        }
                        disabled={safePage >= totalPages}
                        aria-label="Halaman berikutnya"
                        className="rounded-full"
                      >
                        Berikutnya ›
                      </Button>
                    </div>
                  )}
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
            {/* Grup kamera (admin/super_admin): buka satu grup langsung
                sebagai monitor, tanpa harus membuat layout tersimpan dulu. */}
            {isAdminRole(user?.role) && (
              <div className="mb-6">
                <SectionTitle
                  title="Grup kamera"
                  desc="Buka monitor per grup"
                />
                {groupsLoading && groups === null ? (
                  <div className="flex flex-col gap-3">
                    {Array.from({ length: 2 }).map((_, i) => (
                      <div
                        key={i}
                        className="h-24 animate-pulse rounded-2xl bg-ink-800 motion-reduce:animate-none"
                      />
                    ))}
                  </div>
                ) : groupsError ? (
                  <div className="nv-panel-modern flex flex-col items-center gap-3 px-6 py-8 text-center">
                    <p className="text-sm text-neutral-400">{groupsError}</p>
                    <Button variant="subtle" onClick={loadGroups}>
                      Coba lagi
                    </Button>
                  </div>
                ) : groups && groups.length > 0 ? (
                  <div className="flex flex-col gap-3">
                    {groups.map((g) => {
                      const expanded = expandedGroupId === g.id;
                      const existing = g.stream_ids
                        .map((id) => byId.get(id))
                        .filter((s): s is Stream => !!s);
                      const count = existing.length;
                      const onlineN = existing.filter(
                        (s) => s.is_online,
                      ).length;
                      const groupLayout: MonitorLayout = {
                        id: `group-${g.id}`,
                        name: g.name,
                        cols: 2,
                        streamIds: g.stream_ids,
                      };
                      return (
                        <div
                          key={g.id}
                          className="nv-panel-modern overflow-hidden"
                        >
                          <button
                            onClick={() =>
                              setExpandedGroupId(expanded ? null : g.id)
                            }
                            aria-expanded={expanded}
                            className="block w-full px-4 py-4 text-left transition hover:bg-ink-800 active:scale-[0.995] sm:px-5"
                          >
                            <div className="flex items-center gap-3">
                              <div className="min-w-0 flex-1">
                                <div className="truncate text-base font-semibold text-white">
                                  {g.name}
                                </div>
                                <div className="mt-0.5 text-xs text-neutral-400">
                                  {count} kamera ·{" "}
                                  <span className="text-ok-400">
                                    {onlineN} online
                                  </span>{" "}
                                  · Grup kamera
                                </div>
                              </div>
                              <Chevron open={expanded} />
                            </div>
                            <MiniPreview layout={groupLayout} byId={byId} />
                          </button>
                          {expanded && (
                            <div className="flex gap-2 border-t border-ink-800 px-4 py-3 sm:px-5">
                              <Button
                                onClick={() => openGroup(g)}
                                className="flex-1"
                              >
                                Buka
                              </Button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            )}
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
                          <Button
                            onClick={() => {
                              setOpenGroupLayout(null);
                              setOpenId(l.id);
                            }}
                            className="flex-1"
                          >
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
