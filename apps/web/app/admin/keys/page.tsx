"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { ApiKey, Stream } from "../../../lib/types";
import {
  Badge,
  Button,
  Card,
  ConfirmModal,
  EmptyState,
  ErrorBox,
  Field,
  Modal,
  SectionTitle,
  Spinner,
  TextInput,
} from "../../../components/ui";

interface KeyOut extends ApiKey {
  domain_lock: string | null;
  is_active: boolean;
  stream_ids: number[];
}

interface CreatedKey extends KeyOut {
  key: string;
}

interface AccessLog {
  id: number;
  key_id: number | null;
  stream_id: number | null;
  ip: string | null;
  accessed_at: string | null;
}

export default function AdminKeysPage() {
  const [keys, setKeys] = useState<KeyOut[] | null>(null);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [logs, setLogs] = useState<AccessLog[] | null>(null);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [deleting, setDeleting] = useState<KeyOut | null>(null);

  const load = () => {
    api
      .get<KeyOut[]>("/admin/api-keys")
      .then(setKeys)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "Gagal memuat API key");
        setKeys([]);
      });
    api
      .get<AccessLog[]>("/admin/api-access-logs?limit=30")
      .then(setLogs)
      .catch(() => setLogs([]));
  };

  useEffect(() => {
    load();
    api.get<Stream[]>("/admin/streams").then(setStreams).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggleActive(k: KeyOut) {
    try {
      await api.put(`/admin/api-keys/${k.id}`, { is_active: !k.is_active });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memperbarui");
    }
  }

  async function doDelete() {
    if (!deleting) return;
    try {
      await api.del(`/admin/api-keys/${deleting.id}`);
      setDeleting(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus");
    }
  }

  return (
    <div>
      <SectionTitle
        title="API Key"
        desc="Kunci embed untuk pihak ketiga — key penuh hanya tampil sekali saat dibuat"
        action={<Button onClick={() => setShowAdd(true)}>+ Buat Key</Button>}
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {keys === null ? (
        <Spinner />
      ) : keys.length === 0 ? (
        <EmptyState text="Belum ada API key." />
      ) : (
        <div className="space-y-2">
          {keys.map((k) => (
            <Card key={k.id} className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-white">{k.name}</p>
                  <p className="mt-1 flex flex-wrap gap-1.5">
                    <Badge tone={k.is_active ? "ok" : "muted"}>
                      {k.is_active ? "Aktif" : "Nonaktif"}
                    </Badge>
                    <Badge tone="muted">{k.stream_ids.length} kamera</Badge>
                    {k.domain_lock && (
                      <Badge tone="info">{k.domain_lock}</Badge>
                    )}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Terakhir dipakai: {k.last_used_at ?? "belum pernah"}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="subtle"
                    onClick={() => toggleActive(k)}
                    className="min-h-[40px] px-3"
                  >
                    {k.is_active ? "Nonaktifkan" : "Aktifkan"}
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => setDeleting(k)}
                    className="min-h-[40px] px-3"
                  >
                    Hapus
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <h2 className="mb-3 mt-8 text-lg font-semibold text-white">
        Log akses terakhir
      </h2>
      {logs === null ? (
        <Spinner />
      ) : logs.length === 0 ? (
        <EmptyState text="Belum ada akses tercatat." />
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-ink-700 text-left text-xs uppercase tracking-wider text-slate-500">
                <th className="px-4 py-2.5 font-medium">Waktu</th>
                <th className="px-4 py-2.5 font-medium">Key</th>
                <th className="px-4 py-2.5 font-medium">Stream</th>
                <th className="px-4 py-2.5 font-medium">IP</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b border-ink-700/40 last:border-0">
                  <td className="px-4 py-2.5 text-slate-300">
                    {l.accessed_at ? new Date(l.accessed_at).toLocaleString("id-ID") : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">#{l.key_id ?? "—"}</td>
                  <td className="px-4 py-2.5 text-slate-400">#{l.stream_id ?? "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-400">
                    {l.ip ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {showAdd && (
        <AddKeyModal
          streams={streams}
          onClose={() => setShowAdd(false)}
          onCreated={(k) => {
            setShowAdd(false);
            setCreated(k);
            load();
          }}
        />
      )}
      {created && (
        <Modal title="API key dibuat" onClose={() => setCreated(null)}>
          <ErrorBox message="Salin key ini sekarang — tidak akan ditampilkan lagi." />
          <p className="mt-3 break-all rounded-lg bg-ink-950 p-3 font-mono text-sm text-accent-300">
            {created.key}
          </p>
          <div className="mt-5 flex justify-end">
            <Button onClick={() => setCreated(null)}>Selesai</Button>
          </div>
        </Modal>
      )}
      {deleting && (
        <ConfirmModal
          title="Hapus API key"
          message={`Hapus key "${deleting.name}"? Embed yang memakainya ikut mati.`}
          onCancel={() => setDeleting(null)}
          onConfirm={doDelete}
        />
      )}
    </div>
  );
}

function AddKeyModal({
  streams,
  onClose,
  onCreated,
}: {
  streams: Stream[];
  onClose: () => void;
  onCreated: (k: CreatedKey) => void;
}) {
  const [name, setName] = useState("");
  const [domainLock, setDomainLock] = useState("");
  const [password, setPassword] = useState("");
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
      const res = await api.post<CreatedKey>("/admin/api-keys", {
        name: name.trim(),
        stream_ids: [...checked],
        domain_lock: domainLock.trim() || null,
        password: password || null,
      });
      onCreated(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal membuat key");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Buat API Key" onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="space-y-4">
        <Field label="Nama key">
          <TextInput
            placeholder="cth: Website mitra"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Kunci domain (opsional)" hint="cth: mitra.or.id">
            <TextInput
              value={domainLock}
              onChange={(e) => setDomainLock(e.target.value)}
            />
          </Field>
          <Field label="Kata sandi embed (opsional)">
            <TextInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Kamera yang boleh diakses">
          <div className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-ink-700 p-2">
            {streams.map((s) => (
              <label
                key={s.id}
                className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-lg px-2 hover:bg-ink-800"
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
        </Field>
        <Button
          onClick={save}
          disabled={busy || !name.trim() || checked.size === 0}
          className="w-full"
        >
          {busy ? "Membuat…" : "Buat Key"}
        </Button>
      </div>
    </Modal>
  );
}
