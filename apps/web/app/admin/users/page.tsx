"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { Stream, User } from "../../../lib/types";
import { ErrorBox, Modal, Spinner } from "../../../components/ui";
import {
  NBAccordion,
  NBBadge,
  NBButton,
  NBConfirmModal,
  NBEmptyState,
  NBField,
  NBInput,
  NBSelect,
  NBTitle,
} from "../_nb";

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  user: "Pengguna",
  guest: "Tamu",
  super_admin: "Super Admin",
};

function UserIcon({ className = "" }: { className?: string }) {
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
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}



export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [accessFor, setAccessFor] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);

  const load = () =>
    api
      .get<User[]>("/admin/users")
      .then(setUsers)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "Gagal memuat pengguna");
        setUsers([]);
      });

  useEffect(() => {
    load();
    api.get<Stream[]>("/admin/streams").then((d) => setStreams(d ?? [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function doDelete() {
    if (!deleting) return;
    try {
      await api.del(`/admin/users/${deleting.id}`);
      setDeleting(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus");
    }
  }

  return (
    <div>
      <NBTitle
        title="Pengguna"
        desc="Kelola akun dan hak akses kamera"
        action={<NBButton onClick={() => setShowAdd(true)}>+ Tambah Pengguna</NBButton>}
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {users === null ? (
        <Spinner />
      ) : users.length === 0 ? (
        <NBEmptyState icon={<UserIcon className="h-8 w-8 text-slate-500" />} text="Belum ada pengguna." />
      ) : (
        <div className="space-y-2">
          {users.map((u) => {
            const summary = (
              <span className="flex items-center justify-between gap-3">
                <span className="min-w-0">
                  <span className="block truncate font-medium text-white">
                    {u.username}
                  </span>
                  <span className="mt-0.5 flex flex-wrap gap-1">
                    <NBBadge
                      tone={
                        u.role === "admin" || u.role === "super_admin"
                          ? "info"
                          : u.role === "guest"
                            ? "muted"
                            : "ok"
                      }
                    >
                      {ROLE_LABEL[u.role] ?? u.role}
                    </NBBadge>
                    <NBBadge tone={u.show_ads ? "ok" : "muted"}>
                      Iklan: {u.show_ads ? "Ya" : "Tidak"}
                    </NBBadge>
                  </span>
                  <span className="mt-1 block text-xs text-slate-400">
                    Dibuat oleh: {u.dibuat_oleh ?? "—"}
                  </span>
                </span>
              </span>
            );
            const actions = (
              <div className="flex flex-wrap gap-2">
                {/* Superadmin selalu mendapat akses ke semua kamera,
                    jadi tidak ada pengaturan Akses Kamera untuknya. */}
                {u.role !== "super_admin" && (
                  <NBButton
                    variant="secondary"
                    onClick={() => setAccessFor(u)}
                    className="px-3"
                  >
                    Akses Kamera
                  </NBButton>
                )}
                <NBButton
                  variant="secondary"
                  onClick={() => setEditing(u)}
                  className="px-3"
                >
                  Ubah
                </NBButton>
                <NBButton
                  variant="danger"
                  onClick={() => setDeleting(u)}
                  className="px-3"
                >
                  Hapus
                </NBButton>
              </div>
            );
            return (
              <div key={u.id}>
                <div className="md:hidden">
                  <NBAccordion summary={summary}>
                    <div className="space-y-3">{actions}</div>
                  </NBAccordion>
                </div>
                <div className="hidden items-center justify-between gap-3 rounded-xl bg-ink-800 shadow-sm px-4 py-3 transition-colors md:flex">
                  {summary}
                  {actions}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showAdd && (
        <UserFormModal
          onClose={() => setShowAdd(false)}
          onDone={() => {
            setShowAdd(false);
            load();
          }}
        />
      )}
      {editing && (
        <UserFormModal
          user={editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            load();
          }}
        />
      )}
      {accessFor && (
        <AccessModal
          user={accessFor}
          streams={streams}
          onClose={() => setAccessFor(null)}
        />
      )}
      {deleting && (
        <NBConfirmModal
          title="Hapus pengguna"
          message={`Hapus akun "${deleting.username}"?`}
          onCancel={() => setDeleting(null)}
          onConfirm={doDelete}
        />
      )}
    </div>
  );
}

function UserFormModal({
  user,
  onClose,
  onDone,
}: {
  user?: User;
  onClose: () => void;
  onDone: () => void;
}) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<string>(user?.role ?? "user");
  const [showAds, setShowAds] = useState(user?.show_ads ?? true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setError("");
    setBusy(true);
    try {
      if (user) {
        const body: Record<string, unknown> = {
          username: username.trim(),
          role,
          show_ads: showAds,
        };
        if (password) body.password = password;
        await api.put(`/admin/users/${user.id}`, body);
      } else {
        await api.post("/admin/users", {
          username: username.trim(),
          password,
          role,
          show_ads: showAds,
        });
      }
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={user ? "Ubah Pengguna" : "Tambah Pengguna"} onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="space-y-4">
        <NBField label="Nama pengguna">
          <NBInput
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </NBField>
        <NBField
          label={user ? "Kata sandi baru (kosongkan bila tidak diubah)" : "Kata sandi"}
          hint={!user ? "Minimal 8 karakter" : undefined}
        >
          <NBInput
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </NBField>
        <NBField label="Peran">
          <NBSelect value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="user">Pengguna</option>
            <option value="admin">Admin</option>
            <option value="guest">Tamu</option>
            <option value="super_admin">Super Admin</option>
          </NBSelect>
        </NBField>
        <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 rounded-xl bg-ink-800 shadow-sm px-4 py-3">
          <span>
            <span className="block text-sm font-medium text-white">
              Tampilkan Iklan
            </span>
            <span className="block text-xs text-slate-400">
              Banner iklan tampil untuk akun ini
            </span>
          </span>
          <input
            type="checkbox"
            checked={showAds}
            onChange={(e) => setShowAds(e.target.checked)}
            className="h-5 w-5 shrink-0 accent-accent-500"
            aria-label="Tampilkan Iklan"
          />
        </label>
        <NBButton
          onClick={save}
          disabled={busy || !username.trim() || (!user && !password)}
          className="w-full"
        >
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}

function AccessModal({
  user,
  streams,
  onClose,
}: {
  user: User;
  streams: Stream[];
  onClose: () => void;
}) {
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<{ stream_ids: number[] }>(`/admin/users/${user.id}/camera-access`)
      .then((r) => setChecked(new Set(r.stream_ids)))
      .catch((e) => {
        setLoadFailed(true);
        setError(e instanceof ApiError ? e.message : "Gagal memuat hak akses");
      })
      .finally(() => setLoaded(true));
  }, [user.id]);

  function toggle(id: number) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function save() {
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
      {!loaded ? (
        <Spinner />
      ) : streams.length === 0 ? (
        <NBEmptyState text="Belum ada kamera." />
      ) : (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <p className="text-xs tabular-nums text-slate-400">
              {checked.size} dari {streams.length} dipilih
            </p>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => setChecked(new Set(streams.map((s) => s.id)))}
                className="min-h-[44px] rounded-md px-2 text-xs font-medium text-accent-300 transition-colors hover:bg-ink-800"
              >
                Pilih semua
              </button>
              <button
                type="button"
                onClick={() => setChecked(new Set())}
                className="min-h-[44px] rounded-md px-2 text-xs font-medium text-slate-400 transition-colors hover:bg-ink-800 hover:text-slate-200"
              >
                Bersihkan
              </button>
            </div>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {streams.map((s) => (
              <label
                key={s.id}
                className="flex min-h-[48px] cursor-pointer items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-ink-800"
              >
                <input
                  type="checkbox"
                  checked={checked.has(s.id)}
                  onChange={() => toggle(s.id)}
                  className="h-5 w-5 shrink-0 accent-accent-500"
                />
                <span className="text-sm text-slate-200">{s.name}</span>
              </label>
            ))}
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
