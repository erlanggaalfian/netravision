"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ApiError, api } from "../../../lib/api";
import type { DriveAccount } from "../../../lib/types";
import {
  Accordion,
  Badge,
  Button,
  ConfirmModal,
  EmptyState,
  ErrorBox,
  Field,
  Modal,
  SectionTitle,
  Spinner,
  TextInput,
} from "../../../components/ui";

function statusBadge(a: DriveAccount) {
  if (a.status === "connected") return <Badge tone="ok">Terhubung</Badge>;
  if (a.status === "error") return <Badge tone="bad">Bermasalah</Badge>;
  return <Badge tone="warn">Menunggu</Badge>;
}

function AccountRow({
  a,
  onSetDefault,
  onReauth,
  onDelete,
}: {
  a: DriveAccount;
  onSetDefault: () => void;
  onReauth: () => void;
  onDelete: () => void;
}) {
  const summary = (
    <span className="flex items-center justify-between gap-3">
      <span className="min-w-0">
        <span className="block truncate font-medium text-white">
          {a.name}
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
          {a.is_default && <Badge tone="info">Default</Badge>}
          {statusBadge(a)}
          <Badge tone="muted">
            {a.camera_count} kamera
          </Badge>
        </span>
        {a.last_error && (
          <span className="mt-1 block truncate text-xs text-bad-400">
            {a.last_error}
          </span>
        )}
      </span>
    </span>
  );
  const actions = (
    <div className="flex flex-wrap gap-2">
      {!a.is_default && (
        <Button
          variant="subtle"
          onClick={onSetDefault}
          className="min-h-[40px] px-3"
        >
          Jadikan default
        </Button>
      )}
      <Button variant="subtle" onClick={onReauth} className="min-h-[40px] px-3">
        Hubungkan ulang
      </Button>
      <Button variant="danger" onClick={onDelete} className="min-h-[40px] px-3">
        Hapus
      </Button>
    </div>
  );
  return (
    <>
      <div className="md:hidden">
        <Accordion summary={summary}>
          <div className="space-y-3">{actions}</div>
        </Accordion>
      </div>
      <div className="hidden items-center justify-between gap-3 rounded-xl border border-ink-700/60 bg-ink-900 px-4 py-3 md:flex">
        {summary}
        {actions}
      </div>
    </>
  );
}

function DrivePageInner() {
  const params = useSearchParams();
  const [accounts, setAccounts] = useState<DriveAccount[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [deleting, setDeleting] = useState<DriveAccount | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<DriveAccount[]>("/admin/drive-accounts")
      .then(setAccounts)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "Gagal memuat akun");
        setAccounts([]);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (params.get("connected") === "1") {
      setNotice("Akun Google Drive berhasil terhubung.");
      load();
      /* Bersihkan query agar notice tidak muncul lagi saat refresh. */
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [params, load]);

  async function setDefault(a: DriveAccount) {
    setError("");
    try {
      await api.put<DriveAccount>(`/admin/drive-accounts/${a.id}`, {
        is_default: true,
      });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    }
  }

  async function reauth(a: DriveAccount) {
    setError("");
    try {
      const res = await api.post<{ oauth_url: string }>(
        `/admin/drive-accounts/${a.id}/reauth`,
      );
      window.open(res.oauth_url, "_blank", "noopener");
      setNotice(
        "Selesaikan login Google di tab baru, lalu refresh halaman ini.",
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memulai ulang koneksi");
    }
  }

  async function doDelete() {
    if (!deleting) return;
    setError("");
    setBusy(true);
    try {
      await api.del(`/admin/drive-accounts/${deleting.id}`);
      setDeleting(null);
      load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(
          `Akun "${deleting.name}" masih dipakai ${deleting.camera_count} kamera. Pindahkan dulu kamera-kamera tersebut ke akun lain sebelum menghapus.`,
        );
        setDeleting(null);
      } else {
        setError(e instanceof ApiError ? e.message : "Gagal menghapus");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <SectionTitle
        title="Penyimpanan Google Drive"
        desc="Kelola akun Google Drive untuk unggahan rekaman kamera"
        action={
          <Button onClick={() => setShowAdd(true)}>+ Tambah akun</Button>
        }
      />
      {notice && (
        <div className="mb-4 rounded-xl border border-ok-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-ok-400">
          {notice}
        </div>
      )}
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {accounts === null ? (
        <Spinner />
      ) : accounts.length === 0 ? (
        <EmptyState text="Belum ada akun Google Drive. Tambahkan yang pertama." />
      ) : (
        <div className="space-y-2">
          {accounts.map((a) => (
            <AccountRow
              key={a.id}
              a={a}
              onSetDefault={() => setDefault(a)}
              onReauth={() => reauth(a)}
              onDelete={() => setDeleting(a)}
            />
          ))}
        </div>
      )}

      {showAdd && (
        <AddAccountModal
          onClose={() => setShowAdd(false)}
          onDone={() => {
            setShowAdd(false);
            load();
          }}
        />
      )}
      {deleting && (
        <ConfirmModal
          title="Hapus akun"
          message={`Hapus akun "${deleting.name}"? Unggahan yang sudah berjalan akan berhenti.`}
          onCancel={() => setDeleting(null)}
          onConfirm={doDelete}
        />
      )}
      {busy && <Spinner />}
    </div>
  );
}

function AddAccountModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [oauthUrl, setOauthUrl] = useState("");

  async function create() {
    setError("");
    setBusy(true);
    try {
      const res = await api.post<{ id: string; name: string; oauth_url: string }>(
        "/admin/drive-accounts",
        { name: name.trim() },
      );
      setOauthUrl(res.oauth_url);
      window.open(res.oauth_url, "_blank", "noopener");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menambah akun");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Tambah Akun Google Drive" onClose={onDone}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {!oauthUrl ? (
        <div className="space-y-4">
          <Field label="Nama akun">
            <TextInput
              placeholder="cth: Akun A — Gerbang"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Button
            onClick={create}
            disabled={busy || !name.trim()}
            className="w-full"
          >
            {busy ? "Membuat…" : "Buat & hubungkan"}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-slate-300">
            Akun dibuat. Selesaikan login Google di tab baru, lalu refresh
            halaman ini.
          </p>
          <Button
            onClick={() => window.open(oauthUrl, "_blank", "noopener")}
            className="w-full"
          >
            Buka lagi halaman login Google
          </Button>
          <Button variant="subtle" onClick={onDone} className="w-full">
            Selesai
          </Button>
        </div>
      )}
    </Modal>
  );
}

export default function AdminDrivePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center">
          <span className="text-sm text-neutral-400">Memuat…</span>
        </div>
      }
    >
      <DrivePageInner />
    </Suspense>
  );
}
