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

/* Modal berbagi kamera ke akun lain.
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
  const [checked, setChecked] = useState<Set<number> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get<User[]>("/admin/users"),
      api.get<{ user_ids: number[] }>(`/admin/streams/${streamId}/sharing`),
    ])
      .then(([u, s]) => {
        setUsers(u);
        setChecked(new Set(s.user_ids));
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat data"),
      );
  }, [streamId]);

  function toggle(uid: number) {
    setChecked((prev) => {
      if (!prev) return prev;
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }

  async function save() {
    if (!checked) return;
    setError("");
    setBusy(true);
    try {
      await api.post(`/admin/streams/${streamId}/sharing`, {
        user_ids: [...checked],
      });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  const loading = users === null || checked === null;

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
            Pilih akun yang boleh melihat kamera ini.
          </p>
          <div className="max-h-[50vh] space-y-1 overflow-y-auto">
            {(users ?? []).map((u) => (
              <label
                key={u.id}
                className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl px-3 py-2 hover:bg-white/[0.03]"
              >
                <input
                  type="checkbox"
                  checked={(checked ?? new Set()).has(u.id)}
                  onChange={() => toggle(u.id)}
                  className="h-5 w-5 shrink-0 accent-blue-500"
                />
                <span className="flex-1 text-sm text-slate-200">
                  {u.username}
                </span>
                <Badge tone="muted">{ROLE_LABEL[u.role] ?? u.role}</Badge>
              </label>
            ))}
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
