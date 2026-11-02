"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "../../lib/api";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import type { Stream, User } from "../../lib/types";
import {
  Card,
  EmptyState,
  SectionTitle,
  Spinner,
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
  const offlineCount =
    streams === null || online === null ? null : streams.length - online;

  const diskPct = disk && disk.total > 0 ? (disk.used / disk.total) * 100 : 0;
  const diskTone =
    diskPct > 90 ? "text-bad-400" : diskPct > 70 ? "text-warn-400" : "text-white";
  const diskBar =
    diskPct > 90 ? "bg-bad-400" : diskPct > 70 ? "bg-warn-400" : "bg-accent-500";

  return (
    <div>
      <SectionTitle
        title="Dasbor"
        desc="Status kamera, penyimpanan, dan akses"
      />
      {offlineCount !== null && offlineCount > 0 && (
        <p className="-mt-2 mb-4 text-sm text-warn-400">
          {offlineCount} kamera offline —{" "}
          <Link href="/admin/streams" className="font-medium underline underline-offset-2 hover:text-warn-300">
            periksa di halaman Kamera
          </Link>
        </p>
      )}

      {/* Strip status: satu panel ruang kendali, bukan empat kartu identik. */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl bg-white/10 ring-1 ring-white/10 lg:grid-cols-4">
        <div className="bg-ink-900 p-5">
          <p className="text-xs text-slate-500">Kamera</p>
          <p className="tnum mt-1 text-[28px] font-bold leading-none tracking-tight text-white">
            {streams === null ? "…" : streams.length}
          </p>
          {online !== null && (
            <p className="mt-1.5 text-xs text-slate-500">
              {online} online{offlineCount ? `, ${offlineCount} offline` : ""}
            </p>
          )}
        </div>
        <div className="bg-ink-900 p-5">
          <p className="text-xs text-slate-500">Pengguna</p>
          <p className="tnum mt-1 text-[28px] font-bold leading-none tracking-tight text-white">
            {users === null ? "…" : users.length}
          </p>
        </div>
        <div className="bg-ink-900 p-5">
          <p className="text-xs text-slate-500">API key</p>
          <p className="tnum mt-1 text-[28px] font-bold leading-none tracking-tight text-white">
            {keys === null ? "…" : keys.length}
          </p>
        </div>
        <div className="bg-ink-900 p-5">
          <p className="text-xs text-slate-500">Akses embed</p>
          <p className="tnum mt-1 text-[28px] font-bold leading-none tracking-tight text-white">
            {summary === null ? "…" : summary.total}
          </p>
          <p className="mt-1.5 text-xs text-slate-500">total tercatat</p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <Card>
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-semibold text-white">
              Penyimpanan rekaman
            </h2>
            {disk !== null && (
              <p className={`text-2xl font-bold tabular-nums ${diskTone}`}>
                {diskPct.toFixed(0)}
                <span className="text-xs font-medium text-slate-500">
                  {" "}% terpakai
                </span>
              </p>
            )}
          </div>
          {disk === null ? (
            <Spinner />
          ) : (
            <div className="mt-3">
              <div
                className="h-2 overflow-hidden rounded-full bg-ink-800"
                role="progressbar"
                aria-valuenow={Math.round(diskPct)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Persentase penyimpanan terpakai"
              >
                <div
                  className={`h-full rounded-full transition-all ${diskBar}`}
                  style={{ width: `${Math.min(100, diskPct)}%` }}
                />
              </div>
              <div className="mt-2 flex justify-between text-xs text-slate-400">
                <span className="tabular-nums">{fmtBytes(disk.used)} terpakai</span>
                <span className="tabular-nums">{fmtBytes(disk.free)} bebas</span>
              </div>
              <p className="mt-1 truncate text-xs text-slate-600">{disk.path}</p>
            </div>
          )}
        </Card>

        <Card className="p-0">
          <h2 className="px-4 pt-4 text-sm font-semibold text-white sm:px-5 sm:pt-5">
            Akses embed per API key
          </h2>
          {summary === null ? (
            <Spinner />
          ) : summary.by_key.length === 0 ? (
            <div className="px-4 pb-4 sm:px-5 sm:pb-5">
              <div className="mt-3">
                <EmptyState text="Belum ada akses embed tercatat." />
              </div>
            </div>
          ) : (
            <ul className="mt-1 px-4 pb-2 sm:px-5">
              {summary.by_key.slice(0, 6).map((b) => (
                <li
                  key={b.key_id}
                  className="flex items-center justify-between border-b border-ink-700/40 py-2.5 text-sm transition-colors last:border-0 hover:bg-ink-800/40"
                >
                  <span className="text-slate-300">Key #{b.key_id}</span>
                  <span className="font-semibold tabular-nums text-white">
                    {b.count}×
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
