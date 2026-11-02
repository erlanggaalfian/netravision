"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import type { Stream, User } from "../../lib/types";
import {
  Card,
  EmptyState,
  SectionTitle,
  Spinner,
  Stat,
  fmtBytes,
} from "../../components/ui";

interface DiskRaw {
  path: string;
  total: number;
  used: number;
  free: number;
}

interface LogSummary {
  total: number;
  by_key: { key_id: number; count: number }[];
}

export default function AdminDashboard() {
  const { status } = useCameraStatus();
  const [streams, setStreams] = useState<Stream[] | null>(null);
  const [users, setUsers] = useState<User[] | null>(null);
  const [keys, setKeys] = useState<{ id: number }[] | null>(null);
  const [disk, setDisk] = useState<DiskRaw | null>(null);
  const [summary, setSummary] = useState<LogSummary | null>(null);

  useEffect(() => {
    api.get<Stream[]>("/admin/streams").then(setStreams).catch(() => setStreams([]));
    api.get<User[]>("/admin/users").then(setUsers).catch(() => setUsers([]));
    api.get<{ id: number }[]>("/admin/api-keys").then(setKeys).catch(() => setKeys([]));
    api.get<DiskRaw>("/admin/disks").then(setDisk).catch(() => setDisk(null));
    api
      .get<LogSummary>("/admin/api-access-logs/summary")
      .then(setSummary)
      .catch(() => setSummary(null));
  }, []);

  const online = streams
    ? streams.filter((s) => status.get(s.id) ?? s.is_online).length
    : null;

  const diskPct = disk && disk.total > 0 ? (disk.used / disk.total) * 100 : 0;

  return (
    <div>
      <SectionTitle
        title="Dasbor"
        desc="Ringkasan kondisi sistem NetraVision"
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Kamera"
          value={streams === null ? "…" : streams.length}
          sub={online === null ? undefined : `${online} online`}
        />
        <Stat
          label="Pengguna"
          value={users === null ? "…" : users.length}
        />
        <Stat label="API Key" value={keys === null ? "…" : keys.length} />
        <Stat
          label="Akses embed"
          value={summary === null ? "…" : summary.total}
          sub="total tercatat"
        />
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <Card>
          <h2 className="text-sm font-semibold text-white">Penyimpanan rekaman</h2>
          {disk === null ? (
            <Spinner />
          ) : (
            <div className="mt-3">
              <div className="h-2.5 overflow-hidden rounded-full bg-ink-800">
                <div
                  className={`h-full rounded-full transition-all ${
                    diskPct > 90 ? "bg-bad-400" : diskPct > 70 ? "bg-warn-400" : "bg-accent-500"
                  }`}
                  style={{ width: `${Math.min(100, diskPct)}%` }}
                />
              </div>
              <div className="mt-2 flex justify-between text-xs text-slate-400">
                <span>{fmtBytes(disk.used)} terpakai</span>
                <span>{fmtBytes(disk.free)} bebas</span>
              </div>
              <p className="mt-1 truncate text-xs text-slate-600">{disk.path}</p>
            </div>
          )}
        </Card>

        <Card>
          <h2 className="text-sm font-semibold text-white">
            Akses embed per API key
          </h2>
          {summary === null ? (
            <Spinner />
          ) : summary.by_key.length === 0 ? (
            <div className="mt-3">
              <EmptyState text="Belum ada akses embed tercatat." />
            </div>
          ) : (
            <ul className="mt-3 space-y-2">
              {summary.by_key.slice(0, 6).map((b) => (
                <li
                  key={b.key_id}
                  className="flex items-center justify-between rounded-lg bg-ink-800 px-3 py-2 text-sm"
                >
                  <span className="text-slate-300">Key #{b.key_id}</span>
                  <span className="font-semibold text-white">{b.count}×</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
