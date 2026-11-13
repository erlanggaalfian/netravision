"use client";

import { useEffect, useRef, useState } from "react";
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
  /* Funnel 3 tahap: IP hidup tapi port RTSP tertutup (gagal tahap 2). */
  port_closed: { label: "Port RTSP tertutup", tone: "muted" },
};

type ScanJobStatus = {
  status: "running" | "done" | "error";
  scanned: number;
  total: number;
  hosts: SubnetHost[];
  candidates: { host: string; main_url: string }[];
  error: string | null;
  /* Progres funnel 3 tahap (dari GET job). */
  stage: "reachability" | "port_check" | "discovery" | "done";
  reachable_count: number;
  port_open_count: number;
};

const STAGE_LABEL: Record<ScanJobStatus["stage"], string> = {
  reachability: "Tahap 1/3 · Cek IP terjangkau",
  port_check: "Tahap 2/3 · Cek port RTSP",
  discovery: "Tahap 3/3 · Cek kamera",
  done: "Selesai",
};

/* Urutkan host secara numerik per IP supaya daftar live tidak
   meloncat-loncat mengikuti urutan selesainya tiap host. */
function sortHosts(hosts: SubnetHost[]): SubnetHost[] {
  const num = (h: SubnetHost) =>
    h.host.split(".").reduce((acc, n) => acc * 256 + (parseInt(n, 10) || 0), 0);
  return [...hosts].sort((a, b) => num(a) - num(b));
}

function mainInfo(h: SubnetHost): string {
  const p = h.paths.find((x) => x.role === "main");
  if (!p?.width || !p.height) return p?.path ?? "";
  const parts = [`${p.width}×${p.height}`];
  if (p.fps) parts.push(`${p.fps} fps`);
  return parts.join(" · ");
}

/* Info sub stream (role 'sub' dari klasifikasi pintar backend):
   resolusi + fps bila ada, atau path-nya bila tanpa info video
   (mis. jalur cepat kamera dikenal). */
function subInfo(h: SubnetHost): string {
  const p = h.paths.find((x) => x.role === "sub");
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
  const [progress, setProgress] = useState({
    scanned: 0,
    total: 0,
    stage: "reachability" as ScanJobStatus["stage"],
    reachable: 0,
    portOpen: 0,
  });
  const [hosts, setHosts] = useState<SubnetHost[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(0);
  const [error, setError] = useState("");
  /* Batalkan polling saat unmount supaya tidak setState sesudah lepas. */
  const cancelledRef = useRef(false);
  useEffect(() => {
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const key = (h: SubnetHost) => `${h.host}:${h.port}`;
  /* Host 'unreachable' (IP mati) TIDAK ditampilkan di daftar hasil:
     hanya noise saat scan /24. Jumlahnya tetap dihitung dan tampil di
     ringkasan sebagai "tidak terjangkau (disembunyikan)". API tetap
     mengembalikannya supaya hitungan funnel benar. */
  const visibleHosts = (hosts ?? []).filter(
    (h) => h.status !== "unreachable",
  );
  const hiddenUnreachable = (hosts ?? []).length - visibleHosts.length;
  /* Kamera yang sudah terdaftar tidak ditawarkan untuk ditambah lagi
     (cegah duplikat): hanya host video yang BELUM dikenal yang bisa
     dipilih. */
  const selectable = (hosts ?? []).filter(
    (h) => h.status === "video" && !h.known,
  );

  async function doScan() {
    setError("");
    setScanning(true);
    setProgress({
      scanned: 0,
      total: 0,
      stage: "reachability",
      reachable: 0,
      portOpen: 0,
    });
    setHosts(null);
    setChecked(new Set());
    setAdded(0);
    try {
      /* Scan async: POST langsung kembalikan 202 + job_id, lalu polling
         status tiap 2 detik sampai done/error. Hasil parsial
         ditampilkan langsung selagi jalan (bukan hanya saat selesai). */
      const created = await api.post<{ job_id: string }>("/admin/scan-subnet", {
        ip_range: ipRange.trim(),
        port: parseInt(port, 10) || 554,
        username: username.trim(),
        password,
      });
      const jobId = created.job_id;
      for (;;) {
        await new Promise((r) => setTimeout(r, 2000));
        if (cancelledRef.current) return;
        const job = await api.get<ScanJobStatus>(
          `/admin/scan-subnet/${jobId}`,
        );
        if (cancelledRef.current) return;
        setProgress({
          scanned: job.scanned,
          total: job.total,
          stage: job.stage ?? "reachability",
          reachable: job.reachable_count ?? 0,
          portOpen: job.port_open_count ?? 0,
        });
        /* Hasil live: host yang sudah selesai langsung terlihat. */
        setHosts(sortHosts(job.hosts ?? []));
        if (job.status === "done") {
          if (job.hosts.length === 0)
            setError("Tidak ada kamera ditemukan di subnet ini.");
          break;
        }
        if (job.status === "error") {
          setError(job.error ?? "Scan gagal");
          break;
        }
      }
    } catch (e) {
      if (!cancelledRef.current)
        setError(e instanceof ApiError ? e.message : "Scan gagal");
    } finally {
      if (!cancelledRef.current) setScanning(false);
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
    /* E-S5: jangan berhenti di kegagalan pertama, lanjutkan sisanya
       dan laporkan mana yang gagal. */
    const failed: string[] = [];
    const failedKeys = new Set<string>();
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
      } catch {
        failed.push(h.host);
        failedKeys.add(key(h));
      }
    }
    if (failed.length > 0) {
      setError(
        `Gagal menambah ${failed.length} kamera: ${failed.join(", ")}. ${ok} kamera berhasil ditambahkan.`,
      );
    }
    setAdded(ok);
    /* Reset checked supaya klik kedua tidak membuat duplikat; bila
       ada yang gagal, hanya yang gagal yang tetap tercentang. */
    setChecked(failedKeys);
    setAdding(false);
  }

  /* E-R5: dua komponen terpisah supaya HTML valid: kartu <li>
     hanya di dalam <ul> mobile, baris <tr> hanya di <tbody>. */
  function HostCheckbox({ h }: { h: SubnetHost }) {
    /* Kamera yang sudah terdaftar tidak bisa dipilih (cegah duplikat). */
    const canPick = h.status === "video" && !h.known;
    return (
      <input
        type="checkbox"
        checked={checked.has(key(h))}
        onChange={() => toggle(h)}
        disabled={!canPick}
        className="h-5 w-5 shrink-0 accent-accent-500 disabled:opacity-40"
        aria-label={`Pilih ${h.host}`}
      />
    );
  }

  function HostCard({ h }: { h: SubnetHost }) {
    const st = SCAN_STATUS[h.status] ?? SCAN_STATUS.error;
    return (
      <li className="flex items-center gap-3 rounded-xl bg-ink-900 shadow-sm p-3 md:hidden">
        <HostCheckbox h={h} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-sm text-white">
            {h.host}:{h.port}
          </p>
          <p className="mt-0.5 truncate text-xs text-slate-400">
            {h.best_main ? `Main: ${mainInfo(h)}` : "tanpa video"}
          </p>
          {h.best_sub && (
            <p className="mt-0.5 truncate text-xs text-slate-400">
              Sub: {subInfo(h)}
            </p>
          )}
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <NBBadge tone={st.tone}>{st.label}</NBBadge>
            {h.known && <NBBadge tone="info">Sudah terdaftar</NBBadge>}
          </div>
        </div>
      </li>
    );
  }

  function HostRow({ h }: { h: SubnetHost }) {
    const st = SCAN_STATUS[h.status] ?? SCAN_STATUS.error;
    return (
      <NBTr className="hidden md:table-row">
        <NBTd>
          <HostCheckbox h={h} />
        </NBTd>
        <NBTd className="font-mono">{h.host}</NBTd>
        <NBTd className="font-mono">{h.port}</NBTd>
        <NBTd>
          <span className="flex flex-wrap items-center gap-1.5">
            <NBBadge tone={st.tone}>{st.label}</NBBadge>
            {h.known && <NBBadge tone="info">Sudah terdaftar</NBBadge>}
          </span>
        </NBTd>
        <NBTd className="max-w-[280px] truncate font-mono text-xs">
          {h.best_main ?? "-"}
        </NBTd>
        <NBTd className="max-w-[280px] truncate font-mono text-xs">
          {h.best_sub ?? "-"}
        </NBTd>
        <NBTd className="text-xs">
          {h.best_main && (
            <span className="block leading-relaxed">
              <span className="block">Main: {mainInfo(h)}</span>
              {h.best_sub && (
                <span className="block text-slate-400">
                  Sub: {subInfo(h)}
                </span>
              )}
            </span>
          )}
        </NBTd>
      </NBTr>
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
          {/* Sel tombol sejajar kotak input: pelabel tak terlihat setinggi
              label field, supaya tombol tidak turun mengikuti hint di
              bawah field IP Subnet. */}
          <div className="flex flex-col">
            <span
              className="mb-1.5 block text-sm font-semibold invisible select-none"
              aria-hidden="true"
            >
              Aksi
            </span>
            <NBButton onClick={doScan} disabled={scanning} className="w-full sm:w-auto">
              {scanning ? "Memindai…" : "Scan Network"}
            </NBButton>
          </div>
        </div>

        {scanning && (
          <div className="mt-5 space-y-2 border-t border-ink-800 pt-4">
            <div className="flex flex-wrap justify-between gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <span>{STAGE_LABEL[progress.stage]}</span>
              <span>
                Memindai {progress.scanned} dari {progress.total} host
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-ink-700">
              <div
                className="h-full rounded-full bg-accent-500 transition-all duration-500"
                style={{
                  width: `${
                    progress.total > 0
                      ? Math.round((progress.scanned / progress.total) * 100)
                      : 0
                  }%`,
                }}
              />
            </div>
            <p className="text-xs text-slate-400">
              {progress.reachable} IP terjangkau
              {progress.stage !== "reachability" &&
                ` · ${progress.portOpen} port RTSP terbuka`}
              {progress.stage === "done" &&
                ` · ${selectable.length} kamera baru dengan video`}
            </p>
          </div>
        )}
      </NBCard>

      {hosts !== null && (
        <NBCard>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-white">
              Host terdeteksi{" "}
              <span className="text-slate-400">({visibleHosts.length})</span>
            </h3>
            {selectable.length > 0 && (
              <NBButton
                variant="secondary"
                onClick={addSelected}
                disabled={scanning || adding || checked.size === 0}
              >
                {adding
                  ? "Menambah…"
                  : `+ Tambah terpilih (${checked.size})`}
              </NBButton>
            )}
          </div>
          {!scanning && visibleHosts.length > 0 && (
            <p className="mb-3 text-xs text-slate-400">
              {progress.reachable} IP terjangkau · {progress.portOpen}{" "}
              port RTSP terbuka ·{" "}
              {visibleHosts.filter((h) => h.status === "video").length} dengan
              video
              {visibleHosts.some((h) => h.known) &&
                ` · ${visibleHosts.filter((h) => h.known).length} sudah terdaftar`}
              {hiddenUnreachable > 0 &&
                ` · ${hiddenUnreachable} tidak terjangkau (disembunyikan)`}
            </p>
          )}
          {added > 0 && (
            <p className="mb-3 text-sm text-ok-400">
              {added} kamera berhasil ditambahkan. Lihat di tab Kamera.
            </p>
          )}
          {visibleHosts.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
              {scanning
                ? "Memindai… hasil muncul di sini begitu ditemukan."
                : `Tidak ada kamera yang merespons di subnet ini.${
                    hiddenUnreachable > 0
                      ? ` (${hiddenUnreachable} IP tidak terjangkau, disembunyikan.)`
                      : ""
                  }`}
            </p>
          ) : (
            <>
              {/* Mobile: pilih semua + daftar kartu */}
              {selectable.length > 0 && (
                <label className="mb-2 flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-300 md:hidden">
                  <input
                    type="checkbox"
                    checked={checked.size === selectable.length}
                    onChange={toggleAll}
                    className="h-5 w-5 accent-accent-500"
                    aria-label="Pilih semua"
                  />
                  Pilih semua
                </label>
              )}
              <ul className="space-y-2 md:hidden">
                {visibleHosts.map((h) => (
                  <HostCard key={key(h)} h={h} />
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
                      <NBTh>Path sub</NBTh>
                      <NBTh>Video</NBTh>
                    </NBTr>
                  </thead>
                  <tbody>
                    {visibleHosts.map((h) => (
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
