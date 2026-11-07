"use client";

import { useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { Stream, SubnetHost } from "../../../lib/types";
import { ErrorBox } from "../../../components/ui";
import { NBBadge, NBButton, NBCard, NBField, NBInput, NBTitle, NBTableWrap, NBTh, NBTd, NBTr } from "../_nb";

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
        <li className="flex items-start gap-3 rounded-xl bg-ink-800 shadow-sm p-3 md:hidden">
          {checkbox}
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-sm text-white">
              {h.host}:{h.port}
            </p>
            <p className="mt-0.5 truncate text-xs text-slate-400">
              {h.best_main ? mainInfo(h) : "tanpa video"}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              <NBBadge tone={st.tone}>{st.label}</NBBadge>
            </div>
          </div>
        </li>
        {/* Desktop: baris tabel */}
        <NBTr key={key(h)} className="hidden md:table-row">
          <NBTd>{checkbox}</NBTd>
          <NBTd className="font-mono">{h.host}</NBTd>
          <NBTd className="font-mono">{h.port}</NBTd>
          <NBTd>
            <NBBadge tone={st.tone}>{st.label}</NBBadge>
          </NBTd>
          <NBTd className="max-w-[280px] truncate font-mono text-xs">
            {h.best_main ?? "—"}
          </NBTd>
          <NBTd className="text-xs">{mainInfo(h)}</NBTd>
        </NBTr>
      </>
    );
  }

  return (
    <div>
      <NBTitle
        title="Camera Scanner"
        desc="Pindai subnet jaringan lokal untuk menemukan kamera (maks 256 host)"
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      <NBCard className="mb-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          <NBField label="IP Subnet (CIDR)" hint="cth: 192.168.1.0/24">
            <NBInput
              value={ipRange}
              onChange={(e) => setIpRange(e.target.value)}
              placeholder="192.168.1.0/24"
              className="font-mono"
            />
          </NBField>
          <NBField label="Port RTSP">
            <NBInput
              value={port}
              onChange={(e) => setPort(e.target.value)}
              inputMode="numeric"
              className="font-mono"
            />
          </NBField>
          <NBField label="Username">
            <NBInput
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
            />
          </NBField>
          <NBField label="Password">
            <NBInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
          </NBField>
          <div className="flex items-end">
            <NBButton onClick={doScan} disabled={scanning} className="w-full sm:w-auto">
              {scanning ? "Memindai…" : "Scan Network"}
            </NBButton>
          </div>
        </div>

        {scanning && (
          <div className="mt-5 space-y-2 border-t border-ink-800 pt-4">
            <div className="flex justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <span>Memindai {ipRange}…</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-ink-700">
              <div className="nv-scanbar h-full rounded-full bg-accent-500" />
            </div>
            <style>{`.nv-scanbar{width:40%;animation:nvscan 1.2s ease-in-out infinite}@keyframes nvscan{0%{margin-left:-40%}100%{margin-left:100%}}`}</style>
          </div>
        )}
      </NBCard>

      {hosts !== null && !scanning && (
        <NBCard>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-white">
              Host terdeteksi{" "}
              <span className="text-slate-400">({hosts.length})</span>
            </h3>
            {selectable.length > 0 && (
              <NBButton
                variant="secondary"
                onClick={addSelected}
                disabled={adding || checked.size === 0}
              >
                {adding
                  ? "Menambah…"
                  : `+ Tambah terpilih (${checked.size})`}
              </NBButton>
            )}
          </div>
          {added > 0 && (
            <p className="mb-3 text-sm text-ok-400">
              {added} kamera berhasil ditambahkan. Lihat di tab Kamera.
            </p>
          )}
          {hosts.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
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
              <div className="hidden md:block">
                <NBTableWrap>
                <table className="w-full text-left text-sm">
                  <thead>
                    <NBTr>
                      <NBTh className="w-10">
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
                      </NBTh>
                      <NBTh>IP</NBTh>
                      <NBTh>Port</NBTh>
                      <NBTh>Status</NBTh>
                      <NBTh>Path main</NBTh>
                      <NBTh>Video</NBTh>
                    </NBTr>
                  </thead>
                  <tbody>
                    {hosts.map((h) => (
                      <HostRow key={key(h)} h={h} />
                    ))}
                  </tbody>
                </table>
                </NBTableWrap>
              </div>
            </>
          )}
        </NBCard>
      )}
      {hosts === null && !scanning && !error && (
        <p className="py-10 text-center text-sm text-slate-400">
          Isi subnet lalu tekan “Scan Network” untuk mulai memindai.
        </p>
      )}
    </div>
  );
}
