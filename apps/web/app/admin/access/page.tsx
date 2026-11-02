"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { Stream, User } from "../../../lib/types";
import {
  Badge,
  Button,
  Card,
  ErrorBox,
  Modal,
  SectionTitle,
  Spinner,
  TextInput,
} from "../../../components/ui";

type Arah = "akun" | "kamera";

interface Overview {
  roles: Record<string, number>;
  grants: { stream_id: number; stream_name: string | null; users: number }[];
}

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  user: "Pengguna",
  guest: "Tamu",
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
      <SectionTitle
        title="Akses Kamera"
        desc="Atur kamera mana yang dapat dilihat tiap akun"
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      <Card>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex rounded-xl border border-ink-700 bg-ink-950 p-1">
            {(["akun", "kamera"] as Arah[]).map((a) => (
              <button
                key={a}
                onClick={() => setArah(a)}
                className={`rounded-lg px-4 text-sm font-medium transition-colors ${
                  arah === a
                    ? "bg-accent-600 text-white"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {a === "akun" ? "Per akun" : "Per kamera"}
              </button>
            ))}
          </div>
          <div className="w-full sm:w-64">
            <TextInput
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
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-ink-700 text-xs uppercase tracking-wider text-slate-500">
                  <th scope="col" className="px-3 py-3 font-semibold">Akun</th>
                  <th scope="col" className="px-3 py-3 font-semibold">Peran</th>
                  <th scope="col" className="px-3 py-3 text-center font-semibold">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-700/60">
                {filteredUsers.map((u) => (
                  <tr key={u.id} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-3 font-medium text-white">
                      {u.username}
                    </td>
                    <td className="px-3 py-3">
                      <Badge tone="muted">
                        {ROLE_LABEL[u.role] ?? u.role}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-center">
                      <Button
                        variant="subtle"
                        onClick={() => setManageUser(u)}
                      >
                        Kelola
                      </Button>
                    </td>
                  </tr>
                ))}
                {filteredUsers.length === 0 && (
                  <tr>
                    <td
                      colSpan={3}
                      className="px-3 py-8 text-center text-sm text-slate-500"
                    >
                      Tidak ada akun yang cocok.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-ink-700 text-xs uppercase tracking-wider text-slate-500">
                  <th scope="col" className="px-3 py-3 font-semibold">Kamera</th>
                  <th scope="col" className="px-3 py-3 font-semibold">Status</th>
                  <th scope="col" className="px-3 py-3 text-center font-semibold">
                    Akun berakses
                  </th>
                  <th scope="col" className="px-3 py-3 text-center font-semibold">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-700/60">
                {filteredStreams.map((s) => (
                  <tr key={s.id} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-3 font-medium text-white">
                      {s.name}
                    </td>
                    <td className="px-3 py-3">
                      <Badge tone={s.is_online ? "ok" : "bad"}>
                        {s.is_online ? "Online" : "Offline"}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-center font-mono text-slate-300">
                      {grantCount(s.id)}
                    </td>
                    <td className="px-3 py-3 text-center">
                      <Button
                        variant="subtle"
                        onClick={() => setManageStream(s)}
                      >
                        Kelola
                      </Button>
                    </td>
                  </tr>
                ))}
                {filteredStreams.length === 0 && (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-3 py-8 text-center text-sm text-slate-500"
                    >
                      Tidak ada kamera yang cocok.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

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
          <div className="max-h-[50vh] space-y-1 overflow-y-auto">
            {streams.map((s) => (
              <label
                key={s.id}
                className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl px-3 py-2 hover:bg-white/[0.03]"
              >
                <input
                  type="checkbox"
                  checked={checked.has(s.id)}
                  onChange={() => toggle(s.id)}
                  className="h-5 w-5 shrink-0 accent-accent-500"
                />
                <span className="flex-1 text-sm text-slate-200">{s.name}</span>
                <Badge tone={s.is_online ? "ok" : "bad"}>
                  {s.is_online ? "Online" : "Offline"}
                </Badge>
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
          <div className="max-h-[50vh] space-y-1 overflow-y-auto">
            {/* Principal Tamu: semua sesi guest */}
            <label className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl border border-ink-700 bg-ink-950/60 px-3 py-2 hover:bg-white/[0.03]">
              <input
                type="checkbox"
                checked={guestAccess}
                onChange={(e) => setGuestAccess(e.target.checked)}
                className="h-5 w-5 shrink-0 accent-accent-500"
              />
              <span className="flex-1 text-sm text-slate-200">
                Tamu <span className="text-slate-500">(semua sesi guest)</span>
              </span>
              <Badge tone="muted">Tamu</Badge>
            </label>
            {users.map((u) => (
              <label
                key={u.id}
                className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl px-3 py-2 hover:bg-white/[0.03]"
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
