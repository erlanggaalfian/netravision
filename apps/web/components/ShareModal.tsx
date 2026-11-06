"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { User } from "../lib/types";
import {
  Badge,
  Button,
  ErrorBox,
  Modal,
  Spinner,
} from "./ui";

/* Modal berbagi kamera ke akun lain, dengan pilihan per akun:
   - Stream saja (live, tanpa playback/rekaman)
   - Stream + Playback (live + rekaman)
   Siap dipasang di halaman streams (atau di mana saja):
     const [shareFor, setShareFor] = useState<Stream | null>(null);
     ...
     <Button variant="subtle" onClick={() => setShareFor(s)}>Bagikan</Button>
     ...
     {shareFor && (
       <ShareModal
         streamId={shareFor.id}
         streamName={shareFor.name}
         onClose={() => setShareFor(null)}
       />
     )}
*/

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  user: "Pengguna",
  guest: "Tamu",
};

interface ShareEntry {
  user_id: number;
  can_playback: boolean;
}

export function ShareModal({
  streamId,
  streamName,
  onClose,
}: {
  streamId: number;
  streamName: string;
  onClose: () => void;
}) {
  const [users, setUsers] = useState<User[] | null>(null);
  // Map user_id -> can_playback (hanya untuk user yang di-share).
  const [shares, setShares] = useState<Map<number, boolean> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get<User[]>("/admin/users"),
      api.get<{ user_ids: number[]; shares: ShareEntry[] }>(
        `/admin/streams/${streamId}/sharing`,
      ),
    ])
      .then(([u, s]) => {
        setUsers(u);
        // Bentuk baru (shares) diutamakan; fallback ke user_ids lama.
        const m = new Map<number, boolean>();
        if (Array.isArray(s.shares)) {
          for (const sh of s.shares) m.set(sh.user_id, sh.can_playback);
        } else {
          for (const uid of s.user_ids ?? []) m.set(uid, true);
        }
        setShares(m);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat data"),
      );
  }, [streamId]);

  function toggleShare(uid: number) {
    setShares((prev) => {
      if (!prev) return prev;
      const next = new Map(prev);
      if (next.has(uid)) next.delete(uid);
      else next.set(uid, true);
      return next;
    });
  }

  function togglePlayback(uid: number) {
    setShares((prev) => {
      if (!prev || !prev.has(uid)) return prev;
      const next = new Map(prev);
      next.set(uid, !next.get(uid));
      return next;
    });
  }

  async function save() {
    if (!shares) return;
    setError("");
    setBusy(true);
    try {
      // Superadmin selalu ikut (otomatis, Stream + Playback) agar baris
      // share-nya tidak terhapus saat admin lain menyimpan.
      const all = new Map(shares);
      for (const u of users ?? []) {
        if (u.role === "super_admin") all.set(u.id, true);
      }
      await api.post(`/admin/streams/${streamId}/sharing`, {
        shares: [...all.entries()].map(([user_id, can_playback]) => ({
          user_id,
          can_playback,
        })),
      });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  const loading = users === null || shares === null;

  return (
    <Modal title={`Bagikan — ${streamName}`} onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {loading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <>
          <p className="mb-3 text-sm text-slate-400">
            Pilih akun yang boleh melihat kamera ini, lalu atur apakah mereka
            juga boleh membuka rekaman (playback).
          </p>
          <div className="max-h-[50vh] space-y-1 overflow-y-auto">
            {(users ?? []).map((u) => {
              // Superadmin otomatis punya akses semua kamera (bypass di
              // backend) — selalu tercantum, tidak bisa dihapus dari share.
              const isSuper = u.role === "super_admin";
              const shared = isSuper || (shares ?? new Map()).has(u.id);
              const playback = isSuper || ((shares ?? new Map()).get(u.id) ?? true);
              return (
                <div
                  key={u.id}
                  className="flex min-h-[44px] items-center gap-3 rounded-xl px-3 py-2 hover:bg-white/[0.03]"
                >
                  <input
                    type="checkbox"
                    checked={shared}
                    disabled={isSuper}
                    onChange={() => toggleShare(u.id)}
                    className="h-5 w-5 shrink-0 accent-blue-500 disabled:opacity-60"
                    aria-label={`Bagikan ke ${u.username}`}
                  />
                  <span className="min-w-0 flex-1 text-sm text-slate-200">
                    {u.username}
                  </span>
                  <Badge tone="muted">{ROLE_LABEL[u.role] ?? u.role}</Badge>
                  {isSuper && (
                    <Badge tone="info">Otomatis</Badge>
                  )}
                  {shared && (
                    <button
                      type="button"
                      onClick={() => togglePlayback(u.id)}
                      disabled={isSuper}
                      className={`shrink-0 cursor-pointer rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-all active:scale-[0.97] disabled:cursor-default disabled:opacity-80 ${
                        playback
                          ? "border-accent-500/40 bg-accent-500/15 text-accent-300"
                          : "border-slate-200/20 bg-transparent text-slate-400"
                      }`}
                      title={
                        isSuper
                          ? "Superadmin otomatis Stream + Playback di semua kamera"
                          : playback
                            ? "Boleh membuka rekaman — ketuk untuk stream saja"
                            : "Stream saja — ketuk untuk izinkan playback"
                      }
                    >
                      {playback ? "Stream + Playback" : "Stream saja"}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Batal
            </Button>
            <Button onClick={save} disabled={busy}>
              {busy ? "Menyimpan…" : "Simpan"}
            </Button>
          </div>
        </>
      )}
    </Modal>
  );
}
