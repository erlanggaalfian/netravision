"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { Group, Stream } from "../../../lib/types";
import {
  Accordion,
  Button,
  EmptyState,
  ErrorBox,
  Field,
  Modal,
  SectionTitle,
  Spinner,
  TextArea,
  TextInput,
} from "../../../components/ui";

export default function AdminGroupsPage() {
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
    api.get<Stream[]>("/admin/streams").then(setStreams).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <SectionTitle
        title="Grup Wilayah"
        desc="Kelompokkan kamera per area dan atur cakupannya"
        action={<Button onClick={() => setShowAdd(true)}>+ Tambah Grup</Button>}
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {groups === null ? (
        <Spinner />
      ) : groups.length === 0 ? (
        <EmptyState text="Belum ada grup. Tambahkan yang pertama." />
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
            const actions = (
              <Button
                variant="subtle"
                onClick={() => setGrantsFor(g)}
                className="min-h-[40px] px-3"
              >
                Kelola Kamera
              </Button>
            );
            return (
              <div key={g.id}>
                <div className="md:hidden">
                  <Accordion summary={summary}>
                    <div>{actions}</div>
                  </Accordion>
                </div>
                <div className="hidden items-center justify-between gap-3 rounded-xl border border-ink-700/60 bg-ink-900 px-4 py-3 md:flex">
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
        <Field label="Nama grup">
          <TextInput
            placeholder="cth: Gedung A"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Deskripsi (opsional)">
          <TextArea
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <Button onClick={save} disabled={busy || !name.trim()} className="w-full">
          {busy ? "Menyimpan…" : "Simpan"}
        </Button>
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
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<{ stream_ids: number[] }>(
        `/admin/groups/${encodeURIComponent(group.name)}/camera-grants`,
      )
      .then((r) => setChecked(new Set(r.stream_ids)))
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat"),
      )
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
    <Modal title={`Kamera grup — ${group.name}`} onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {!loaded ? (
        <Spinner />
      ) : streams.length === 0 ? (
        <EmptyState text="Belum ada kamera." />
      ) : (
        <div className="space-y-1">
          {streams.map((s) => (
            <label
              key={s.id}
              className="flex min-h-[48px] cursor-pointer items-center gap-3 rounded-lg px-3 py-2 hover:bg-ink-800"
            >
              <input
                type="checkbox"
                checked={checked.has(s.id)}
                onChange={() => toggle(s.id)}
                className="h-5 w-5 shrink-0 accent-blue-500"
              />
              <span className="text-sm text-slate-200">{s.name}</span>
            </label>
          ))}
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Batal
        </Button>
        <Button onClick={save} disabled={busy || !loaded}>
          {busy ? "Menyimpan…" : "Simpan"}
        </Button>
      </div>
    </Modal>
  );
}
