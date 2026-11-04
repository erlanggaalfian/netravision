"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { Stream, User } from "../../../lib/types";
import { ErrorBox, Modal, Spinner } from "../../../components/ui";
import {
  NBBadge,
  NBButton,
  NBCard,
  NBTitle,
  NBInput,
  NBTableWrap,
  NBTh,
  NBTd,
  NBTr,
} from "../_nb";

type Arah = "akun" | "kamera";

interface Overview {
  roles: Record<string, number>;
  grants: { stream_id: number; stream_name: string | null; users: number }[];
}

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  user: "Pengguna",
  guest: "Tamu",
  super_admin: "Super Admin",
};

export default function AdminAccessPage() {
  const [arah, setArah] = useState<Arah>("akun");
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<User[] | null>(null);
  const [streams, setStreams] = useState<Stream[] | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [manageUser, setManageUser] = useState<User | null>(null);
  const [manageStream, setManageStream] = useState<Stream | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<User[]>("/admin/users"),
      api.get<Stream[]>("/admin/streams"),
      api.get<Overview>("/admin/access-overview"),
    ])
      .then(([u, s, o]) => {
        setUsers(u);
        setStreams(s);
        setOverview(o);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat data akses"),
      );
  }, []);

  function refreshOverview() {
    api
      .get<Overview>("/admin/access-overview")
      .then(setOverview)
      .catch(() => {});
  }

  const ql = q.trim().toLowerCase();
  const filteredUsers = (users ?? []).filter(
    (u) => !ql || u.username.toLowerCase().includes(ql),
  );
  const filteredStreams = (streams ?? []).filter(
    (s) => !ql || s.name.toLowerCase().includes(ql),
  );
  const grantCount = (sid: number) =>
    overview?.grants.find((g) => g.stream_id === sid)?.users ?? 0;

  const loading = users === null || streams === null;

  return (
    <div>
      <NBTitle
        title="Akses Kamera"
        desc="Atur kamera mana yang dapat dilihat tiap akun"
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      <NBCard>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex rounded-xl border border-ink-700 bg-ink-950 p-1">
            {(["akun", "kamera"] as Arah[]).map((a) => (
              <button
                key={a}
                onClick={() => setArah(a)}
                className={`min-h-[44px] rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                  arah === a
                    ? "bg-accent-500 text-onaccent"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {a === "akun" ? "Per akun" : "Per kamera"}
              </button>
            ))}
          </div>
          <div className="w-full sm:w-64">
            <NBInput
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Cari…"
              aria-label="Cari"
            />
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : arah === "akun" ? (
          <NBTableWrap>
            <table className="w-full text-left text-sm">
              <thead>
                <NBTr>
                  <NBTh>Akun</NBTh>
                  <NBTh>Peran</NBTh>
                  <NBTh className="text-center">Aksi</NBTh>
                </NBTr>
              </thead>
              <tbody>
                {filteredUsers.map((u) => (
                  <NBTr key={u.id}>
                    <NBTd className="font-medium">
                      {u.username}
                    </NBTd>
                    <NBTd>
                      <NBBadge tone="muted">
                        {ROLE_LABEL[u.role] ?? u.role}
                      </NBBadge>
                    </NBTd>
                    <NBTd className="text-center">
                      <NBButton
                        variant="secondary"
                        onClick={() => setManageUser(u)}
                      >
                        Kelola
                      </NBButton>
                    </NBTd>
                  </NBTr>
                ))}
                {filteredUsers.length === 0 && (
                  <NBTr>
                    <NBTd
                      colSpan={3}
                      className="py-8 text-center text-slate-400"
                    >
                      Tidak ada akun yang cocok.
                    </NBTd>
                  </NBTr>
                )}
              </tbody>
            </table>
          </NBTableWrap>
        ) : (
          <NBTableWrap>
            <table className="w-full text-left text-sm">
              <thead>
                <NBTr>
                  <NBTh>Kamera</NBTh>
                  <NBTh>Status</NBTh>
                  <NBTh className="text-center">
                    Akun berakses
                  </NBTh>
                  <NBTh className="text-center">Aksi</NBTh>
                </NBTr>
              </thead>
              <tbody>
                {filteredStreams.map((s) => (
                  <NBTr key={s.id}>
                    <NBTd className="font-medium">
                      {s.name}
                    </NBTd>
                    <NBTd>
                      <NBBadge tone={s.is_online ? "ok" : "bad"}>
                        {s.is_online ? "Online" : "Offline"}
                      </NBBadge>
                    </NBTd>
                    <NBTd className="text-center font-mono">
                      {grantCount(s.id)}
                    </NBTd>
                    <NBTd className="text-center">
                      <NBButton
                        variant="secondary"
                        onClick={() => setManageStream(s)}
                      >
                        Kelola
                      </NBButton>
                    </NBTd>
                  </NBTr>
                ))}
                {filteredStreams.length === 0 && (
                  <NBTr>
                    <NBTd
                      colSpan={4}
                      className="py-8 text-center text-slate-400"
                    >
                      Tidak ada kamera yang cocok.
                    </NBTd>
                  </NBTr>
                )}
              </tbody>
            </table>
          </NBTableWrap>
        )}
      </NBCard>

      {manageUser && streams && (
        <AccessByUserModal
          user={manageUser}
          streams={streams}
          onClose={() => {
            setManageUser(null);
            refreshOverview();
          }}
        />
      )}
      {manageStream && users && (
        <AccessByCameraModal
          stream={manageStream}
          users={users}
          onClose={() => {
            setManageStream(null);
            refreshOverview();
          }}
        />
      )}
    </div>
  );
}

/* ---------- Modal: kamera yang boleh dilihat satu akun ---------- */

function AccessByUserModal({
  user,
  streams,
  onClose,
}: {
  user: User;
  streams: Stream[];
  onClose: () => void;
}) {
  const [checked, setChecked] = useState<Set<number> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<{ stream_ids: number[] }>(`/admin/users/${user.id}/camera-access`)
      .then((r) => setChecked(new Set(r.stream_ids)))
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat akses"),
      );
  }, [user.id]);

  function toggle(sid: number) {
    setChecked((prev) => {
      if (!prev) return prev;
      const next = new Set(prev);
      if (next.has(sid)) next.delete(sid);
      else next.add(sid);
      return next;
    });
  }

  async function save() {
    if (!checked) return;
    setError("");
    setBusy(true);
    try {
      await api.post(`/admin/users/${user.id}/camera-access`, {
        stream_ids: [...checked],
      });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Akses kamera — ${user.username}`} onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {checked === null ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {streams.map((s) => (
              <label
                key={s.id}
                className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl px-3 py-2 hover:bg-ink-800/50"
              >
                <input
                  type="checkbox"
                  checked={checked.has(s.id)}
                  onChange={() => toggle(s.id)}
                  className="h-5 w-5 shrink-0 accent-accent-500"
                />
                <span className="flex-1 text-sm text-slate-200">{s.name}</span>
                <NBBadge tone={s.is_online ? "ok" : "bad"}>
                  {s.is_online ? "Online" : "Offline"}
                </NBBadge>
              </label>
            ))}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <NBButton variant="secondary" onClick={onClose}>
              Batal
            </NBButton>
            <NBButton onClick={save} disabled={busy}>
              {busy ? "Menyimpan…" : "Simpan"}
            </NBButton>
          </div>
        </>
      )}
    </Modal>
  );
}

/* ---------- Modal: akun yang boleh melihat satu kamera ---------- */

function AccessByCameraModal({
  stream,
  users,
  onClose,
}: {
  stream: Stream;
  users: User[];
  onClose: () => void;
}) {
  const [checked, setChecked] = useState<Set<number> | null>(null);
  const [guestAccess, setGuestAccess] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<{ user_ids: number[] }>(`/admin/streams/${stream.id}/sharing`)
      .then((r) => setChecked(new Set(r.user_ids)))
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat akses"),
      );
    /* Status akses Tamu harus ikut dimuat — tanpa ini Simpan selalu
       menulis can_view=false dan menghapus akses tamu yang sudah ada. */
    api
      .get<{ roles: { role: string; can_view: boolean }[] }>(
        `/admin/streams/${stream.id}/role-access`,
      )
      .then((r) =>
        setGuestAccess(
          r.roles.find((x) => x.role === "guest")?.can_view ?? false,
        ),
      )
      .catch(() => {});
  }, [stream.id]);

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
      await api.post(`/admin/streams/${stream.id}/sharing`, {
        user_ids: [...checked],
      });
      // Akses peran Tamu: endpoint khusus (lihat catatan).
      await api.put(`/admin/streams/${stream.id}/role-access`, {
        role: "guest",
        can_view: guestAccess,
      });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Akses — ${stream.name}`} onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {checked === null ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {/* Principal Tamu: semua sesi guest */}
            <label className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl border border-ink-700 bg-ink-950/60 px-3 py-2 hover:bg-ink-800/50">
              <input
                type="checkbox"
                checked={guestAccess}
                onChange={(e) => setGuestAccess(e.target.checked)}
                className="h-5 w-5 shrink-0 accent-accent-500"
              />
              <span className="flex-1 text-sm text-slate-200">
                Tamu <span className="text-slate-400">(semua sesi guest)</span>
              </span>
              <NBBadge tone="muted">Tamu</NBBadge>
            </label>
            {users.map((u) => (
              <label
                key={u.id}
                className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl px-3 py-2 hover:bg-ink-800/50"
              >
                <input
                  type="checkbox"
                  checked={checked.has(u.id)}
                  onChange={() => toggle(u.id)}
                  className="h-5 w-5 shrink-0 accent-accent-500"
                />
                <span className="flex-1 text-sm text-slate-200">
                  {u.username}
                </span>
                <NBBadge tone="muted">{ROLE_LABEL[u.role] ?? u.role}</NBBadge>
              </label>
            ))}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <NBButton variant="secondary" onClick={onClose}>
              Batal
            </NBButton>
            <NBButton onClick={save} disabled={busy}>
              {busy ? "Menyimpan…" : "Simpan"}
            </NBButton>
          </div>
        </>
      )}
    </Modal>
  );
}
