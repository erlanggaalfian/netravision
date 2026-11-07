"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { AdConfig, ApiKey, Stream } from "../../../lib/types";
import { ErrorBox, Modal, Spinner } from "../../../components/ui";
import {
  NBAccordion,
  NBBadge,
  NBButton,
  NBCard,
  NBConfirmModal,
  NBEmptyState,
  NBField,
  NBInput,
  NBSelect,
  NBTitle,
  NBTableWrap,
  NBTh,
  NBTd,
  NBTr,
} from "../_nb";

type KeyOut = ApiKey;

interface CreatedKey extends KeyOut {
  key: string;
}

interface AccessLog {
  id: number;
  key_id: number | null;
  stream_id: number | null;
  ip: string | null;
  action: string | null;
  accessed_at: string | null;
}

const LOG_PAGE = 30;

function KeyIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      width="40"
      height="40"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
    </svg>
  );
}



async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default function AdminKeysPage() {
  const [keys, setKeys] = useState<KeyOut[] | null>(null);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [logs, setLogs] = useState<AccessLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(true);
  const [logsOffset, setLogsOffset] = useState(0);
  const [logsDone, setLogsDone] = useState(false);
  const [logKeyF, setLogKeyF] = useState("all");
  const [logStatusF, setLogStatusF] = useState("all");
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [deleting, setDeleting] = useState<KeyOut | null>(null);
  const [clearingLogs, setClearingLogs] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [guideKey, setGuideKey] = useState("");

  const loadKeys = () => {
    api
      .get<KeyOut[]>("/admin/api-keys")
      .then(setKeys)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "Gagal memuat API key");
        setKeys([]);
      });
  };

  const loadLogs = (reset: boolean) => {
    const offset = reset ? 0 : logsOffset;
    if (reset) {
      setLogsLoading(true);
      setLogsDone(false);
    }
    const params = new URLSearchParams({
      limit: String(LOG_PAGE),
      offset: String(offset),
    });
    if (logKeyF !== "all") params.set("key_id", logKeyF);
    if (logStatusF !== "all") params.set("status", logStatusF);
    api
      .get<AccessLog[]>(`/admin/api-access-logs?${params}`)
      .then((rows) => {
        setLogs((prev) => (reset ? rows : [...prev, ...rows]));
        setLogsOffset(offset + rows.length);
        if (rows.length < LOG_PAGE) setLogsDone(true);
      })
      .catch(() => {
        if (reset) setLogs([]);
      })
      .finally(() => setLogsLoading(false));
  };

  useEffect(() => {
    loadKeys();
    api.get<Stream[]>("/admin/streams").then((d) => setStreams(d ?? [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setLogsOffset(0);
    loadLogs(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logKeyF, logStatusF]);

  const [togglingId, setTogglingId] = useState<number | null>(null);

  async function toggleActive(k: KeyOut) {
    if (togglingId !== null) return;
    setTogglingId(k.id);
    try {
      await api.put(`/admin/api-keys/${k.id}`, { is_active: !k.is_active });
      loadKeys();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memperbarui");
    } finally {
      setTogglingId(null);
    }
  }

  async function doDelete() {
    if (!deleting) return;
    try {
      await api.del(`/admin/api-keys/${deleting.id}`);
      setDeleting(null);
      loadKeys();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus");
    }
  }

  async function doClearLogs() {
    try {
      await api.del("/admin/api-access-logs");
      setClearingLogs(false);
      setLogsOffset(0);
      loadLogs(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus log");
    }
  }

  const streamName = (id: number | null) =>
    streams.find((s) => s.id === id)?.name ?? (id != null ? `#${id}` : "—");
  const keyName = (id: number | null) =>
    keys?.find((k) => k.id === id)?.name ?? (id != null ? `#${id}` : "—");

  return (
    <div>
      <NBTitle
        title="API Key"
        desc="Kunci embed untuk pihak ketiga — key penuh hanya tampil sekali saat dibuat"
        action={
          <div className="flex flex-wrap gap-2">
            <NBButton variant="secondary" onClick={() => setShowGuide(true)}>
              Panduan Integrasi
            </NBButton>
            <NBButton onClick={() => setShowAdd(true)}>+ Buat Key</NBButton>
          </div>
        }
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {keys === null ? (
        <Spinner />
      ) : keys.length === 0 ? (
        <NBEmptyState icon={<KeyIcon className="h-8 w-8 text-slate-500" />} text="Belum ada API key." />
      ) : (
        <div className="space-y-2">
          {keys.map((k) => (
            <div key={k.id}>
              <div className="md:hidden">
                <NBAccordion
                  summary={
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-white">
                        {k.name}
                      </span>
                      <span className="mt-1 flex flex-wrap gap-1.5">
                        <NBBadge tone={k.is_active ? "ok" : "muted"}>
                          {k.is_active ? "Aktif" : "Nonaktif"}
                        </NBBadge>
                      </span>
                    </span>
                  }
                >
                  <div className="space-y-3">
                    <p className="flex flex-wrap gap-1.5">
                      <NBBadge tone="muted">{k.stream_ids.length} kamera</NBBadge>
                      {k.domain_lock && (
                        <NBBadge tone="info">{k.domain_lock}</NBBadge>
                      )}
                      {!k.include_playback && (
                        <NBBadge tone="muted">Tanpa playback</NBBadge>
                      )}
                    </p>
                    {k.custom_camera_name && (
                      <p className="text-xs text-slate-400">
                        Nama kustom: {k.custom_camera_name}
                      </p>
                    )}
                    <p className="text-xs text-slate-400">
                      Terakhir dipakai: {k.last_used_at ?? "belum pernah"}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <NBButton
                        variant="secondary"
                        onClick={() => toggleActive(k)}
                        disabled={togglingId === k.id}
                        className="px-3"
                      >
                        {togglingId === k.id
                          ? "Memproses…"
                          : k.is_active
                            ? "Nonaktifkan"
                            : "Aktifkan"}
                      </NBButton>
                      <NBButton
                        variant="danger"
                        onClick={() => setDeleting(k)}
                        className="px-3"
                      >
                        Hapus
                      </NBButton>
                    </div>
                  </div>
                </NBAccordion>
              </div>
              <div className="hidden md:block">
                <NBCard className="p-4 transition-colors">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-white">{k.name}</p>
                      <p className="mt-1 flex flex-wrap gap-1.5">
                        <NBBadge tone={k.is_active ? "ok" : "muted"}>
                          {k.is_active ? "Aktif" : "Nonaktif"}
                        </NBBadge>
                        <NBBadge tone="muted">{k.stream_ids.length} kamera</NBBadge>
                        {k.domain_lock && (
                          <NBBadge tone="info">{k.domain_lock}</NBBadge>
                        )}
                        {!k.include_playback && (
                          <NBBadge tone="muted">Tanpa playback</NBBadge>
                        )}
                      </p>
                      {k.custom_camera_name && (
                        <p className="mt-1 text-xs text-slate-400">
                          Nama kustom: {k.custom_camera_name}
                        </p>
                      )}
                      <p className="mt-1 text-xs text-slate-400">
                        Terakhir dipakai: {k.last_used_at ?? "belum pernah"}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <NBButton
                        variant="secondary"
                        onClick={() => toggleActive(k)}
                        disabled={togglingId === k.id}
                        className="px-3"
                      >
                        {togglingId === k.id
                          ? "Memproses…"
                          : k.is_active
                            ? "Nonaktifkan"
                            : "Aktifkan"}
                      </NBButton>
                      <NBButton
                        variant="danger"
                        onClick={() => setDeleting(k)}
                        className="px-3"
                      >
                        Hapus
                      </NBButton>
                    </div>
                  </div>
                </NBCard>
              </div>
            </div>
          ))}
        </div>
      )}

      <EmbedPlayerSettings />

      <div className="mb-3 mt-8 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold tracking-tight text-white">Log akses</h2>
        <div className="flex flex-wrap gap-2">
          <NBButton
            variant="secondary"
            onClick={() => {
              setLogsOffset(0);
              loadLogs(true);
            }}
           
          >
            Muat ulang
          </NBButton>
          <NBButton
            variant="danger"
            onClick={() => setClearingLogs(true)}
           
          >
            Hapus semua log
          </NBButton>
        </div>
      </div>

      <NBCard className="mb-3 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <NBField label="Filter key">
            <NBSelect value={logKeyF} onChange={(e) => setLogKeyF(e.target.value)}>
              <option value="all">Semua key</option>
              {(keys ?? []).map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </NBSelect>
          </NBField>
          <NBField label="Filter status">
            <NBSelect
              value={logStatusF}
              onChange={(e) => setLogStatusF(e.target.value)}
            >
              <option value="all">Semua status</option>
              <option value="ok">Berhasil</option>
              <option value="denied">Ditolak</option>
            </NBSelect>
          </NBField>
        </div>
      </NBCard>

      {logsLoading && logs.length === 0 ? (
        <Spinner />
      ) : logs.length === 0 ? (
        <NBEmptyState icon={<KeyIcon className="h-8 w-8 text-slate-500" />} text="Belum ada akses tercatat." />
      ) : (
        <>
          <NBTableWrap>
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <NBTr>
                  <NBTh>Waktu</NBTh>
                  <NBTh>Key</NBTh>
                  <NBTh>Kamera</NBTh>
                  <NBTh>Aksi</NBTh>
                  <NBTh>IP</NBTh>
                </NBTr>
              </thead>
              <tbody>
                {logs.map((l) => {
                  const denied = (l.action ?? "").includes(".denied");
                  return (
                    <NBTr key={l.id}>
                      <NBTd>
                        {l.accessed_at
                          ? new Date(l.accessed_at).toLocaleString("id-ID")
                          : "—"}
                      </NBTd>
                      <NBTd className="text-slate-400">
                        {keyName(l.key_id)}
                      </NBTd>
                      <NBTd className="text-slate-400">
                        {streamName(l.stream_id)}
                      </NBTd>
                      <NBTd>
                        <NBBadge tone={denied ? "bad" : "ok"}>
                          {denied ? "Ditolak" : (l.action ?? "—")}
                        </NBBadge>
                      </NBTd>
                      <NBTd className="font-mono text-xs text-slate-400">
                        {l.ip ?? "—"}
                      </NBTd>
                    </NBTr>
                  );
                })}
              </tbody>
            </table>
          </NBTableWrap>
          {!logsDone && (
            <div className="mt-3 text-center">
              <NBButton
                variant="secondary"
                onClick={() => loadLogs(false)}
                disabled={logsLoading}
                className="min-h-[44px]"
              >
                {logsLoading ? "Memuat…" : "Muat lebih banyak"}
              </NBButton>
            </div>
          )}
        </>
      )}

      {showAdd && (
        <KeyFormModal
          streams={streams}
          onClose={() => setShowAdd(false)}
          onCreated={(k) => {
            setShowAdd(false);
            setCreated(k);
            setGuideKey(k.key);
            loadKeys();
          }}
        />
      )}
      {created && (
        <Modal title="API key dibuat" onClose={() => setCreated(null)}>
          <ErrorBox message="Salin key ini sekarang — tidak akan ditampilkan lagi." />
          <p className="mt-3 break-all rounded-lg bg-ink-950 p-3 font-mono text-sm text-accent-300">
            {created.key}
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <NBButton
              variant="secondary"
              onClick={() => {
                setCreated(null);
                setShowGuide(true);
              }}
            >
              Panduan Integrasi
            </NBButton>
            <NBButton onClick={() => setCreated(null)}>Selesai</NBButton>
          </div>
        </Modal>
      )}
      {deleting && (
        <NBConfirmModal
          title="Hapus API key"
          message={`Hapus key "${deleting.name}"? Embed yang memakainya ikut mati.`}
          onCancel={() => setDeleting(null)}
          onConfirm={doDelete}
        />
      )}
      {clearingLogs && (
        <NBConfirmModal
          title="Hapus semua log"
          message="Hapus seluruh catatan akses API? Tindakan ini tidak bisa dibatalkan."
          onCancel={() => setClearingLogs(false)}
          onConfirm={doClearLogs}
        />
      )}
      {showGuide && (
        <IntegrationGuideModal
          initialKey={guideKey}
          onClose={() => setShowGuide(false)}
        />
      )}
    </div>
  );
}

function EmbedPlayerSettings() {
  const [cfg, setCfg] = useState<AdConfig | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .get<AdConfig>("/ad-config")
      .then(setCfg)
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat pengaturan"),
      );
  }, []);

  async function save() {
    if (!cfg) return;
    setError("");
    setBusy(true);
    setSaved(false);
    try {
      const res = await api.post<AdConfig>("/admin/ad-config", cfg);
      setCfg(res);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  if (!cfg && !error) return <Spinner />;

  return (
    <NBCard className="mt-8 p-4 sm:p-5">
      <h2 className="text-lg font-bold tracking-tight text-white">Pengaturan Embed Player</h2>
      <p className="mt-1 text-sm text-slate-400">
        Berlaku untuk semua pemutar embed pihak ketiga
      </p>
      {error && (
        <div className="mt-3">
          <ErrorBox message={error} />
        </div>
      )}
      {cfg && (
        <div className="mt-4 space-y-4">
          <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3">
            <span>
              <span className="block text-sm font-medium text-white">
                Klik untuk memutar
              </span>
              <span className="block text-xs text-slate-400">
                Pengunjung menekan tombol putar sebelum stream dimulai
              </span>
            </span>
            <input
              type="checkbox"
              checked={cfg.click_to_play ?? true}
              onChange={(e) => setCfg({ ...cfg, click_to_play: e.target.checked })}
              className="h-5 w-5 shrink-0 accent-accent-500"
              aria-label="Klik untuk memutar"
            />
          </label>
          <NBField
            label="Batas waktu pemutaran (detik)"
            hint="Pemutaran berhenti otomatis setelah durasi ini"
          >
            <NBInput
              inputMode="numeric"
              value={String(cfg.embed_timeout_seconds ?? 300)}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                setCfg({
                  ...cfg,
                  embed_timeout_seconds: Number.isNaN(n) ? 0 : n,
                });
              }}
            />
          </NBField>
          <div className="flex items-center gap-3">
            <NBButton onClick={save} disabled={busy} className="min-h-[44px]">
              {busy ? "Menyimpan…" : "Simpan"}
            </NBButton>
            {saved && <span className="text-sm text-ok-400">Tersimpan</span>}
          </div>
        </div>
      )}
    </NBCard>
  );
}

function IntegrationGuideModal({
  initialKey,
  onClose,
}: {
  initialKey: string;
  onClose: () => void;
}) {
  const [key, setKey] = useState(initialKey);
  const [copied, setCopied] = useState("");
  const origin = typeof window !== "undefined" ? window.location.origin : "";

  const methods = [
    {
      id: "iframe",
      title: "Metode 1 — Kode iframe",
      desc: "Tempel di halaman web/HTML Anda.",
      code: `<iframe src="${origin}/embed?key=${key}" width="640" height="360" frameborder="0" allowfullscreen></iframe>`,
    },
    {
      id: "rest",
      title: "Metode 2 — URL REST API",
      desc: "Ambil daftar kamera & URL stream sebagai JSON.",
      code: `${origin}/api/external/cameras?key=${key}`,
    },
    {
      id: "player",
      title: "Metode 3 — URL pemutar langsung",
      desc: "Tautan langsung ke halaman pemutar embed.",
      code: `${origin}/embed?key=${key}`,
    },
  ];

  async function doCopy(id: string, text: string) {
    const ok = await copyText(text);
    setCopied(ok ? id : "");
    if (ok) setTimeout(() => setCopied(""), 2000);
  }

  return (
    <Modal title="Panduan Integrasi API" onClose={onClose} wide>
      <NBField
        label="API key"
        hint="Tempel key Anda bila belum terisi otomatis"
      >
        <NBInput
          value={key}
          onChange={(e) => setKey(e.target.value.trim())}
          placeholder="Tempel API key di sini…"
        />
      </NBField>
      <div className="mt-4 space-y-4">
        {methods.map((m) => (
          <div
            key={m.id}
            className="rounded-xl bg-ink-800 shadow-sm p-4"
          >
            <p className="text-sm font-semibold text-white">{m.title}</p>
            <p className="mt-0.5 text-xs text-slate-400">{m.desc}</p>
            <p className="mt-2 break-all rounded-lg bg-ink-950 p-3 font-mono text-xs text-accent-300">
              {key ? m.code : "— isi API key dulu —"}
            </p>
            <NBButton
              variant="secondary"
              disabled={!key}
              onClick={() => doCopy(m.id, m.code)}
              className="mt-2"
            >
              {copied === m.id ? "Tersalin ✓" : "Salin"}
            </NBButton>
          </div>
        ))}
      </div>
    </Modal>
  );
}

function KeyFormModal({
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
  const [customName, setCustomName] = useState("");
  const [includePlayback, setIncludePlayback] = useState(true);
  const [ordered, setOrdered] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function toggle(id: number) {
    setOrdered((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function move(id: number, dir: -1 | 1) {
    setOrdered((prev) => {
      const i = prev.indexOf(id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  const nameOf = (id: number) =>
    streams.find((s) => s.id === id)?.name ?? `#${id}`;

  async function save() {
    setError("");
    setBusy(true);
    try {
      const res = await api.post<CreatedKey>("/admin/api-keys", {
        name: name.trim(),
        stream_ids: ordered,
        domain_lock: domainLock.trim() || null,
        password: password || null,
        custom_camera_name: customName.trim() || null,
        include_playback: includePlayback,
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
        <NBField label="Nama key">
          <NBInput
            placeholder="cth: Website mitra"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </NBField>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <NBField label="Kunci domain (opsional)" hint="cth: mitra.or.id">
            <NBInput
              value={domainLock}
              onChange={(e) => setDomainLock(e.target.value)}
            />
          </NBField>
          <NBField label="Kata sandi embed (opsional)">
            <NBInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </NBField>
        </div>
        <NBField
          label="Judul kamera kustom (opsional)"
          hint="Untuk menyamarkan nama asli, cth: Kamera Depan, Pos Jaga"
        >
          <NBInput
            value={customName}
            onChange={(e) => setCustomName(e.target.value)}
            placeholder="Kosongkan untuk memakai nama asli"
          />
        </NBField>
        <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3">
          <span>
            <span className="block text-sm font-medium text-white">
              Sertakan playback
            </span>
            <span className="block text-xs text-slate-400">
              Key ini boleh membuka rekaman, bukan hanya live
            </span>
          </span>
          <input
            type="checkbox"
            checked={includePlayback}
            onChange={(e) => setIncludePlayback(e.target.checked)}
            className="h-5 w-5 shrink-0 accent-accent-500"
            aria-label="Sertakan playback"
          />
        </label>
        <NBField label={`Kamera yang boleh diakses${ordered.length ? ` (${ordered.length})` : ""}`}>
          <div className="max-h-64 space-y-1 overflow-y-auto rounded-lg bg-ink-800 shadow-sm p-2">
            {streams.map((s) => (
              <label
                key={s.id}
                className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-lg px-2 hover:bg-ink-800"
              >
                <input
                  type="checkbox"
                  checked={ordered.includes(s.id)}
                  onChange={() => toggle(s.id)}
                  className="h-5 w-5 shrink-0 accent-accent-500"
                />
                <span className="text-sm text-slate-200">{s.name}</span>
              </label>
            ))}
          </div>
        </NBField>
        {ordered.length > 1 && (
          <NBField label="Urutan kamera">
            <div className="space-y-1 rounded-lg bg-ink-800 shadow-sm p-2">
              {ordered.map((id, i) => (
                <div
                  key={id}
                  className="flex min-h-[44px] items-center gap-2 rounded-lg px-2 hover:bg-ink-800"
                >
                  <span className="w-6 shrink-0 text-center text-xs tabular-nums text-slate-400">
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm text-slate-200">
                    {nameOf(id)}
                  </span>
                  <button
                    type="button"
                    onClick={() => move(id, -1)}
                    disabled={i === 0}
                    className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-slate-400 hover:bg-ink-700 hover:text-slate-200 disabled:opacity-30"
                    aria-label={`Naikkan ${nameOf(id)}`}
                  >
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                      <path
                        d="M8 13V3M4 7l4-4 4 4"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => move(id, 1)}
                    disabled={i === ordered.length - 1}
                    className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-slate-400 hover:bg-ink-700 hover:text-slate-200 disabled:opacity-30"
                    aria-label={`Turunkan ${nameOf(id)}`}
                  >
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                      <path
                        d="M8 3v10M4 9l4 4 4-4"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          </NBField>
        )}
        <NBButton
          onClick={save}
          disabled={busy || !name.trim() || ordered.length === 0}
          className="w-full"
        >
          {busy ? "Membuat…" : "Buat Key"}
        </NBButton>
      </div>
    </Modal>
  );
}
