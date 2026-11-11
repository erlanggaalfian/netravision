"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import type { Group, Stream } from "../../../lib/types";
import { ErrorBox, Modal, Spinner } from "../../../components/ui";
import {
  NBAccordion,
  NBButton,
  NBEmptyState,
  NBField,
  NBInput,
  NBTextArea,
  NBTitle,
} from "../_nb";

function GroupIcon({ className = "" }: { className?: string }) {
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
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}



export default function AdminGroupsPage() {
  const { user: me } = useAuth();
  /* E-S1: Tambah Grup dan Kelola Kamera hanya super_admin;
     backend sudah super_admin_only untuk keduanya. */
  const isSuperAdmin = me?.role === "super_admin";
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [grantsFor, setGrantsFor] = useState<Group | null>(null);

  const load = () =>
    api
      .get<Group[]>("/admin/groups")
      .then(setGroups)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "Gagal memuat grup");
        setGroups([]);
      });

  useEffect(() => {
    load();
    api.get<Stream[]>("/admin/streams").then((d) => setStreams(d ?? [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <NBTitle
        title="Grup Wilayah"
        desc="Kelompokkan kamera per area dan atur cakupannya"
        action={
          isSuperAdmin ? (
            <NBButton onClick={() => setShowAdd(true)}>+ Tambah Grup</NBButton>
          ) : undefined
        }
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {groups === null ? (
        <Spinner />
      ) : groups.length === 0 ? (
        <NBEmptyState icon={<GroupIcon className="h-8 w-8 text-slate-500" />} text="Belum ada grup. Tambahkan yang pertama." />
      ) : (
        <div className="space-y-2">
          {groups.map((g) => {
            const summary = (
              <span className="block min-w-0">
                <span className="block truncate font-medium text-white">
                  {g.name}
                </span>
                {g.description && (
                  <span className="block truncate text-sm text-slate-400">
                    {g.description}
                  </span>
                )}
              </span>
            );
            const actions = isSuperAdmin ? (
              <NBButton
                variant="secondary"
                onClick={() => setGrantsFor(g)}
                className="px-3"
              >
                Kelola Kamera
              </NBButton>
            ) : null;
            return (
              <div key={g.id}>
                <div className="md:hidden">
                  <NBAccordion summary={summary}>
                    <div>{actions}</div>
                  </NBAccordion>
                </div>
                <div className="nv-panel-modern hidden items-center justify-between gap-3 px-4 py-3 transition-colors md:flex">
                  {summary}
                  {actions}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showAdd && (
        <AddGroupModal
          onClose={() => setShowAdd(false)}
          onDone={() => {
            setShowAdd(false);
            load();
          }}
        />
      )}
      {grantsFor && (
        <GrantsModal
          group={grantsFor}
          streams={streams}
          onClose={() => setGrantsFor(null)}
        />
      )}
    </div>
  );
}

function AddGroupModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setError("");
    setBusy(true);
    try {
      await api.put(`/admin/groups/${encodeURIComponent(name.trim())}`, {
        name: name.trim(),
        description: description.trim() || null,
      });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Tambah Grup" onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="space-y-4">
        <NBField label="Nama grup">
          <NBInput
            placeholder="cth: Gedung A"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </NBField>
        <NBField label="Deskripsi (opsional)">
          <NBTextArea
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </NBField>
        <NBButton onClick={save} disabled={busy || !name.trim()} className="w-full">
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}

function GrantsModal({
  group,
  streams,
  onClose,
}: {
  group: Group;
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
      .get<{ stream_ids: number[] }>(
        `/admin/groups/${encodeURIComponent(group.name)}/camera-grants`,
      )
      .then((r) => setChecked(new Set(r.stream_ids)))
      .catch((e) => {
        setLoadFailed(true);
        setError(e instanceof ApiError ? e.message : "Gagal memuat");
      })
      .finally(() => setLoaded(true));
  }, [group.name]);

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
      await api.post(
        `/admin/groups/${encodeURIComponent(group.name)}/camera-grants`,
        { stream_ids: [...checked] },
      );
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Kamera grup: ${group.name}`} onClose={onClose} wide>
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
              <NBButton
                variant="secondary"
                onClick={() => setChecked(new Set(streams.map((s) => s.id)))}
                className="shrink-0 whitespace-nowrap px-2.5 text-xs sm:text-sm"
              >
                Pilih semua
              </NBButton>
              <NBButton
                variant="secondary"
                onClick={() => setChecked(new Set())}
                className="shrink-0 whitespace-nowrap px-2.5 text-xs sm:text-sm"
              >
                Bersihkan
              </NBButton>
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
