"use client";

import { useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { Stream } from "../../../lib/types";
import {
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  SectionTitle,
  Select,
  TextInput,
} from "../../../components/ui";

const BRANDS = [
  { slug: "auto", label: "Otomatis (coba semua)" },
  { slug: "hikvision", label: "Hikvision" },
  { slug: "dahua", label: "Dahua / Amcrest" },
  { slug: "uniview_ipc", label: "Uniview (kamera langsung)" },
  { slug: "uniview_nvr", label: "Uniview (NVR)" },
  { slug: "hanwha", label: "Hanwha / Samsung" },
  { slug: "axis", label: "Axis" },
  { slug: "tplink_vigi", label: "TP-Link Vigi" },
  { slug: "reolink", label: "Reolink" },
  { slug: "ezviz", label: "Ezviz" },
  { slug: "foscam", label: "Foscam" },
  { slug: "milesight", label: "Milesight" },
  { slug: "panasonic", label: "Panasonic" },
];

interface SubnetCandidate {
  host: string;
  port: number;
  brand: string;
  main_url: string;
  sub_url: string | null;
}

export default function AdminScannerPage() {
  const [ipRange, setIpRange] = useState("192.168.1.0/24");
  const [port, setPort] = useState("554");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [brand, setBrand] = useState("auto");
  const [scanning, setScanning] = useState(false);
  const [candidates, setCandidates] = useState<SubnetCandidate[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(0);
  const [error, setError] = useState("");

  const key = (c: SubnetCandidate) => `${c.host}:${c.port}:${c.brand}`;

  async function doScan() {
    setError("");
    setScanning(true);
    setCandidates(null);
    setChecked(new Set());
    setAdded(0);
    try {
      const res = await api.post<{ candidates: SubnetCandidate[] }>(
        "/admin/scan-subnet",
        {
          ip_range: ipRange.trim(),
          port: parseInt(port, 10) || 554,
          username: username.trim(),
          password,
          brand,
        },
      );
      setCandidates(res.candidates);
      if (res.candidates.length === 0)
        setError("Tidak ada kamera ditemukan di subnet ini.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan gagal");
    } finally {
      setScanning(false);
    }
  }

  function toggle(c: SubnetCandidate) {
    const k = key(c);
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  function toggleAll() {
    if (!candidates) return;
    if (checked.size === candidates.length) setChecked(new Set());
    else setChecked(new Set(candidates.map(key)));
  }

  async function addSelected() {
    if (!candidates) return;
    const selected = candidates.filter((c) => checked.has(key(c)));
    if (selected.length === 0) return;
    setError("");
    setAdding(true);
    let ok = 0;
    for (const c of selected) {
      try {
        await api.post<Stream>("/admin/streams", {
          name: `Kamera ${c.host}`,
          rtsp_url: c.main_url,
          brand: c.brand,
          storage_mode: "local",
        });
        ok++;
      } catch (e) {
        setError(
          e instanceof ApiError
            ? `Gagal menambah ${c.host}: ${e.message}`
            : `Gagal menambah ${c.host}`,
        );
        break;
      }
    }
    setAdded(ok);
    setAdding(false);
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
          <Field label="Merek">
            <Select
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
            >
              {BRANDS.map((b) => (
                <option key={b.slug} value={b.slug}>
                  {b.label}
                </option>
              ))}
            </Select>
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

      {candidates !== null && !scanning && (
        <Card>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-white">
              Kamera ditemukan{" "}
              <span className="text-slate-400">({candidates.length})</span>
            </h3>
            {candidates.length > 0 && (
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
          {candidates.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              Tidak ada kamera yang merespons di subnet ini.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-ink-700 text-xs uppercase tracking-wider text-slate-500">
                    <th scope="col" className="w-10 px-3 py-3">
                      <input
                        type="checkbox"
                        checked={checked.size === candidates.length}
                        onChange={toggleAll}
                        className="h-5 w-5 accent-accent-500"
                        aria-label="Pilih semua"
                      />
                    </th>
                    <th scope="col" className="px-3 py-3 font-semibold">IP</th>
                    <th scope="col" className="px-3 py-3 font-semibold">Port</th>
                    <th scope="col" className="px-3 py-3 font-semibold">Merek</th>
                    <th scope="col" className="px-3 py-3 font-semibold">URL Stream</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-700/60">
                  {candidates.map((c) => (
                    <tr key={key(c)} className="hover:bg-white/[0.02]">
                      <td className="px-3 py-3">
                        <input
                          type="checkbox"
                          checked={checked.has(key(c))}
                          onChange={() => toggle(c)}
                          className="h-5 w-5 accent-accent-500"
                          aria-label={`Pilih ${c.host}`}
                        />
                      </td>
                      <td className="px-3 py-3 font-mono text-white">{c.host}</td>
                      <td className="px-3 py-3 font-mono text-slate-400">
                        {c.port}
                      </td>
                      <td className="px-3 py-3">
                        <Badge tone="muted">{c.brand}</Badge>
                      </td>
                      <td className="max-w-[280px] truncate px-3 py-3 font-mono text-xs text-slate-400">
                        {c.main_url}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
      {candidates === null && !scanning && !error && (
        <p className="py-10 text-center text-sm text-slate-500">
          Isi subnet lalu tekan “Scan Network” untuk mulai memindai.
        </p>
      )}
    </div>
  );
}
