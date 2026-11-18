"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../lib/api";
import type { Stream, User } from "../../lib/types";
import { ErrorBox, Modal, Spinner, Switch } from "../../components/ui";
import { NBButton, NBEmptyState } from "../../app/admin/_nb";

/* P1 code-review 2026-11-18: dipindah dari app/admin/users/page.tsx
   tanpa perubahan perilaku — modal grant admin per kamera
   (live/playback/bagikan). */

export type GrantFlags = {
  can_view: boolean;
  can_playback: boolean;
  can_reshare: boolean;
};

export const EMPTY_GRANT: GrantFlags = {
  can_view: false,
  can_playback: false,
  can_reshare: false,
};

/* ---------- Modal: grant admin per kamera (live/playback/bagikan) ---------- */

export function AdminGrantModal({
  user,
  streams,
  onClose,
}: {
  user: User;
  streams: Stream[];
  onClose: () => void;
}) {
  const [grants, setGrants] = useState<Record<number, GrantFlags>>({});
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /* Muat ulang daftar saat gagal (pola yang sama di semua modal hak
     akses): tombol "Coba lagi" memicu effect ini lagi. */
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    setLoaded(false);
    setLoadFailed(false);
    setError("");
    api
      .get<{
        grants: {
          stream_id: number;
          can_view: boolean;
          can_playback: boolean;
          can_reshare: boolean;
        }[];
      }>(`/admin/admins/${user.id}/camera-grants`)
      .then((r) => {
        const map: Record<number, GrantFlags> = {};
        for (const g of r.grants ?? []) {
          map[g.stream_id] = {
            can_view: g.can_view,
            can_playback: g.can_playback,
            can_reshare: g.can_reshare,
          };
        }
        setGrants(map);
      })
      .catch((e) => {
        setLoadFailed(true);
        setError(e instanceof ApiError ? e.message : "Gagal memuat hak akses");
      })
      .finally(() => setLoaded(true));
  }, [user.id, reloadKey]);

  function setFlag(
    id: number,
    key: "can_view" | "can_playback" | "can_reshare",
    value: boolean,
  ) {
    setGrants((prev) => {
      const cur = prev[id] ?? { ...EMPTY_GRANT };
      const next = { ...cur, [key]: value };
      /* E-S3: Playback dan Bagikan butuh Live; mematikan Live ikut
         mematikan Playback dan Bagikan. */
      if ((key === "can_playback" || key === "can_reshare") && value) {
        next.can_view = true;
      }
      if (key === "can_view" && !value) {
        next.can_playback = false;
        next.can_reshare = false;
      }
      return { ...prev, [id]: next };
    });
  }

  async function save() {
    setError("");
    setBusy(true);
    try {
      const list = Object.entries(grants)
        .filter(([, g]) => g.can_view || g.can_playback)
        .map(([sid, g]) => ({ stream_id: Number(sid), ...g }));
      await api.post(`/admin/admins/${user.id}/camera-grants`, {
        grants: list,
      });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Akses kamera: ${user.username}`} onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {loadFailed && (
        <div className="mb-4">
          <NBButton variant="secondary" onClick={() => setReloadKey((k) => k + 1)}>
            Coba lagi
          </NBButton>
        </div>
      )}
      {!loaded ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : streams.length === 0 ? (
        <NBEmptyState text="Belum ada kamera." />
      ) : (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <p className="text-xs leading-relaxed text-slate-400">
              Bagikan yang dicentang berarti admin ini bisa meneruskan kamera
              ke user di grupnya.
            </p>
            <div className="flex shrink-0 gap-2">
              <NBButton
                variant="secondary"
                onClick={() =>
                  setGrants((prev) => {
                    const next: Record<number, GrantFlags> = { ...prev };
                    for (const s of streams) {
                      next[s.id] = {
                        ...(next[s.id] ?? { ...EMPTY_GRANT }),
                        can_view: true,
                      };
                    }
                    return next;
                  })
                }
                className="px-3"
              >
                Pilih semua
              </NBButton>
              <NBButton
                variant="secondary"
                onClick={() => setGrants({})}
                className="px-3"
              >
                Bersihkan
              </NBButton>
            </div>
          </div>
          <div className="mb-1 flex items-center gap-2 px-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            <span className="min-w-0 flex-1">Kamera</span>
            <span className="w-16 shrink-0 text-center">Live</span>
            <span className="w-16 shrink-0 text-center">Playback</span>
            <span className="w-16 shrink-0 text-center">Bagikan</span>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {streams.map((s) => {
              const g = grants[s.id] ?? { ...EMPTY_GRANT };
              return (
                <div
                  key={s.id}
                  className="flex min-h-[48px] items-center gap-2 rounded-lg px-3 py-2 hover:bg-ink-800"
                >
                  <span className="min-w-0 flex-1 truncate text-sm text-slate-200">
                    {s.name}
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <Switch
                      checked={g.can_view}
                      onChange={(v) => setFlag(s.id, "can_view", v)}
                      label={`Live ${s.name}`}
                    />
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <Switch
                      checked={g.can_playback}
                      onChange={(v) => setFlag(s.id, "can_playback", v)}
                      label={`Playback ${s.name}`}
                    />
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <Switch
                      checked={g.can_reshare}
                      onChange={(v) => setFlag(s.id, "can_reshare", v)}
                      label={`Bagikan ${s.name}`}
                    />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <NBButton variant="secondary" onClick={onClose}>
          Batal
        </NBButton>
        <NBButton onClick={save} disabled={busy || !loaded || loadFailed}>
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}
