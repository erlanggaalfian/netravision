"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "../../lib/api";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import type { Stream, User } from "../../lib/types";
import {
  EmptyState,
  Spinner,
  fmtBytes,
} from "../../components/ui";
import { NBButton, NBCard, NBTitle } from "./_nb";

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

  const tileClass =
    "group relative block cursor-pointer overflow-hidden rounded-xl bg-ink-800 p-5 shadow-sm transition-all duration-150 hover:bg-ink-700 active:scale-[0.98]";
  const chev = (
    <span
      aria-hidden
      className="absolute right-4 top-4 text-slate-400 transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-accent-400"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 6l6 6-6 6" />
      </svg>
    </span>
  );

  return (
    <div>
      <NBTitle
        title="Dasbor"
        desc="Status kamera, penyimpanan, dan akses"
      />
      {offlineCount !== null && offlineCount > 0 && (
        <p className="-mt-2 mb-4 text-sm text-warn-400">
          {offlineCount} kamera offline,{" "}
          <Link href="/admin/streams" className="font-medium underline underline-offset-2 hover:text-warn-300">
            periksa di halaman Kamera
          </Link>
        </p>
      )}

      {/* Strip status: gelembung kaca transparan, bisa diklik ke halaman masing-masing. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Link href="/admin/streams" className={tileClass}>
          {chev}
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
              <circle cx="12" cy="13" r="4" />
            </svg>
            Kamera
          </p>
          <p className="tnum mt-1.5 text-[28px] font-bold leading-none tracking-tight text-white">
            {streams === null ? "…" : streams.length}
          </p>
          {online !== null && (
            <p className="mt-1.5 text-xs text-slate-400">
              {online} online{offlineCount ? `, ${offlineCount} offline` : ""}
            </p>
          )}
        </Link>
        <Link href="/admin/users" className={tileClass}>
          {chev}
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
            Pengguna
          </p>
          <p className="tnum mt-1.5 text-[28px] font-bold leading-none tracking-tight text-white">
            {users === null ? "…" : users.length}
          </p>
        </Link>
        <Link href="/admin/keys" className={tileClass}>
          {chev}
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
            </svg>
            API key
          </p>
          <p className="tnum mt-1.5 text-[28px] font-bold leading-none tracking-tight text-white">
            {keys === null ? "…" : keys.length}
          </p>
        </Link>
        <Link href="/admin/keys" className={tileClass}>
          {chev}
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <rect x="2" y="3" width="20" height="14" rx="2" />
              <path d="M8 21h8M12 17v4" />
            </svg>
            Akses embed
          </p>
          <p className="tnum mt-1.5 text-[28px] font-bold leading-none tracking-tight text-white">
            {summary === null ? "…" : summary.total}
          </p>
          <p className="mt-1.5 text-xs text-slate-400">total tercatat</p>
        </Link>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <NBCard>
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-lg font-bold tracking-tight text-white">
              Penyimpanan rekaman
            </h2>
            {disk !== null && (
              <p className={`text-2xl font-bold tabular-nums ${diskTone}`}>
                {diskPct.toFixed(0)}
                <span className="text-xs font-medium text-slate-400">
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
              <p className="mt-1 truncate text-xs text-slate-400">{disk.path}</p>
            </div>
          )}
        </NBCard>

        <NBCard className="p-0">
          <h2 className="px-4 pt-4 text-lg font-bold tracking-tight text-white sm:px-5 sm:pt-5">
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
                  className="flex items-center justify-between border-b border-ink-800 py-2.5 text-sm transition-colors last:border-0 hover:bg-ink-800"
                >
                  <span className="text-slate-300">Key #{b.key_id}</span>
                  <span className="font-semibold tabular-nums text-white">
                    {b.count}×
                  </span>
                </li>
              ))}
            </ul>
          )}
        </NBCard>
      </div>
    </div>
  );
}
