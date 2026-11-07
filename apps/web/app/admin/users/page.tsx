"use client";

import { useEffect, useMemo, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { ApiError, api } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import type { Stream, User } from "../../../lib/types";
import { ErrorBox, Modal, Spinner } from "../../../components/ui";
import {
  NBAccordion,
  NBBadge,
  NBButton,
  NBConfirmModal,
  NBEmptyState,
  NBField,
  NBInput,
  NBSelect,
  NBTitle,
} from "../_nb";

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  user: "Pengguna",
  guest: "Tamu",
  super_admin: "Super Admin",
};

/* Checkbox kecil (16px) dengan border tipis dan centang putih saat aktif. */
function NBCheckbox({
  checked,
  onChange,
  disabled,
  title,
  ariaLabel,
  onClick,
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
  title?: string;
  ariaLabel?: string;
  onClick?: (e: ReactMouseEvent) => void;
}) {
  return (
    <span className="relative inline-flex h-4 w-4 shrink-0">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        onClick={onClick}
        disabled={disabled}
        title={title}
        aria-label={ariaLabel}
        className="peer h-4 w-4 cursor-pointer appearance-none rounded border border-ink-700 bg-transparent transition-colors checked:border-accent-500 checked:bg-accent-500 disabled:cursor-not-allowed disabled:opacity-40"
      />
      <svg
        className="pointer-events-none absolute inset-0 m-auto hidden h-3 w-3 text-white peer-checked:block"
        viewBox="0 0 12 12"
        fill="none"
        aria-hidden
      >
        <path
          d="M2 6.5l2.5 2.5L10 3.5"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

/* Tombol ikon ringkas ala mockup (p-1.5, ikon 16px). */
function IconBtn({
  label,
  onClick,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={`inline-flex shrink-0 cursor-pointer items-center justify-center rounded-lg p-1.5 transition-colors ${
        danger
          ? "text-bad-400 hover:bg-bad-400/10 hover:text-bad-300"
          : "text-slate-400 hover:bg-ink-800 hover:text-slate-200"
      }`}
    >
      {children}
    </button>
  );
}

/* Tombol kecil ber-border (Ubah grup, Akses Kamera). Dulu gaya ghost
   tanpa border, tapi di HP (tanpa hover) teksnya tidak terlihat seperti
   tombol, jadi diberi border + latar supaya jelas bisa diketuk. */
function MiniBtn({
  onClick,
  className = "",
  children,
}: {
  onClick: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex shrink-0 cursor-pointer items-center whitespace-nowrap rounded-md border border-ink-700 bg-ink-800 px-2.5 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:border-ink-700 hover:bg-ink-700 hover:text-slate-200 sm:text-sm ${className}`}
    >
      {children}
    </button>
  );
}

/* Indikator iklan ringkas (HP): ikon megaphone + warna saja, tanpa teks.
   Hijau = iklan tampil, abu-abu = tidak tampil. Desktop tetap pakai
   lencana teks. */
function AdsIcon({ on }: { on: boolean }) {
  return (
    <span
      title={on ? "Iklan: Ya" : "Iklan: Tidak"}
      aria-label={on ? "Iklan: Ya" : "Iklan: Tidak"}
      className={`inline-flex shrink-0 items-center justify-center rounded-full p-1.5 ${
        on ? "bg-ok-400/15 text-ok-400" : "bg-ink-800 text-slate-400"
      }`}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path
          d="M10.34 15.84c-.688-.06-1.386-.09-2.09-.09H7.5a4.5 4.5 0 110-9h.75c.704 0 1.402-.03 2.09-.09m0 9.18c.253.962.584 1.892.985 2.783.247.55.06 1.21-.463 1.511l-.657.38c-.551.318-1.26.117-1.527-.461a20.845 20.845 0 01-1.44-4.282m3.102.069a18.03 18.03 0 01-.59-4.59c0-1.586.205-3.124.59-4.59m0 9.18a23.848 23.848 0 018.835 2.535M10.34 6.66a23.847 23.847 0 008.835-2.535m0 0A23.74 23.74 0 0018.795 3.14c.383-.21.87-.05 1.07.338.196.38.09.885-.274 1.15a23.73 23.73 0 01-1.796 1.255m0 0A23.74 23.74 0 0018.795 8.14c.383.21.87.05 1.07-.338.196-.38.09-.885-.274-1.15a23.73 23.73 0 01-1.796-1.255"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

function PencilIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2M10 11v6M14 11v6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function UserIcon({ className = "" }: { className?: string }) {
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
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}



export default function AdminUsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [accessFor, setAccessFor] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);

  /* Daftar grup yang sudah ada (untuk pilihan di form). */
  const groups = useMemo(
    () =>
      [...new Set((users ?? []).map((u) => u.admin_group).filter((g): g is string => !!g))].sort(),
    [users],
  );
  const [groupEdit, setGroupEdit] = useState<{
    name: string;
    members: User[];
  } | null>(null);
  const [groupAccess, setGroupAccess] = useState<{
    name: string;
    members: User[];
  } | null>(null);
  /* Pilihan massal ala Kamera: checkbox per baris + bar bulk. */
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showGroup, setShowGroup] = useState(false);
  /* Grup yang sedang terbuka lipatannya (tertutup dulu). */
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  // Accordion anggota di HP (ala Stitch): tiap anggota bisa dilipat/dibuka
  // untuk melihat "Dibuat oleh" + aksinya. Desktop tetap baris datar.
  const [openMembers, setOpenMembers] = useState<Set<number>>(new Set());
  function toggleMember(id: number) {
    setOpenMembers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleGroup(name: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllPage() {
    /* Superadmin tidak bisa masuk grup: tidak ikut dipilih. */
    const ids = (users ?? [])
      .filter((u) => u.role !== "super_admin")
      .map((u) => u.id);
    const allChecked = ids.length > 0 && ids.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allChecked) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  /* Konsep v2: akun bergrup dikelompokkan di bawah satu baris induk
     bernama grupnya; yang tanpa grup berdiri sendiri. Grup lebih
     dahulu (urut nama), lalu akun lepas. Anggota diurutkan supaya
     pengelolanya di atas: admin dulu, lalu sisanya menurut nama. */
  const { perGrup, lepas } = useMemo(() => {
    const map = new Map<string, User[]>();
    const free: User[] = [];
    (users ?? []).forEach((u) => {
      /* Superadmin berdiri sendiri: tidak bisa masuk grup. */
      if (!u.admin_group || u.role === "super_admin") {
        free.push(u);
        return;
      }
      const list = map.get(u.admin_group) ?? [];
      list.push(u);
      map.set(u.admin_group, list);
    });
    const bobot = (r: string) =>
      r === "super_admin" || r === "admin" ? 0 : 1;
    map.forEach((list) =>
      list.sort(
        (a, b) =>
          bobot(a.role) - bobot(b.role) ||
          a.username.localeCompare(b.username),
      ),
    );
    return {
      perGrup: [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])),
      lepas: free,
    };
  }, [users]);

  /* Satu baris pengguna. Anggota grup tidak menampilkan lencana iklan:
     iklan diatur serentak di baris induk grup, dan nama grup sudah
     tertulis di sana (paritas v2.0). */
  /* Checkbox dan aksi dipakai baris lepas maupun anggota grup. */
  function checkboxFor(u: User) {
    return (
      <NBCheckbox
        checked={selected.has(u.id)}
        onChange={() => toggleSelect(u.id)}
        onClick={(e) => e.stopPropagation()}
        disabled={u.role === "super_admin"}
        title={
          u.role === "super_admin"
            ? "Superadmin berdiri sendiri, tidak bisa dimasukkan ke grup"
            : undefined
        }
        ariaLabel={`Pilih ${u.username}`}
      />
    );
  }

  /* Pilih / batalkan semua anggota satu grup sekaligus. */
  function toggleSelectGroup(members: User[]) {
    const ids = members
      .filter((m) => m.role !== "super_admin")
      .map((m) => m.id);
    const allSelected =
      ids.length > 0 && ids.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  function actionsFor(u: User) {
    return (
      /* Sisi kanan ala mockup: rata kanan, Akses Kamera ghost,
         lalu kelompok ikon pensil + tempat sampah (gap-1.5).
         Tanpa lebar tetap dan tanpa slot chevron; ikon sejajar
         karena semuanya menempel ke tepi kanan. */
      <div className="flex shrink-0 items-center gap-3 sm:gap-4">
        {/* Superadmin selalu mendapat akses ke semua kamera,
            jadi tidak ada pengaturan Akses Kamera untuknya. */}
        {u.role !== "super_admin" && (
          <MiniBtn onClick={() => setAccessFor(u)}>Akses Kamera</MiniBtn>
        )}
        <span className="flex items-center gap-1.5">
          <IconBtn label="Ubah" onClick={() => setEditing(u)}>
            <PencilIcon />
          </IconBtn>
          <IconBtn label="Hapus" danger onClick={() => setDeleting(u)}>
            <TrashIcon />
          </IconBtn>
        </span>
      </div>
    );
  }

  function roleBadge(u: User, size: "sm" | "md" = "md") {
    return (
      <NBBadge
        size={size}
        tone={
          u.role === "admin" || u.role === "super_admin"
            ? "info"
            : u.role === "guest"
              ? "muted"
              : "ok"
        }
      >
        {ROLE_LABEL[u.role] ?? u.role}
      </NBBadge>
    );
  }

  function renderUser(u: User) {
    /* Tata letak bertumpuk ala mockup (desktop): nama, lalu baris lencana
       (peran + Iklan), lalu Dibuat oleh yang kecil dan pudar. */
    const content = (
      <span className="min-w-0 flex-1 space-y-1">
        <span className="block truncate text-base font-bold text-white">
          {u.username}
        </span>
        <span className="flex flex-wrap items-center gap-2">
          {roleBadge(u)}
          <NBBadge tone={u.show_ads ? "ok" : "muted"}>
            Iklan: {u.show_ads ? "Ya" : "Tidak"}
          </NBBadge>
        </span>
        <span className="block text-xs text-slate-400">
          Dibuat oleh:{" "}
          <span className="font-medium text-slate-300">
            {u.dibuat_oleh ?? "—"}
          </span>
        </span>
      </span>
    );
    const left = (
      <div className="flex min-w-0 flex-1 items-start gap-3.5 sm:items-center">
        {checkboxFor(u)}
        {content}
      </div>
    );
    const actions = actionsFor(u);
    /* HP (ala Stitch): header accordion ringkas — nama di atas, lencana
       peran kecil di bawahnya (bukan di samping nama). */
    const mobileSummary = (
      <span className="flex min-w-0 items-center gap-2">
        {checkboxFor(u)}
        <span className="flex min-w-0 flex-col items-start gap-0.5">
          <span className="min-w-0 truncate text-sm font-bold text-white">
            {u.username}
          </span>
          <span className="shrink-0">{roleBadge(u, "sm")}</span>
        </span>
      </span>
    );
    const mobilePanel = (
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <AdsIcon on={u.show_ads} />
          <span className="min-w-0 truncate text-[11px] text-slate-400">
            Dibuat oleh:{" "}
            <span className="text-slate-300">{u.dibuat_oleh ?? "—"}</span>
          </span>
        </span>
        {actions}
      </div>
    );
    return (
      <div key={u.id}>
        <div className="md:hidden">
          <NBAccordion summary={mobileSummary}>{mobilePanel}</NBAccordion>
        </div>
        <div className="hidden items-center justify-between gap-4 rounded-2xl border border-ink-800 bg-ink-900 px-5 py-4 shadow-sm transition-colors sm:px-6 md:flex">
          {left}
          {actions}
        </div>
      </div>
    );
  }

  /* Anggota grup ala mockup: satu baris, nama text-sm, lencana
     peran di barisnya sendiri, Dibuat oleh di bawahnya; pemisah
     sangat halus antar baris, hover lembut. */
  function renderMember(u: User) {
    const mOpen = openMembers.has(u.id);
    return (
      <div key={u.id}>
        {/* HP: accordion (ala Stitch) — header ringkas nama + peran, panel
            menampilkan Dibuat oleh + aksi. */}
        <div className="md:hidden">
          <button
            type="button"
            onClick={() => toggleMember(u.id)}
            aria-expanded={mOpen}
            className="flex w-full cursor-pointer items-center justify-between gap-3 p-3 pl-4 text-left transition-colors hover:bg-ink-850"
          >
            <span className="flex min-w-0 flex-1 items-center gap-2.5">
              {checkboxFor(u)}
              {/* Nama di atas, lencana peran kecil di bawahnya (bukan di samping). */}
              <span className="flex min-w-0 flex-col items-start gap-0.5">
                <span className="truncate text-sm font-bold text-white">
                  {u.username}
                </span>
                {roleBadge(u, "sm")}
              </span>
            </span>
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              aria-hidden
              className={`shrink-0 text-slate-400 transition-transform duration-200 ease-out ${mOpen ? "rotate-180" : ""}`}
            >
              <path
                d="M4 6l4 4 4-4"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          {mOpen && (
            <div className="flex items-center justify-between gap-2 border-t border-ink-850 bg-ink-850/40 px-4 py-2">
              <p className="min-w-0 truncate text-[11px] text-slate-400">
                Dibuat oleh:{" "}
                <span className="text-slate-300">
                  {u.dibuat_oleh ?? "—"}
                </span>
              </p>
              {actionsFor(u)}
            </div>
          )}
        </div>
        {/* Desktop: baris datar (tetap). */}
        <div className="hidden items-center justify-between gap-4 px-5 py-3.5 hover:bg-ink-850 sm:px-6 md:flex">
          <div className="flex min-w-0 flex-1 items-start gap-3.5 pl-2 sm:items-center sm:pl-4">
            {checkboxFor(u)}
            <span className="min-w-0 flex-1 space-y-1">
              <span className="block truncate text-sm font-semibold text-white">
                {u.username}
              </span>
              <span className="flex flex-wrap items-center gap-2">
                {roleBadge(u)}
              </span>
              <span className="block text-xs text-slate-400">
                Dibuat oleh:{" "}
                <span className="font-medium text-slate-300">
                  {u.dibuat_oleh ?? "—"}
                </span>
              </span>
            </span>
          </div>
          {actionsFor(u)}
        </div>
      </div>
    );
  }

  const load = () =>
    api
      .get<User[]>("/admin/users")
      .then(setUsers)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "Gagal memuat pengguna");
        setUsers([]);
      });

  useEffect(() => {
    load();
    api.get<Stream[]>("/admin/streams").then((d) => setStreams(d ?? [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function doDelete() {
    if (!deleting) return;
    try {
      await api.del(`/admin/users/${deleting.id}`);
      setDeleting(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus");
    }
  }

  return (
    <div>
      <NBTitle
        title="Pengguna"
        desc="Kelola akun dan hak akses kamera"
        action={
          <NBButton
            className="w-full sm:w-auto"
            onClick={() => setShowAdd(true)}
          >
            + Tambah Pengguna
          </NBButton>
        }
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {users === null ? (
        <Spinner />
      ) : users.length === 0 ? (
        <NBEmptyState icon={<UserIcon className="h-8 w-8 text-slate-500" />} text="Belum ada pengguna." />
      ) : (
        <>
          {/* Bar bulk ala Kamera */}
          {selected.size > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-ink-800 shadow-sm px-4 py-3">
              <span className="text-sm text-slate-300">
                {selected.size} dipilih
              </span>
              <NBButton
                variant="secondary"
                onClick={() => setShowGroup(true)}
              >
                Set grup ({selected.size})
              </NBButton>
              <button
                type="button"
                onClick={() => setSelected(new Set())}
                className="inline-flex min-h-[44px] items-center rounded-lg px-3 text-sm text-slate-400 hover:text-slate-200"
              >
                Batalkan pilihan
              </button>
            </div>
          )}
          <div className="mb-2 flex items-center gap-3 px-1">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-400">
              <NBCheckbox
                checked={
                  (users ?? []).filter((u) => u.role !== "super_admin")
                    .length > 0 &&
                  (users ?? [])
                    .filter((u) => u.role !== "super_admin")
                    .every((u) => selected.has(u.id))
                }
                onChange={toggleSelectAllPage}
                ariaLabel="Pilih semua di halaman ini"
              />
              Pilih semua di halaman ini
            </label>
          </div>
          <div className="space-y-3">
          {perGrup.map(([name, members]) => {
            const allAds =
              members.length > 0 && members.every((m) => m.show_ads);
            const open = openGroups.has(name);
            return (
              <div
                key={name}
                className="overflow-hidden rounded-2xl border border-ink-800 bg-ink-900 shadow-sm"
              >
                <div className="border-b border-ink-850 px-5 py-3 sm:px-6 md:py-4">
                  {/* Nama grup di atas (HP): baris sendiri, lebar penuh, tidak terpotong. */}
                  <button
                    onClick={() => toggleGroup(name)}
                    aria-expanded={open}
                    className="mb-2 flex w-full min-w-0 cursor-pointer items-center gap-2 rounded-lg text-left transition-colors hover:bg-ink-700/40 md:hidden"
                  >
                    <NBBadge tone="info">Grup</NBBadge>
                    {/* Nama + hitungan menempel (tanpa flex-1) supaya hitungan
                        tidak terlepas ke ujung kanan. */}
                    <span className="min-w-0 truncate text-sm font-bold text-white">
                      {name}
                    </span>
                    <span className="shrink-0 text-xs text-slate-400">
                      · {members.length} anggota
                    </span>
                  </button>
                  {/* Baris kontrol. */}
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex min-w-0 flex-1 items-center gap-3">
                      {/* Label "Pilih grup" (HP saja) supaya baris kontrol
                          tidak kosong melompong; klik teks ikut mencentang. */}
                      <label className="flex cursor-pointer items-center gap-2">
                        <NBCheckbox
                          checked={
                            members.length > 0 &&
                            members.every((m) => selected.has(m.id))
                          }
                          onChange={() => toggleSelectGroup(members)}
                          ariaLabel={`Pilih semua anggota ${name}`}
                        />
                        <span className="text-xs text-slate-400 md:hidden">
                          Pilih grup
                        </span>
                      </label>
                      {/* Toggle desktop (sembunyi di HP karena nama sudah di atas). */}
                      <button
                        onClick={() => toggleGroup(name)}
                        aria-expanded={open}
                        className="hidden min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-lg px-2 py-1 text-left transition-colors hover:bg-ink-700/40 md:flex"
                      >
                        <NBBadge tone="info">Grup</NBBadge>
                        <span className="flex min-w-0 items-baseline gap-1.5">
                          <span className="truncate text-base font-bold text-white">
                            {name}
                          </span>
                          <span className="shrink-0 text-xs text-slate-400 sm:text-sm">
                            · {members.length} anggota
                          </span>
                        </span>
                        <span className="shrink-0">
                          <NBBadge tone={allAds ? "ok" : "muted"}>
                            Iklan: {allAds ? "Ya" : "Tidak"}
                          </NBBadge>
                        </span>
                      </button>
                    </div>
                    <div className="flex shrink-0 items-center gap-3 sm:gap-4">
                      {/* Ubah grup + Akses Kamera: hanya di desktop; di HP pindah ke bar detail.
                          Dibungkus span (bukan class hidden di tombol) karena
                          display inline-flex MiniBtn mengalahkan hidden. */}
                      <span className="hidden md:block">
                        <MiniBtn onClick={() => setGroupEdit({ name, members })}>
                          Ubah grup
                        </MiniBtn>
                      </span>
                      {/* Akses grup hanya saat grup terbuka (ala Stitch):
                          saat tertutup hanya Ubah grup + chevron. */}
                      {open && (
                        <span className="hidden md:block">
                          <MiniBtn onClick={() => setGroupAccess({ name, members })}>
                            <span className="hidden sm:inline">Akses Kamera</span>
                            <span className="sm:hidden">Akses</span>
                          </MiniBtn>
                        </span>
                      )}
                      <button
                        onClick={() => toggleGroup(name)}
                        aria-expanded={open}
                        aria-label={open ? "Tutup grup" : "Buka grup"}
                        className="shrink-0 cursor-pointer rounded p-1 text-slate-400 transition-colors hover:bg-ink-800 hover:text-slate-200"
                      >
                        <svg
                          width="20"
                          height="20"
                          viewBox="0 0 16 16"
                          fill="none"
                          aria-hidden
                          className={`shrink-0 text-slate-400 transition-transform duration-200 ease-out ${open ? "rotate-180" : ""}`}
                        >
                          <path
                            d="M4 6l4 4 4-4"
                            stroke="currentColor"
                            strokeWidth="1.75"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
                {/* Bar detail grup, HP saja (ala Stitch): lencana Iklan + Ubah grup
                    + Akses Kamera, muncul saat grup terbuka. */}
                {open && (
                  <div className="flex items-center justify-between gap-2 border-b border-ink-850 bg-ink-850/40 p-3 sm:px-4 md:hidden">
                    <AdsIcon on={allAds} />
                    <div className="flex shrink-0 items-center gap-1">
                      <MiniBtn onClick={() => setGroupEdit({ name, members })}>
                        Ubah grup
                      </MiniBtn>
                      <MiniBtn onClick={() => setGroupAccess({ name, members })}>
                        Akses Kamera
                      </MiniBtn>
                    </div>
                  </div>
                )}
                {open && (
                  <div className="divide-y divide-ink-850">
                    {members.map((u) => renderMember(u))}
                  </div>
                )}
              </div>
            );
          })}
          {lepas.map((u) => renderUser(u))}
          </div>
        </>
      )}

      {showAdd && (
        <UserFormModal
          me={me}
          groups={groups}
          onClose={() => setShowAdd(false)}
          onDone={() => {
            setShowAdd(false);
            load();
          }}
        />
      )}
      {editing && (
        <UserFormModal
          user={editing}
          me={me}
          groups={groups}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            load();
          }}
        />
      )}
      {groupEdit && (
        <GroupEditModal
          name={groupEdit.name}
          members={groupEdit.members}
          me={me}
          onClose={() => setGroupEdit(null)}
          onDone={() => {
            setGroupEdit(null);
            load();
          }}
        />
      )}
      {groupAccess && (
        <GroupAccessModal
          name={groupAccess.name}
          members={groupAccess.members}
          streams={streams}
          onClose={() => setGroupAccess(null)}
          onDone={() => {
            setGroupAccess(null);
            load();
          }}
        />
      )}
      {showGroup && (
        <BulkGroupModal
          count={selected.size}
          groups={groups}
          onClose={() => setShowGroup(false)}
          onDone={async (groupName) => {
            /* admin_group hanya string di akun: set ke pengguna
               terpilih tidak menghapus anggota lama grup. */
            await Promise.all(
              [...selected].map((id) =>
                api.put(`/admin/users/${id}`, { admin_group: groupName }),
              ),
            );
            setShowGroup(false);
            setSelected(new Set());
            load();
          }}
        />
      )}
      {accessFor && (
        <AccessModal
          user={accessFor}
          streams={streams}
          onClose={() => setAccessFor(null)}
        />
      )}
      {deleting && (
        <NBConfirmModal
          title="Hapus pengguna"
          message={`Hapus akun "${deleting.username}"?`}
          onCancel={() => setDeleting(null)}
          onConfirm={doDelete}
        />
      )}
    </div>
  );
}

function UserFormModal({
  user,
  me,
  groups,
  onClose,
  onDone,
}: {
  user?: User;
  me: User | null;
  groups: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<string>(user?.role ?? "user");
  const [group, setGroup] = useState(user?.admin_group ?? "");
  const [showAds, setShowAds] = useState(user?.show_ads ?? true);
  /* Superadmin berdiri sendiri dan punya semua hak: tidak bisa
     dimasukkan ke grup. */
  const isSuperAdmin = role === "super_admin";
  const groupEditable = me?.role === "super_admin" && !isSuperAdmin;
  /* Grup efektif akun ini: yang diketik (superadmin yang mengatur),
     grup akun yang diubah, atau grup pembuatnya (admin biasa yang
     menambah akun baru mengikuti grupnya). */
  const effectiveGroup = isSuperAdmin
    ? ""
    : groupEditable
      ? group.trim()
      : user
        ? (user.admin_group ?? "").trim()
        : (me?.admin_group ?? "").trim();
  /* Iklan diatur di grup bila akun ini masuk grup; pengaturan per
     akun disembunyikan agar tidak bertabrakan dengan setting grup. */
  const inGroup = effectiveGroup !== "";
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setError("");
    setBusy(true);
    try {
      if (user) {
        const body: Record<string, unknown> = {
          username: username.trim(),
          role,
          admin_group: role === "super_admin" ? null : group.trim() || null,
        };
        if (!inGroup) body.show_ads = showAds;
        if (password) body.password = password;
        await api.put(`/admin/users/${user.id}`, body);
      } else {
        await api.post("/admin/users", {
          username: username.trim(),
          password,
          role,
          ...(inGroup ? {} : { show_ads: showAds }),
          admin_group: role === "super_admin" ? null : group.trim() || null,
        });
      }
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={user ? "Ubah Pengguna" : "Tambah Pengguna"} onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="space-y-4">
        <NBField label="Nama pengguna">
          <NBInput
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </NBField>
        <NBField
          label={user ? "Kata sandi baru (kosongkan bila tidak diubah)" : "Kata sandi"}
          hint={!user ? "Minimal 8 karakter" : undefined}
        >
          <NBInput
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </NBField>
        <NBField label="Peran">
          <NBSelect value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="user">Pengguna</option>
            <option value="admin">Admin</option>
            <option value="guest">Tamu</option>
            {/* Super Admin hanya bisa dibuat super_admin lain; admin
                biasa tidak ditawari pilihan ini (backend juga menolak
                dengan 403). Opsi tetap tampil bila targetnya memang
                sudah super_admin agar pilihannya tidak kosong. */}
            {(me?.role === "super_admin" || role === "super_admin") && (
              <option value="super_admin">Super Admin</option>
            )}
          </NBSelect>
        </NBField>
        <NBField
          label="Grup"
          hint={
            isSuperAdmin
              ? "Superadmin berdiri sendiri dan punya semua hak"
              : me?.role === "super_admin"
                ? "Kelompok wilayah akun ini (kosong = tanpa grup)"
                : "Mengikuti grup Anda"
          }
        >
          <NBInput
            value={
              groupEditable
                ? group
                : isSuperAdmin
                  ? ""
                  : (me?.admin_group ?? "")
            }
            onChange={(e) => setGroup(e.target.value)}
            disabled={!groupEditable}
            placeholder="cth. grup-jakarta"
            list="grup-wilayah"
          />
          <datalist id="grup-wilayah">
            {groups.map((g) => (
              <option key={g} value={g} />
            ))}
          </datalist>
        </NBField>
        {!inGroup && (
          <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 rounded-xl bg-ink-800 shadow-sm px-4 py-3">
            <span>
              <span className="block text-sm font-medium text-white">
                Tampilkan Iklan
              </span>
              <span className="block text-xs text-slate-400">
                Banner iklan tampil untuk akun ini
              </span>
            </span>
            <input
              type="checkbox"
              checked={showAds}
              onChange={(e) => setShowAds(e.target.checked)}
              className="h-5 w-5 shrink-0 accent-accent-500"
              aria-label="Tampilkan Iklan"
            />
          </label>
        )}
        <NBButton
          onClick={save}
          disabled={busy || !username.trim() || (!user && !password)}
          className="w-full"
        >
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}

/* ---------- Modal massal: set grup ala Kamera ---------- */

function BulkGroupModal({
  count,
  groups,
  onClose,
  onDone,
}: {
  count: number;
  groups: string[];
  onClose: () => void;
  onDone: (groupName: string) => Promise<void>;
}) {
  const NEW = "__baru__";
  const [picked, setPicked] = useState(groups[0] ?? NEW);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const name = picked === NEW ? newName.trim() : picked;
  const valid = name !== "";

  return (
    <Modal title={`Set grup (${count} pengguna)`} onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <NBField label="Grup">
        <NBSelect value={picked} onChange={(e) => setPicked(e.target.value)}>
          {groups.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
          <option value={NEW}>+ Grup baru…</option>
        </NBSelect>
      </NBField>
      {picked === NEW && (
        <div className="mt-3">
          <NBField label="Nama grup baru">
            <NBInput
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="cth. Lantai 1"
            />
          </NBField>
        </div>
      )}
      <p className="mt-3 text-xs leading-relaxed text-slate-400">
        Pengguna terpilih ditambahkan ke grup. Pengguna yang sudah ada di
        grup tetap dipertahankan.
      </p>
      <NBButton
        className="mt-4 w-full"
        disabled={!valid || busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onDone(name);
          } catch (e) {
            setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Menyimpan…" : "Tambahkan ke grup"}
      </NBButton>
    </Modal>
  );
}

/* ---------- Modal: ubah nama grup + iklan serentak seisi grup ---------- */

function GroupEditModal({
  name,
  members,
  me,
  onClose,
  onDone,
}: {
  name: string;
  members: User[];
  me: User | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [newName, setNewName] = useState(name);
  const [adsOn, setAdsOn] = useState(members.every((m) => m.show_ads));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /* Hanya superadmin yang bisa mengubah nama grup; admin biasa
     terkunci di grupnya sendiri (aturan yang sama seperti form). */
  const canRename = me?.role === "super_admin";
  const nameChanged = newName.trim() !== "" && newName.trim() !== name;
  const adsChanged = members.some((m) => m.show_ads !== adsOn);
  const valid = newName.trim() !== "" && (nameChanged || adsChanged);

  async function save() {
    setError("");
    setBusy(true);
    try {
      const target = newName.trim();
      await Promise.all(
        members.map(async (m) => {
          const body: Record<string, unknown> = {};
          if (nameChanged) body.admin_group = target;
          if (m.show_ads !== adsOn) body.show_ads = adsOn;
          if (Object.keys(body).length > 0) {
            await api.put(`/admin/users/${m.id}`, body);
          }
        }),
      );
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Ubah grup — ${name}`} onClose={onClose}>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      <div className="space-y-4">
        <NBField
          label="Nama grup"
          hint={
            canRename
              ? undefined
              : "Hanya superadmin yang bisa mengubah nama grup"
          }
        >
          <NBInput
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            disabled={!canRename}
          />
        </NBField>
        <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 rounded-xl bg-ink-800 shadow-sm px-4 py-3">
          <span>
            <span className="block text-sm font-medium text-white">
              Tampilkan Iklan
            </span>
            <span className="block text-xs text-slate-400">
              Banner iklan tampil untuk semua anggota grup ini
            </span>
          </span>
          <input
            type="checkbox"
            checked={adsOn}
            onChange={(e) => setAdsOn(e.target.checked)}
            className="h-5 w-5 shrink-0 accent-accent-500"
            aria-label="Tampilkan Iklan untuk grup"
          />
        </label>
        <p className="text-xs text-slate-400">{members.length} anggota</p>
        <NBButton onClick={save} disabled={busy || !valid} className="w-full">
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}

/* ---------- Modal: akses kamera seisi grup ---------- */

function GroupAccessModal({
  name,
  members,
  streams,
  onClose,
  onDone,
}: {
  name: string;
  members: User[];
  streams: Stream[];
  onClose: () => void;
  onDone: () => void;
}) {
  /* Kolom Bagikan hanya bila grup berisi anggota admin. */
  const hasAdmin = members.some((m) => m.role === "admin");
  const [access, setAccess] = useState<Record<number, GrantFlags>>({});
  const [initial, setInitial] = useState<Record<number, GrantFlags> | null>(
    null,
  );
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const adminMembers = members.filter((m) => m.role === "admin");
    Promise.all([
      Promise.all(
        members.map((m) =>
          api
            .get<{
              shares: { stream_id: number; can_playback: boolean }[];
            }>(`/admin/users/${m.id}/camera-access`)
            .then((r) => r.shares ?? [])
            .catch(() => [] as { stream_id: number; can_playback: boolean }[]),
        ),
      ),
      Promise.all(
        adminMembers.map((m) =>
          api
            .get<{
              grants: {
                stream_id: number;
                can_view: boolean;
                can_playback: boolean;
                can_reshare: boolean;
              }[];
            }>(`/admin/admins/${m.id}/camera-grants`)
            .then((r) => r.grants ?? [])
            .catch(
              () =>
                [] as {
                  stream_id: number;
                  can_view: boolean;
                  can_playback: boolean;
                  can_reshare: boolean;
                }[],
            ),
        ),
      ),
    ])
      .then(([accessLists, grantLists]) => {
        if (cancelled) return;
        /* Akses grup = yang dimiliki SEMUA anggota; Bagikan = yang
           dimiliki SEMUA anggota admin. */
        const map: Record<number, GrantFlags> = {};
        for (const s of streams) {
          const live = accessLists.every((list) =>
            list.some((sh) => sh.stream_id === s.id),
          );
          const playback = accessLists.every((list) =>
            list.some(
              (sh) => sh.stream_id === s.id && sh.can_playback,
            ),
          );
          const reshare =
            adminMembers.length > 0 &&
            grantLists.every((list) =>
              list.some(
                (g) => g.stream_id === s.id && g.can_reshare,
              ),
            );
          if (live || playback || reshare) {
            map[s.id] = {
              can_view: live,
              can_playback: playback,
              can_reshare: reshare,
            };
          }
        }
        setAccess(map);
        setInitial(map);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "Gagal memuat hak akses");
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [members]);

  function setFlag(
    id: number,
    key: "can_view" | "can_playback" | "can_reshare",
    value: boolean,
  ) {
    setAccess((prev) => {
      const cur = prev[id] ?? {
        can_view: false,
        can_playback: false,
        can_reshare: false,
      };
      const next = { ...cur, [key]: value };
      /* Playback dan Bagikan butuh Live; mematikan Live ikut
         mematikan keduanya. */
      if ((key === "can_playback" || key === "can_reshare") && value) {
        next.can_view = true;
      }
      if (key === "can_view" && !value) {
        next.can_playback = false;
        next.can_reshare = false;
      }
      return { ...prev, [id]: next };
    });
  }

  const changed =
    initial !== null &&
    (Object.keys(access).length !== Object.keys(initial).length ||
      Object.entries(access).some(([sid, a]) => {
        const b = initial[Number(sid)];
        return (
          !b ||
          b.can_view !== a.can_view ||
          b.can_playback !== a.can_playback ||
          b.can_reshare !== a.can_reshare
        );
      }));

  const grantedCount = Object.values(access).filter(
    (a) => a.can_view || a.can_playback || a.can_reshare,
  ).length;

  async function save() {
    setError("");
    setBusy(true);
    try {
      const selected = Object.entries(access).filter(
        ([, a]) => a.can_view || a.can_playback || a.can_reshare,
      );
      /* Akses tiap anggota diganti dengan pilihan grup. */
      await Promise.all(
        members.map((m) =>
          api.post(`/admin/users/${m.id}/camera-access`, {
            shares: selected.map(([sid, a]) => ({
              stream_id: Number(sid),
              can_playback: a.can_playback,
            })),
          }),
        ),
      );
      /* Anggota admin: grant-nya ikut diselaraskan per kamera. */
      const adminMembers = members.filter((m) => m.role === "admin");
      await Promise.all(
        adminMembers.flatMap((m) =>
          streams.map((s) => {
            const a = access[s.id] ?? {
              can_view: false,
              can_playback: false,
              can_reshare: false,
            };
            return api.post(`/admin/streams/${s.id}/grants`, {
              grants: [
                {
                  admin_id: m.id,
                  can_view: a.can_view,
                  can_playback: a.can_playback,
                  can_reshare: a.can_reshare,
                },
              ],
            });
          }),
        ),
      );
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Akses kamera — ${name}`} onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {!loaded ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : streams.length === 0 ? (
        <NBEmptyState text="Belum ada kamera." />
      ) : (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <p className="text-xs tabular-nums text-slate-400">
              {grantedCount} dari {streams.length} dipilih
            </p>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() =>
                  setAccess((prev) => {
                    const next: Record<number, GrantFlags> = { ...prev };
                    for (const s of streams) {
                      next[s.id] = {
                        ...(next[s.id] ?? {
                          can_view: false,
                          can_playback: false,
                          can_reshare: false,
                        }),
                        can_view: true,
                      };
                    }
                    return next;
                  })
                }
                className="min-h-[44px] rounded-md px-2 text-xs font-medium text-accent-300 transition-colors hover:bg-ink-800"
              >
                Pilih semua
              </button>
              <button
                type="button"
                onClick={() => setAccess({})}
                className="min-h-[44px] rounded-md px-2 text-xs font-medium text-slate-400 transition-colors hover:bg-ink-800"
              >
                Bersihkan
              </button>
            </div>
          </div>
          <p className="mb-3 text-xs leading-relaxed text-slate-400">
            Yang tercentang = kamera yang dimiliki semua anggota grup.
            Menyimpan akan mengganti akses kamera semua anggota grup
            dengan pilihan ini.
            {hasAdmin &&
              " Kolom Bagikan hanya berlaku untuk anggota admin."}
          </p>
          <div className="mb-1 flex items-center gap-2 px-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            <span className="min-w-0 flex-1">Kamera</span>
            <span className="w-16 shrink-0 text-center">Live</span>
            <span className="w-16 shrink-0 text-center">Playback</span>
            {hasAdmin && (
              <span className="w-16 shrink-0 text-center">Bagikan</span>
            )}
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {streams.map((s) => {
              const a = access[s.id] ?? {
                can_view: false,
                can_playback: false,
                can_reshare: false,
              };
              return (
                <div
                  key={s.id}
                  className="flex min-h-[48px] items-center gap-2 rounded-lg px-3 py-2 hover:bg-ink-800"
                >
                  <span className="min-w-0 flex-1 truncate text-sm text-slate-200">
                    {s.name}
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <input
                      type="checkbox"
                      checked={a.can_view}
                      onChange={(e) =>
                        setFlag(s.id, "can_view", e.target.checked)
                      }
                      className="h-5 w-5 accent-accent-500"
                      aria-label={`Live ${s.name}`}
                    />
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <input
                      type="checkbox"
                      checked={a.can_playback}
                      onChange={(e) =>
                        setFlag(s.id, "can_playback", e.target.checked)
                      }
                      className="h-5 w-5 accent-accent-500"
                      aria-label={`Playback ${s.name}`}
                    />
                  </span>
                  {hasAdmin && (
                    <span className="flex w-16 shrink-0 justify-center">
                      <input
                        type="checkbox"
                        checked={a.can_reshare}
                        onChange={(e) =>
                          setFlag(s.id, "can_reshare", e.target.checked)
                        }
                        className="h-5 w-5 accent-accent-500"
                        aria-label={`Bagikan ${s.name}`}
                      />
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <NBButton variant="secondary" onClick={onClose}>
          Batal
        </NBButton>
        <NBButton onClick={save} disabled={busy || !loaded || !changed}>
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}

type AccessFlags = {
  can_view: boolean;
  can_playback: boolean;
};

/* ---------- Modal: akses kamera user/tamu (Live, Playback) ---------- */

function UserAccessModal({
  user,
  streams,
  onClose,
}: {
  user: User;
  streams: Stream[];
  onClose: () => void;
}) {
  const [access, setAccess] = useState<Record<number, AccessFlags>>({});
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<{
        shares: { stream_id: number; can_playback: boolean }[];
      }>(`/admin/users/${user.id}/camera-access`)
      .then((r) => {
        const map: Record<number, AccessFlags> = {};
        for (const sh of r.shares ?? []) {
          map[sh.stream_id] = {
            can_view: true,
            can_playback: sh.can_playback,
          };
        }
        setAccess(map);
      })
      .catch((e) => {
        setLoadFailed(true);
        setError(e instanceof ApiError ? e.message : "Gagal memuat hak akses");
      })
      .finally(() => setLoaded(true));
  }, [user.id]);

  function setFlag(
    id: number,
    key: "can_view" | "can_playback",
    value: boolean,
  ) {
    setAccess((prev) => {
      const cur = prev[id] ?? { can_view: false, can_playback: false };
      const next = { ...cur, [key]: value };
      /* Playback butuh Live; mematikan Live ikut mematikan Playback. */
      if (key === "can_playback" && value) next.can_view = true;
      if (key === "can_view" && !value) next.can_playback = false;
      return { ...prev, [id]: next };
    });
  }

  const grantedCount = Object.values(access).filter(
    (a) => a.can_view || a.can_playback,
  ).length;

  async function save() {
    setError("");
    setBusy(true);
    try {
      const shares = Object.entries(access)
        .filter(([, a]) => a.can_view || a.can_playback)
        .map(([sid, a]) => ({
          stream_id: Number(sid),
          can_playback: a.can_playback,
        }));
      await api.post(`/admin/users/${user.id}/camera-access`, { shares });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Akses kamera — ${user.username}`} onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {!loaded ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : streams.length === 0 ? (
        <NBEmptyState text="Belum ada kamera." />
      ) : (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <p className="text-xs tabular-nums text-slate-400">
              {grantedCount} dari {streams.length} dipilih
            </p>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() =>
                  setAccess((prev) => {
                    const next: Record<number, AccessFlags> = { ...prev };
                    for (const s of streams) {
                      next[s.id] = {
                        ...(next[s.id] ?? {
                          can_view: false,
                          can_playback: false,
                        }),
                        can_view: true,
                      };
                    }
                    return next;
                  })
                }
                className="min-h-[44px] rounded-md px-2 text-xs font-medium text-accent-300 transition-colors hover:bg-ink-800"
              >
                Pilih semua
              </button>
              <button
                type="button"
                onClick={() => setAccess({})}
                className="min-h-[44px] rounded-md px-2 text-xs font-medium text-slate-400 transition-colors hover:bg-ink-800 hover:text-slate-200"
              >
                Bersihkan
              </button>
            </div>
          </div>
          <div className="mb-1 flex items-center gap-2 px-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            <span className="min-w-0 flex-1">Kamera</span>
            <span className="w-16 shrink-0 text-center">Live</span>
            <span className="w-16 shrink-0 text-center">Playback</span>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {streams.map((s) => {
              const a = access[s.id] ?? {
                can_view: false,
                can_playback: false,
              };
              return (
                <div
                  key={s.id}
                  className="flex min-h-[48px] items-center gap-2 rounded-lg px-3 py-2 hover:bg-ink-800"
                >
                  <span className="min-w-0 flex-1 truncate text-sm text-slate-200">
                    {s.name}
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <input
                      type="checkbox"
                      checked={a.can_view}
                      onChange={(e) =>
                        setFlag(s.id, "can_view", e.target.checked)
                      }
                      className="h-5 w-5 accent-accent-500"
                      aria-label={`Live ${s.name}`}
                    />
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <input
                      type="checkbox"
                      checked={a.can_playback}
                      onChange={(e) =>
                        setFlag(s.id, "can_playback", e.target.checked)
                      }
                      className="h-5 w-5 accent-accent-500"
                      aria-label={`Playback ${s.name}`}
                    />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <NBButton variant="secondary" onClick={onClose}>
          Batal
        </NBButton>
        <NBButton onClick={save} disabled={busy || !loaded || loadFailed}>
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}

/* ---------- Modal Akses Kamera: sadar peran ---------- */

function AccessModal({
  user,
  streams,
  onClose,
}: {
  user: User;
  streams: Stream[];
  onClose: () => void;
}) {
  /* Admin diatur lewat grant (live/playback/bagikan); user/tamu lewat
     daftar kamera biasa. */
  if (user.role === "admin") {
    return <AdminGrantModal user={user} streams={streams} onClose={onClose} />;
  }
  return <UserAccessModal user={user} streams={streams} onClose={onClose} />;
}

type GrantFlags = {
  can_view: boolean;
  can_playback: boolean;
  can_reshare: boolean;
};

const EMPTY_GRANT: GrantFlags = {
  can_view: false,
  can_playback: false,
  can_reshare: false,
};

/* ---------- Modal: grant admin per kamera (live/playback/bagikan) ---------- */

function AdminGrantModal({
  user,
  streams,
  onClose,
}: {
  user: User;
  streams: Stream[];
  onClose: () => void;
}) {
  const [grants, setGrants] = useState<Record<number, GrantFlags>>({});
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<{
        grants: {
          stream_id: number;
          can_view: boolean;
          can_playback: boolean;
          can_reshare: boolean;
        }[];
      }>(`/admin/admins/${user.id}/camera-grants`)
      .then((r) => {
        const map: Record<number, GrantFlags> = {};
        for (const g of r.grants ?? []) {
          map[g.stream_id] = {
            can_view: g.can_view,
            can_playback: g.can_playback,
            can_reshare: g.can_reshare,
          };
        }
        setGrants(map);
      })
      .catch((e) => {
        setLoadFailed(true);
        setError(e instanceof ApiError ? e.message : "Gagal memuat hak akses");
      })
      .finally(() => setLoaded(true));
  }, [user.id]);

  function setFlag(
    id: number,
    key: "can_view" | "can_playback" | "can_reshare",
    value: boolean,
  ) {
    setGrants((prev) => {
      const cur = prev[id] ?? { ...EMPTY_GRANT };
      const next = { ...cur, [key]: value };
      /* Bagikan butuh Live; mematikan Live ikut mematikan Bagikan. */
      if (key === "can_reshare" && value) next.can_view = true;
      if (key === "can_view" && !value) next.can_reshare = false;
      return { ...prev, [id]: next };
    });
  }

  async function save() {
    setError("");
    setBusy(true);
    try {
      const list = Object.entries(grants)
        .filter(([, g]) => g.can_view || g.can_playback)
        .map(([sid, g]) => ({ stream_id: Number(sid), ...g }));
      await api.post(`/admin/admins/${user.id}/camera-grants`, {
        grants: list,
      });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Akses kamera — ${user.username}`} onClose={onClose} wide>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {!loaded ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : streams.length === 0 ? (
        <NBEmptyState text="Belum ada kamera." />
      ) : (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <p className="text-xs leading-relaxed text-slate-400">
              Bagikan yang dicentang berarti admin ini bisa meneruskan kamera
              ke user di grupnya.
            </p>
            <div className="flex shrink-0 gap-1">
              <button
                type="button"
                onClick={() =>
                  setGrants((prev) => {
                    const next: Record<number, GrantFlags> = { ...prev };
                    for (const s of streams) {
                      next[s.id] = {
                        ...(next[s.id] ?? { ...EMPTY_GRANT }),
                        can_view: true,
                      };
                    }
                    return next;
                  })
                }
                className="min-h-[44px] rounded-md px-2 text-xs font-medium text-accent-300 transition-colors hover:bg-ink-800"
              >
                Pilih semua
              </button>
              <button
                type="button"
                onClick={() => setGrants({})}
                className="min-h-[44px] rounded-md px-2 text-xs font-medium text-slate-400 transition-colors hover:bg-ink-800"
              >
                Bersihkan
              </button>
            </div>
          </div>
          <div className="mb-1 flex items-center gap-2 px-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            <span className="min-w-0 flex-1">Kamera</span>
            <span className="w-16 shrink-0 text-center">Live</span>
            <span className="w-16 shrink-0 text-center">Playback</span>
            <span className="w-16 shrink-0 text-center">Bagikan</span>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {streams.map((s) => {
              const g = grants[s.id] ?? { ...EMPTY_GRANT };
              return (
                <div
                  key={s.id}
                  className="flex min-h-[48px] items-center gap-2 rounded-lg px-3 py-2 hover:bg-ink-800"
                >
                  <span className="min-w-0 flex-1 truncate text-sm text-slate-200">
                    {s.name}
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <input
                      type="checkbox"
                      checked={g.can_view}
                      onChange={(e) =>
                        setFlag(s.id, "can_view", e.target.checked)
                      }
                      className="h-5 w-5 accent-accent-500"
                      aria-label={`Live ${s.name}`}
                    />
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <input
                      type="checkbox"
                      checked={g.can_playback}
                      onChange={(e) =>
                        setFlag(s.id, "can_playback", e.target.checked)
                      }
                      className="h-5 w-5 accent-accent-500"
                      aria-label={`Playback ${s.name}`}
                    />
                  </span>
                  <span className="flex w-16 shrink-0 justify-center">
                    <input
                      type="checkbox"
                      checked={g.can_reshare}
                      onChange={(e) =>
                        setFlag(s.id, "can_reshare", e.target.checked)
                      }
                      className="h-5 w-5 accent-accent-500"
                      aria-label={`Bagikan ${s.name}`}
                    />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <NBButton variant="secondary" onClick={onClose}>
          Batal
        </NBButton>
        <NBButton onClick={save} disabled={busy || !loaded || loadFailed}>
          {busy ? "Menyimpan…" : "Simpan"}
        </NBButton>
      </div>
    </Modal>
  );
}
