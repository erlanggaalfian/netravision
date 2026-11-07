"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
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
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [accessFor, setAccessFor] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);

  /* Daftar grup yang sudah ada (untuk pilihan di form). */
  const groups = useMemo(
    () =>
      [...new Set((users ?? []).map((u) => u.admin_group).filter((g): g is string => !!g))].sort(),
    [users],
  );
  const [groupEdit, setGroupEdit] = useState<{
    name: string;
    members: User[];
  } | null>(null);
  /* Pilihan massal ala Kamera: checkbox per baris + bar bulk. */
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showGroup, setShowGroup] = useState(false);
  /* Grup yang sedang terbuka lipatannya (tertutup dulu). */
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());

  function toggleGroup(name: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllPage() {
    const ids = (users ?? []).map((u) => u.id);
    const allChecked = ids.length > 0 && ids.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allChecked) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  /* Konsep v2: akun bergrup dikelompokkan di bawah satu baris induk
     bernama grupnya; yang tanpa grup berdiri sendiri. Grup lebih
     dahulu (urut nama), lalu akun lepas. Anggota diurutkan supaya
     pengelolanya di atas: admin dulu, lalu sisanya menurut nama. */
  const { perGrup, lepas } = useMemo(() => {
    const map = new Map<string, User[]>();
    const free: User[] = [];
    (users ?? []).forEach((u) => {
      if (!u.admin_group) {
        free.push(u);
        return;
      }
      const list = map.get(u.admin_group) ?? [];
      list.push(u);
      map.set(u.admin_group, list);
    });
    const bobot = (r: string) =>
      r === "super_admin" || r === "admin" ? 0 : 1;
    map.forEach((list) =>
      list.sort(
        (a, b) =>
          bobot(a.role) - bobot(b.role) ||
          a.username.localeCompare(b.username),
      ),
    );
    return {
      perGrup: [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])),
      lepas: free,
    };
  }, [users]);

  /* Satu baris pengguna. Anggota grup tidak menampilkan lencana iklan:
     iklan diatur serentak di baris induk grup, dan nama grup sudah
     tertulis di sana (paritas v2.0). */
  /* Checkbox dan aksi dipakai baris lepas maupun anggota grup. */
  function checkboxFor(u: User) {
    return (
      <input
        type="checkbox"
        checked={selected.has(u.id)}
        onChange={() => toggleSelect(u.id)}
        onClick={(e) => e.stopPropagation()}
        className="h-5 w-5 shrink-0 accent-accent-500"
        aria-label={`Pilih ${u.username}`}
      />
    );
  }

  function actionsFor(u: User) {
    return (
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
  }

  function roleBadge(u: User) {
    return (
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
    );
  }

  function renderUser(u: User) {
    const summary = (
      <span className="flex min-w-0 flex-1 items-center gap-3">
        {checkboxFor(u)}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-white">
            {u.username}
          </span>
          <span className="mt-0.5 flex flex-wrap gap-1">
            {roleBadge(u)}
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
    const actions = actionsFor(u);
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
  }

  /* Anggota grup: baris datar di dalam kartu grupnya (tanpa kartu
     bersarang), dipisah garis halus; aksi tampil langsung, HP menumpuk
     di bawah nama, desktop sejajar kanan seperti baris lepas. */
  function renderMember(u: User) {
    return (
      <div key={u.id} className="py-3">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            {checkboxFor(u)}
            <span className="min-w-0">
              <span className="block truncate font-medium text-white">
                {u.username}
              </span>
              <span className="mt-0.5 flex flex-wrap gap-1">{roleBadge(u)}</span>
              <span className="mt-1 block text-xs text-slate-400">
                Dibuat oleh: {u.dibuat_oleh ?? "—"}
              </span>
            </span>
          </div>
          <div className="flex flex-wrap gap-2 pl-8 md:pl-0">
            {actionsFor(u)}
          </div>
        </div>
      </div>
    );
  }

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
        <>
          {/* Bar bulk ala Kamera */}
          {selected.size > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-ink-800 shadow-sm px-4 py-3">
              <span className="text-sm text-slate-300">
                {selected.size} dipilih
              </span>
              <NBButton
                variant="secondary"
                onClick={() => setShowGroup(true)}
              >
                Set grup ({selected.size})
              </NBButton>
              <button
                type="button"
                onClick={() => setSelected(new Set())}
                className="inline-flex min-h-[44px] items-center rounded-lg px-3 text-sm text-slate-400 hover:text-slate-200"
              >
                Batalkan pilihan
              </button>
            </div>
          )}
          <div className="mb-2 flex items-center gap-3 px-1">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-400">
              <input
                type="checkbox"
                checked={
                  (users?.length ?? 0) > 0 &&
                  (users ?? []).every((u) => selected.has(u.id))
                }
                onChange={toggleSelectAllPage}
                className="h-5 w-5 accent-accent-500"
              />
              Pilih semua di halaman ini
            </label>
          </div>
          <div className="space-y-2">
          {perGrup.map(([name, members]) => {
            const allAds =
              members.length > 0 && members.every((m) => m.show_ads);
            const open = openGroups.has(name);
            return (
              <div
                key={name}
                className="overflow-hidden rounded-xl bg-ink-800 shadow-sm"
              >
                <div className="flex items-center gap-2 px-4 py-3">
                  <button
                    onClick={() => toggleGroup(name)}
                    aria-expanded={open}
                    className="flex min-h-[44px] min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-lg px-2 py-1 text-left transition-colors hover:bg-ink-700/40"
                  >
                    <NBBadge tone="info">Grup</NBBadge>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-white">
                        {name}
                      </span>
                      <span className="mt-0.5 block text-xs text-slate-400">
                        {members.length} anggota
                      </span>
                    </span>
                    <NBBadge tone={allAds ? "ok" : "muted"}>
                      Iklan: {allAds ? "Ya" : "Tidak"}
                    </NBBadge>
                  </button>
                  <NBButton
                    variant="secondary"
                    onClick={() => setGroupEdit({ name, members })}
                    className="shrink-0 px-3"
                  >
                    Ubah grup
                  </NBButton>
                  <button
                    onClick={() => toggleGroup(name)}
                    aria-expanded={open}
                    aria-label={open ? "Tutup grup" : "Buka grup"}
                    className="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-ink-700/40"
                  >
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 16 16"
                      fill="none"
                      aria-hidden
                      className={`shrink-0 text-slate-400 transition-transform duration-200 ease-out ${open ? "rotate-180" : ""}`}
                    >
                      <path
                        d="M4 6l4 4 4-4"
                        stroke="currentColor"
                        strokeWidth="1.75"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                </div>
                {open && (
                  <div className="border-t border-ink-800 px-4 pb-2">
                    <div className="divide-y divide-ink-800">
                      {members.map((u) => renderMember(u))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {lepas.map((u) => renderUser(u))}
          </div>
        </>
      )}

      {showAdd && (
        <UserFormModal
          me={me}
          groups={groups}
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
          me={me}
          groups={groups}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            load();
          }}
        />
      )}
      {groupEdit && (
        <GroupEditModal
          name={groupEdit.name}
          members={groupEdit.members}
          me={me}
          onClose={() => setGroupEdit(null)}
          onDone={() => {
            setGroupEdit(null);
            load();
          }}
        />
      )}
      {showGroup && (
        <BulkGroupModal
          count={selected.size}
          groups={groups}
          onClose={() => setShowGroup(false)}
          onDone={async (groupName) => {
            /* admin_group hanya string di akun: set ke pengguna
               terpilih tidak menghapus anggota lama grup. */
            await Promise.all(
              [...selected].map((id) =>
                api.put(`/admin/users/${id}`, { admin_group: groupName }),
              ),
            );
            setShowGroup(false);
            setSelected(new Set());
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
  me,
  groups,
  onClose,
  onDone,
}: {
  user?: User;
  me: User | null;
  groups: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<string>(user?.role ?? "user");
  const [group, setGroup] = useState(user?.admin_group ?? "");
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
          admin_group: group.trim() || null,
        };
        if (password) body.password = password;
        await api.put(`/admin/users/${user.id}`, body);
      } else {
        await api.post("/admin/users", {
          username: username.trim(),
          password,
          role,
          show_ads: showAds,
          admin_group: group.trim() || null,
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
        <NBField
          label="Grup"
          hint={
            me?.role === "super_admin"
              ? "Kelompok wilayah akun ini (kosong = tanpa grup)"
              : "Mengikuti grup Anda"
          }
        >
          <NBInput
            value={me?.role === "super_admin" ? group : (me?.admin_group ?? "")}
            onChange={(e) => setGroup(e.target.value)}
            disabled={me?.role !== "super_admin"}
            placeholder="cth. grup-jakarta"
            list="grup-wilayah"
          />
          <datalist id="grup-wilayah">
            {groups.map((g) => (
              <option key={g} value={g} />
            ))}
          </datalist>
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

/* ---------- Modal massal: set grup ala Kamera ---------- */

function BulkGroupModal({
  count,
  groups,
  onClose,
  onDone,
}: {
  count: number;
  groups: string[];
  onClose: () => void;
  onDone: (groupName: string) => Promise<void>;
}) {
  const NEW = "__baru__";
  const [picked, setPicked] = useState(groups[0] ?? NEW);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const name = picked === NEW ? newName.trim() : picked;
  const valid = name !== "";

  return (
    <Modal title={`Set grup (${count} pengguna)`} onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <NBField label="Grup">
        <NBSelect value={picked} onChange={(e) => setPicked(e.target.value)}>
          {groups.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
          <option value={NEW}>+ Grup baru…</option>
        </NBSelect>
      </NBField>
      {picked === NEW && (
        <div className="mt-3">
          <NBField label="Nama grup baru">
            <NBInput
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="cth. Lantai 1"
            />
          </NBField>
        </div>
      )}
      <p className="mt-3 text-xs leading-relaxed text-slate-400">
        Pengguna terpilih ditambahkan ke grup. Pengguna yang sudah ada di
        grup tetap dipertahankan.
      </p>
      <NBButton
        className="mt-4 w-full"
        disabled={!valid || busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onDone(name);
          } catch (e) {
            setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Menyimpan…" : "Tambahkan ke grup"}
      </NBButton>
    </Modal>
  );
}

/* ---------- Modal: ubah nama grup + iklan serentak seisi grup ---------- */

function GroupEditModal({
  name,
  members,
  me,
  onClose,
  onDone,
}: {
  name: string;
  members: User[];
  me: User | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [newName, setNewName] = useState(name);
  const [adsOn, setAdsOn] = useState(members.every((m) => m.show_ads));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /* Hanya superadmin yang bisa mengubah nama grup; admin biasa
     terkunci di grupnya sendiri (aturan yang sama seperti form). */
  const canRename = me?.role === "super_admin";
  const nameChanged = newName.trim() !== "" && newName.trim() !== name;
  const adsChanged = members.some((m) => m.show_ads !== adsOn);
  const valid = newName.trim() !== "" && (nameChanged || adsChanged);

  async function save() {
    setError("");
    setBusy(true);
    try {
      const target = newName.trim();
      await Promise.all(
        members.map(async (m) => {
          const body: Record<string, unknown> = {};
          if (nameChanged) body.admin_group = target;
          if (m.show_ads !== adsOn) body.show_ads = adsOn;
          if (Object.keys(body).length > 0) {
            await api.put(`/admin/users/${m.id}`, body);
          }
        }),
      );
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Ubah grup — ${name}`} onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="space-y-4">
        <NBField
          label="Nama grup"
          hint={
            canRename
              ? undefined
              : "Hanya superadmin yang bisa mengubah nama grup"
          }
        >
          <NBInput
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            disabled={!canRename}
          />
        </NBField>
        <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 rounded-xl bg-ink-800 shadow-sm px-4 py-3">
          <span>
            <span className="block text-sm font-medium text-white">
              Tampilkan Iklan
            </span>
            <span className="block text-xs text-slate-400">
              Banner iklan tampil untuk semua anggota grup ini
            </span>
          </span>
          <input
            type="checkbox"
            checked={adsOn}
            onChange={(e) => setAdsOn(e.target.checked)}
            className="h-5 w-5 shrink-0 accent-accent-500"
            aria-label="Tampilkan Iklan untuk grup"
          />
        </label>
        <p className="text-xs text-slate-400">{members.length} anggota</p>
        <NBButton onClick={save} disabled={busy || !valid} className="w-full">
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
