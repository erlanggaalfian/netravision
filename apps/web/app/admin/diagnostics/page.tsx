"use client";

/* Halaman admin: Diagnostik tambah kamera (super_admin only).
   Tiga seksi: control API MediaMTX (versi + akses), status registrasi
   path MediaMTX per kamera, hasil probe RTSP terakhir per kamera,
   ditambah riwayat 20 kegagalan terakhir. Setiap kegagalan tampil
   sebagai penyebab yang bisa dibaca beserta langkah perbaikan, bukan
   kode HTTP mentah. Tidak menampilkan URL atau kredensial kamera. */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import type {
  DiagnosticsData,
  ProbeResult,
} from "../../../lib/types";
import { ErrorBox, FailureBox, Spinner } from "../../../components/ui";
import { NBBadge, NBButton, NBCard, NBEmptyState, NBTitle } from "../_nb";

const PROBE_LABEL: Record<string, { label: string; tone: "ok" | "bad" | "warn" | "muted" }> = {
  video: { label: "Video OK", tone: "ok" },
  auth_failed: { label: "Auth gagal", tone: "bad" },
  not_found: { label: "Path tidak ditemukan", tone: "bad" },
  timeout: { label: "Timeout", tone: "warn" },
  no_video: { label: "Tidak ada video", tone: "bad" },
  error: { label: "Error", tone: "bad" },
};

function ProbeBadge({ status }: { status: string | null }) {
  if (!status) {
    return <NBBadge tone="muted">Belum diprobe</NBBadge>;
  }
  const entry = PROBE_LABEL[status] ?? { label: status, tone: "muted" as const };
  return <NBBadge tone={entry.tone}>{entry.label}</NBBadge>;
}

function fmtWaktu(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString("id-ID", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function AdminDiagnosticsPage() {
  const { user: me } = useAuth();
  /* Pertahanan berlapis: halaman ini super_admin-only (layout juga
     mengalihkan admin biasa), jangan render atau muat kontennya bila
     peran tidak cocok. */
  const isSuperAdmin = me?.role === "super_admin";
  const [data, setData] = useState<DiagnosticsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [probingId, setProbingId] = useState<number | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await api.get<DiagnosticsData>("/admin/diagnostics/camera-add");
      setData(res);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Gagal memuat diagnostik",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isSuperAdmin) void load();
    else setLoading(false);
  }, [isSuperAdmin, load]);

  async function probe(streamId: number) {
    setProbingId(streamId);
    setProbeError(null);
    try {
      const res = await api.post<ProbeResult>(
        "/admin/diagnostics/camera-add/probe",
        { stream_id: streamId },
      );
      setData((prev) =>
        prev
          ? {
              ...prev,
              rtsp: prev.rtsp.map((row) =>
                row.stream_id === streamId
                  ? {
                      ...row,
                      main_status: res.main.status,
                      sub_status: res.sub ? res.sub.status : row.sub_status,
                      checked_at: new Date().toISOString(),
                    }
                  : row,
              ),
            }
          : prev,
      );
    } catch (e) {
      setProbeError(
        e instanceof ApiError ? e.message : "Probe gagal, coba lagi",
      );
    } finally {
      setProbingId(null);
    }
  }

  if (!isSuperAdmin) {
    return (
      <NBCard>
        <NBEmptyState text="Halaman ini hanya untuk super admin." />
      </NBCard>
    );
  }

  if (loading) return <Spinner />;
  if (error) {
    return (
      <div className="space-y-3">
        <ErrorBox message={error} />
        <NBButton variant="secondary" onClick={() => void load()}>
          Muat ulang
        </NBButton>
      </div>
    );
  }
  if (!data) return null;

  const { mediamtx } = data;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <NBTitle title="Diagnostik Tambah Kamera" />
        <NBButton variant="secondary" onClick={() => void load()}>
          Muat ulang
        </NBButton>
      </div>
      <p className="-mt-2 text-sm text-slate-400">
        Penyebab kegagalan tambah kamera beserta langkah perbaikannya.
        Tidak menampilkan URL atau kata sandi kamera.
      </p>

      {/* Seksi 1: control API MediaMTX */}
      <NBCard>
        <h2 className="mb-3 text-base font-semibold">Control API MediaMTX</h2>
        <dl className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-slate-400">Status:</dt>
            <dd>
              {mediamtx.reachable ? (
                <NBBadge tone="ok">Terhubung</NBBadge>
              ) : (
                <NBBadge tone="bad">Tidak terhubung</NBBadge>
              )}
            </dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-slate-400">Alamat:</dt>
            <dd className="break-all">{mediamtx.api_url}</dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-slate-400">Versi:</dt>
            <dd>{mediamtx.version ?? "Tidak diketahui"}</dd>
          </div>
        </dl>
        {mediamtx.failure && (
          <div className="mt-3">
            <FailureBox failure={mediamtx.failure} />
          </div>
        )}
      </NBCard>

      {/* Seksi 2: registrasi path MediaMTX */}
      <NBCard>
        <h2 className="mb-3 text-base font-semibold">
          Registrasi Path MediaMTX
        </h2>
        <p className="mb-3 text-sm text-slate-400">
          {data.paths_terdaftar} dari {data.paths_total} path terdaftar di
          MediaMTX.
        </p>
        {data.paths_hilang.length === 0 ? (
          <NBEmptyState text="Semua path kamera aktif terdaftar di MediaMTX." />
        ) : (
          <ul className="space-y-2 text-sm">
            {data.paths_hilang.map((p) => (
              <li
                key={p.path}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-ink-800 px-3 py-2"
              >
                <span className="min-w-0">
                  <span className="font-medium">{p.name}</span>
                  <span className="text-slate-400"> ({p.path})</span>
                </span>
                <NBBadge tone="warn">Belum terdaftar</NBBadge>
              </li>
            ))}
          </ul>
        )}
      </NBCard>

      {/* Seksi 3: hasil probe RTSP */}
      <NBCard>
        <h2 className="mb-3 text-base font-semibold">Hasil Probe RTSP</h2>
        {probeError && (
          <div className="mb-3">
            <ErrorBox message={probeError} />
          </div>
        )}
        {data.rtsp.length === 0 ? (
          <NBEmptyState text="Belum ada kamera aktif." />
        ) : (
          <ul className="space-y-2 text-sm">
            {data.rtsp.map((row) => (
              <li
                key={row.stream_id}
                className="rounded-xl bg-ink-800 px-3 py-2.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 font-medium">{row.name}</span>
                  <NBButton
                    variant="secondary"
                    disabled={probingId === row.stream_id}
                    onClick={() => void probe(row.stream_id)}
                  >
                    {probingId === row.stream_id ? "Memprobe..." : "Probe"}
                  </NBButton>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-slate-400">
                  <span className="flex items-center gap-1.5">
                    Utama: <ProbeBadge status={row.main_status} />
                  </span>
                  {row.sub_status !== null && (
                    <span className="flex items-center gap-1.5">
                      Sub: <ProbeBadge status={row.sub_status} />
                    </span>
                  )}
                  <span>Terakhir: {fmtWaktu(row.checked_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </NBCard>

      {/* Riwayat kegagalan terakhir */}
      <NBCard>
        <h2 className="mb-3 text-base font-semibold">
          Riwayat Kegagalan Terakhir
        </h2>
        {data.riwayat.length === 0 ? (
          <NBEmptyState text="Belum ada kegagalan tambah kamera yang tercatat." />
        ) : (
          <ul className="space-y-3">
            {data.riwayat.map((row) => (
              <li key={row.id} className="space-y-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium">{row.camera_name}</span>
                  <span className="text-slate-400">
                    {fmtWaktu(row.created_at)}
                  </span>
                </div>
                <FailureBox failure={row} />
              </li>
            ))}
          </ul>
        )}
      </NBCard>
    </div>
  );
}
