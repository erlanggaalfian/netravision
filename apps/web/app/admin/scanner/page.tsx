"use client";

import { useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { Stream, SubnetHost } from "../../../lib/types";
import {
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  SectionTitle,
  TextInput,
} from "../../../components/ui";

type Tone = "ok" | "bad" | "warn" | "info" | "muted";
const SCAN_STATUS: Record<string, { label: string; tone: Tone }> = {
  video: { label: "Video", tone: "ok" },
  no_video: { label: "Tanpa video", tone: "warn" },
  auth_failed: { label: "Login salah", tone: "bad" },
  not_found: { label: "Tidak ada", tone: "muted" },
  timeout: { label: "Timeout", tone: "muted" },
  error: { label: "Gagal", tone: "muted" },
  unreachable: { label: "Tidak terjangkau", tone: "muted" },
};

function mainInfo(h: SubnetHost): string {
  const p = h.paths.find((x) => x.role === "main");
  if (!p?.width || !p.height) return p?.path ?? "";
  const parts = [`${p.width}×${p.height}`];
  if (p.fps) parts.push(`${p.fps} fps`);
  return parts.join(" · ");
}

export default function AdminScannerPage() {
  const [ipRange, setIpRange] = useState("192.168.1.0/24");
  const [port, setPort] = useState("554");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [scanning, setScanning] = useState(false);
  const [hosts, setHosts] = useState<SubnetHost[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(0);
  const [error, setError] = useState("");

  const key = (h: SubnetHost) => `${h.host}:${h.port}`;
  const selectable = (hosts ?? []).filter((h) => h.status === "video");

  async function doScan() {
    setError("");
    setScanning(true);
    setHosts(null);
    setChecked(new Set());
    setAdded(0);
    try {
      const res = await api.post<{ hosts: SubnetHost[] }>("/admin/scan-subnet", {
        ip_range: ipRange.trim(),
        port: parseInt(port, 10) || 554,
        username: username.trim(),
        password,
      });
      setHosts(res.hosts);
      if (res.hosts.length === 0)
        setError("Tidak ada kamera ditemukan di subnet ini.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan gagal");
    } finally {
      setScanning(false);
    }
  }

  function toggle(h: SubnetHost) {
    const k = key(h);
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  function toggleAll() {
    if (checked.size === selectable.length) setChecked(new Set());
    else setChecked(new Set(selectable.map(key)));
  }

  async function addSelected() {
    const selected = selectable.filter((h) => checked.has(key(h)));
    if (selected.length === 0) return;
    setError("");
    setAdding(true);
    let ok = 0;
    for (const h of selected) {
      try {
        // force: path sudah diverifikasi video saat scan.
        await api.post<Stream>("/admin/streams", {
          name: `Kamera ${h.host}`,
          rtsp_url: h.best_main,
          storage_mode: "local",
          force: true,
        });
        ok++;
      } catch (e) {
        setError(
          e instanceof ApiError
            ? `Gagal menambah ${h.host}: ${e.message}`
            : `Gagal menambah ${h.host}`,
        );
        break;
      }
    }
    setAdded(ok);
    setAdding(false);
  }

  function HostRow({ h }: { h: SubnetHost }) {
    const st = SCAN_STATUS[h.status] ?? SCAN_STATUS.error;
    const canPick = h.status === "video";
    const checkbox = (
      <input
        type="checkbox"
        checked={checked.has(key(h))}
        onChange={() => toggle(h)}
        disabled={!canPick}
        className="h-5 w-5 shrink-0 accent-accent-500 disabled:opacity-40"
        aria-label={`Pilih ${h.host}`}
      />
    );
    return (
      <>
        {/* Mobile: kartu */}
        <li className="flex items-start gap-3 rounded-xl border border-ink-700 bg-ink-950 p-3 md:hidden">
          {checkbox}
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-sm text-white">
              {h.host}:{h.port}
            </p>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              {h.best_main ? mainInfo(h) : "tanpa video"}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              <Badge tone={st.tone}>{st.label}</Badge>
            </div>
          </div>
        </li>
        {/* Desktop: baris tabel */}
        <tr key={key(h)} className="hidden hover:bg-white/[0.02] md:table-row">
          <td className="px-3 py-3">{checkbox}</td>
          <td className="px-3 py-3 font-mono text-white">{h.host}</td>
          <td className="px-3 py-3 font-mono text-slate-400">{h.port}</td>
          <td className="px-3 py-3">
            <Badge tone={st.tone}>{st.label}</Badge>
          </td>
          <td className="max-w-[280px] truncate px-3 py-3 font-mono text-xs text-slate-400">
            {h.best_main ?? "—"}
          </td>
          <td className="px-3 py-3 text-xs text-slate-400">{mainInfo(h)}</td>
        </tr>
      </>
    );
  }

  return (
    <div>
      <SectionTitle
        title="Camera Scanner"
        desc="Pindai subnet jaringan lokal untuk menemukan kamera (maks 256 host)"
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      <Card className="mb-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="IP Subnet (CIDR)" hint="cth: 192.168.1.0/24">
            <TextInput
              value={ipRange}
              onChange={(e) => setIpRange(e.target.value)}
              placeholder="192.168.1.0/24"
              className="font-mono"
            />
          </Field>
          <Field label="Port RTSP">
            <TextInput
              value={port}
              onChange={(e) => setPort(e.target.value)}
              inputMode="numeric"
              className="font-mono"
            />
          </Field>
          <Field label="Username">
            <TextInput
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
            />
          </Field>
          <Field label="Password">
            <TextInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
          <div className="flex items-end">
            <Button onClick={doScan} disabled={scanning} className="w-full sm:w-auto">
              {scanning ? "Memindai…" : "Scan Network"}
            </Button>
          </div>
        </div>

        {scanning && (
          <div className="mt-5 space-y-2 border-t border-ink-700 pt-4">
            <div className="flex justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              <span>Memindai {ipRange}…</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-ink-700">
              <div className="nv-scanbar h-full rounded-full bg-accent-500" />
            </div>
            <style>{`.nv-scanbar{width:40%;animation:nvscan 1.2s ease-in-out infinite}@keyframes nvscan{0%{margin-left:-40%}100%{margin-left:100%}}`}</style>
          </div>
        )}
      </Card>

      {hosts !== null && !scanning && (
        <Card>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-white">
              Host terdeteksi{" "}
              <span className="text-slate-400">({hosts.length})</span>
            </h3>
            {selectable.length > 0 && (
              <Button
                variant="subtle"
                onClick={addSelected}
                disabled={adding || checked.size === 0}
              >
                {adding
                  ? "Menambah…"
                  : `+ Tambah terpilih (${checked.size})`}
              </Button>
            )}
          </div>
          {added > 0 && (
            <p className="mb-3 text-sm text-emerald-400">
              {added} kamera berhasil ditambahkan. Lihat di tab Kamera.
            </p>
          )}
          {hosts.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              Tidak ada kamera yang merespons di subnet ini.
            </p>
          ) : (
            <>
              {/* Mobile: daftar kartu */}
              <ul className="space-y-2 md:hidden">
                {hosts.map((h) => (
                  <HostRow key={key(h)} h={h} />
                ))}
              </ul>
              {/* Desktop: tabel */}
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-ink-700 text-xs uppercase tracking-wider text-slate-500">
                      <th scope="col" className="w-10 px-3 py-3">
                        <input
                          type="checkbox"
                          checked={
                            selectable.length > 0 &&
                            checked.size === selectable.length
                          }
                          onChange={toggleAll}
                          className="h-5 w-5 accent-accent-500"
                          aria-label="Pilih semua"
                        />
                      </th>
                      <th scope="col" className="px-3 py-3 font-semibold">IP</th>
                      <th scope="col" className="px-3 py-3 font-semibold">Port</th>
                      <th scope="col" className="px-3 py-3 font-semibold">Status</th>
                      <th scope="col" className="px-3 py-3 font-semibold">Path main</th>
                      <th scope="col" className="px-3 py-3 font-semibold">Video</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-700/60">
                    {hosts.map((h) => (
                      <HostRow key={key(h)} h={h} />
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      )}
      {hosts === null && !scanning && !error && (
        <p className="py-10 text-center text-sm text-slate-500">
          Isi subnet lalu tekan “Scan Network” untuk mulai memindai.
        </p>
      )}
    </div>
  );
}
