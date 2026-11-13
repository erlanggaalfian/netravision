"use client";

/* Primitif UI bahasa desain modern, KHUSUS halaman admin.
   Selaras dengan components/ui.tsx: gradient buttons + glow, panel modern
   (nv-panel-modern), heading besar/bold. Permukaan SOLID (tanpa blur),
   memakai token tema (ink/accent/slate) sehingga mode gelap/terang benar. */

import { useEffect, useId, useState, type ReactNode } from "react";

export function NBCard({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`nv-panel-modern p-4 sm:p-5 ${className}`}
    >
      {children}
    </div>
  );
}

export function NBTitle({
  title,
  desc,
  action,
}: {
  title: string;
  desc?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-[28px] font-extrabold tracking-tight text-slate-100">{title}</h1>
        {desc && (
          <p className="mt-1.5 max-w-2xl text-[15px] leading-relaxed text-slate-400">
            {desc}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

/* Varian tombol "secondary": ALIAS dari Button "subtle"
   (components/ui.tsx). Keduanya SENGAJA identik, class yang sama persis:
   "bg-ink-800 text-slate-200 hover:bg-ink-700".
   Kapan memakai yang mana: NBButton variant="secondary" untuk menu admin,
   Button variant="subtle" untuk menu utama. Jangan menulis class
   varian ini secara manual di tempat lain, pakai salah satu varian di atas.
   Kalau tampilannya perlu berubah, ubah KEDUA definisi sekaligus supaya
   tetap identik; cek dengan:
   grep -h 'bg-ink-800 text-slate-200 hover:bg-ink-700' components/ui.tsx app/admin/_nb.tsx */
type NBBtnVariant = "primary" | "secondary" | "danger";

export function NBButton({
  children,
  variant = "primary",
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: NBBtnVariant;
}) {
  const base =
    "inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-all duration-150 ease-out disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]";
  const styles: Record<NBBtnVariant, string> = {
    primary:
      "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)] hover:shadow-[0_6px_20px_-4px_var(--nv-accent-600)]",
    secondary: "bg-ink-800 text-slate-200 hover:bg-ink-700",
    danger:
      "bg-bad-400/15 text-bad-400 hover:bg-bad-400/25 hover:shadow-[0_4px_16px_-6px_var(--nv-bad-400)]",
  };
  return (
    <button className={`${base} ${styles[variant]} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function NBBadge({
  tone,
  size = "md",
  children,
}: {
  tone: "ok" | "bad" | "warn" | "info" | "muted";
  size?: "sm" | "md";
  children: ReactNode;
}) {
  const styles = {
    ok: "bg-ok-400/15 text-ok-400 ring-1 ring-ok-400/25",
    bad: "bg-bad-400/15 text-bad-400 ring-1 ring-bad-400/25",
    warn: "bg-warn-400/15 text-warn-400 ring-1 ring-warn-400/25",
    info: "bg-accent-500/15 text-accent-600 ring-1 ring-accent-500/25",
    muted: "bg-ink-800 text-slate-400 ring-1 ring-slate-200/15",
  } as const;
  const sizes = {
    sm: "px-2 py-0.5 text-[10px]",
    md: "px-2.5 py-1 text-[11px]",
  } as const;
  return (
    <span
      className={`inline-flex items-center rounded-full font-bold uppercase tracking-wide ${sizes[size]} ${styles[tone]}`}
    >
      {children}
    </span>
  );
}

export function NBField({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold text-slate-200">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-slate-400">{hint}</span>}
    </label>
  );
}

const nbInputCls =
  "w-full rounded-xl bg-ink-800 px-3.5 py-2.5 text-[15px] text-slate-100 placeholder:text-slate-400 shadow-sm outline-none transition-all duration-150 ease-out focus:ring-2 focus:ring-accent-500/30";

export function NBInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${nbInputCls} ${props.className ?? ""}`} />;
}

export function NBSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${nbInputCls} ${props.className ?? ""}`} />;
}

export function NBTextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${nbInputCls} ${props.className ?? ""}`} />;
}

/* Wadah tabel: panel modern + header jelas. */
export function NBTableWrap({ children }: { children: ReactNode }) {
  return (
    <div className="nv-panel-modern overflow-x-auto">
      {children}
    </div>
  );
}

export function NBTh({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <th
      scope="col"
      className={`border-b border-ink-800 bg-ink-800/40 px-4 py-3 text-left text-[11px] font-bold uppercase tracking-[0.08em] text-slate-400 ${className}`}
    >
      {children}
    </th>
  );
}

/* Sel tabel standar: padding konsisten + border baris halus. */
export function NBTd({
  children,
  className = "",
  ...rest
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={`border-b border-ink-800 px-4 py-3 text-sm text-slate-200 ${className ?? ""}`} {...rest}>
      {children}
    </td>
  );
}

/* Baris tabel dengan hover halus (bungkus <tr>). */
export function NBTr({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <tr className={`transition-colors duration-150 hover:bg-ink-800/50 ${className}`}>
      {children}
    </tr>
  );
}

/* Baris kartu daftar (mobile accordion / desktop row). */
export function NBRowCard({ children }: { children: ReactNode }) {
  return (
    <div className="nv-panel-modern px-4 py-3 transition-colors duration-150">
      {children}
    </div>
  );
}

export function NBAccordion({
  summary,
  children,
  defaultOpen = false,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="nv-panel-modern overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex min-h-[44px] w-full cursor-pointer items-center justify-between gap-3 p-4 text-left transition-colors duration-150 hover:bg-ink-800/40"
      >
        <span className="min-w-0 flex-1">{summary}</span>
        <svg
          width="16"
          height="16"
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
      {open && <div className="border-t border-ink-800 p-4">{children}</div>}
    </div>
  );
}

/* Modal konfirmasi: tombol Batal netral + aksi danger. */
export function NBConfirmModal({
  title,
  message,
  onCancel,
  onConfirm,
  confirmLabel = "Hapus",
}: {
  title: string;
  message: string;
  onCancel: () => void;
  onConfirm: () => void;
  confirmLabel?: string;
}) {
  const titleId = useId();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div
      /* Backdrop blur disamakan di semua popup (FocusModal, Modal ui.tsx,
         Modal _nb.tsx): backdrop-blur-md. */
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 backdrop-blur-md p-0 sm:items-center sm:p-6"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <div
        className="nv-pop nv-panel-modern w-full max-w-lg overflow-y-auto rounded-2xl! pb-[calc(1.25rem+env(safe-area-inset-bottom))]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-800 px-5 py-4">
          <h2 id={titleId} className="text-xl font-extrabold tracking-tight text-slate-100">{title}</h2>
          <button
            onClick={onCancel}
            aria-label="Tutup"
            className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl text-slate-400 transition-colors hover:bg-ink-800 hover:text-slate-200"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="px-5 py-5">
          <p className="text-[15px] leading-relaxed text-slate-300">{message}</p>
          <div className="mt-6 grid gap-2.5 sm:flex sm:justify-end">
            <NBButton variant="secondary" onClick={onCancel} className="w-full sm:w-auto">
              Batal
            </NBButton>
            <NBButton variant="danger" onClick={onConfirm} className="w-full sm:w-auto">
              {confirmLabel}
            </NBButton>
          </div>
        </div>
      </div>
    </div>
  );
}

/* Empty state modern: ikon + teks, di dalam panel modern. */
export function NBEmptyState({ text, icon }: { text: string; icon?: ReactNode }) {
  return (
    <div className="nv-panel-modern px-4 py-14 text-center">
      {icon ? (
        <span className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-ink-800/70 ring-1 ring-slate-200/10">
          {icon}
        </span>
      ) : (
        <svg
          width="40"
          height="40"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden
          className="mx-auto mb-3 text-slate-400"
        >
          <path
            d="M20 7H4a2 2 0 00-2 2v10a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2zM16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
      <p className="text-[15px] font-medium text-slate-300">{text}</p>
    </div>
  );
}

/* Kartu statistik modern. */
export function NBStat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="nv-panel-modern p-5">
      <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-400">
        {label}
      </p>
      <p className="tnum mt-2 text-[32px] font-extrabold leading-none tracking-tight text-slate-100">
        {value}
      </p>
      {sub && <p className="mt-2 text-xs text-slate-400">{sub}</p>}
    </div>
  );
}
