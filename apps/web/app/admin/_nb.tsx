"use client";

/* Primitif UI bahasa desain NetBackup — KHUSUS halaman admin.
   Kartu putih radius 12px + border jelas + shadow halus, tombol primer
   biru #0097FC radius 8px, badge pill uppercase, judul section 18px.
   Memakai token tema (ink/accent/slate) sehingga mode gelap tetap benar. */

import { useState, type ReactNode } from "react";

export function NBCard({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-ink-700/70 bg-ink-900 p-4 shadow-[0_1px_3px_rgba(15,23,42,0.08)] sm:p-5 ${className}`}
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
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-lg font-bold tracking-tight text-white">{title}</h1>
        {desc && (
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-400">
            {desc}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

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
    "inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-all duration-150 ease-out disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]";
  const styles: Record<NBBtnVariant, string> = {
    primary:
      "bg-accent-500 text-onaccent shadow-[0_1px_2px_rgba(0,151,252,0.35)] hover:bg-accent-600",
    secondary:
      "border border-ink-700 bg-ink-900 text-slate-300 hover:bg-ink-800",
    danger:
      "border border-bad-400/40 bg-bad-400/10 text-bad-400 hover:bg-bad-400/20",
  };
  return (
    <button className={`${base} ${styles[variant]} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function NBBadge({
  tone,
  children,
}: {
  tone: "ok" | "bad" | "warn" | "info" | "muted";
  children: ReactNode;
}) {
  const styles = {
    ok: "bg-ok-400/15 text-ok-400",
    bad: "bg-bad-400/15 text-bad-400",
    warn: "bg-warn-400/15 text-warn-400",
    info: "bg-accent-500/15 text-accent-600",
    muted: "bg-ink-800 text-slate-400",
  } as const;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${styles[tone]}`}
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
      <span className="mb-1.5 block text-sm font-medium text-slate-300">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-slate-400">{hint}</span>}
    </label>
  );
}

const nbInputCls =
  "w-full rounded-lg border border-ink-700 bg-ink-900 px-3.5 py-2.5 text-slate-100 placeholder:text-slate-400 outline-none transition-all duration-150 ease-out focus:border-accent-500 focus:ring-4 focus:ring-accent-500/15";

export function NBInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${nbInputCls} ${props.className ?? ""}`} />;
}

export function NBSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${nbInputCls} ${props.className ?? ""}`} />;
}

export function NBTextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${nbInputCls} ${props.className ?? ""}`} />;
}

/* Wadah tabel putih: border + radius 12 + shadow halus. */
export function NBTableWrap({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-ink-700/70 bg-ink-900 shadow-[0_1px_3px_rgba(15,23,42,0.08)]">
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
    <th scope="col" className={`px-3 py-3 font-semibold ${className}`}>
      {children}
    </th>
  );
}

/* Baris kartu daftar (mobile accordion / desktop row): putih, border jelas. */
export function NBRowCard({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-700/70 bg-ink-900 px-4 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.05)] transition-colors hover:border-ink-500">
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
    <div className="rounded-xl border border-ink-700/70 bg-ink-900 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
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
      {open && <div className="border-t border-ink-700/60 p-4">{children}</div>}
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
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 sm:items-center sm:p-6"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-lg overflow-y-auto rounded-t-xl border border-ink-700/70 bg-ink-900 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-[0_8px_32px_rgba(15,23,42,0.18)] sm:rounded-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-700/60 px-5 py-4">
          <h2 className="text-lg font-bold tracking-tight text-white">{title}</h2>
          <button
            onClick={onCancel}
            aria-label="Tutup"
            className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-ink-800 hover:text-white"
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

/* Empty state kartu garis putus-putus. */
export function NBEmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-ink-700 bg-ink-900/50 px-4 py-12 text-center text-sm text-slate-400">
      <p>{text}</p>
    </div>
  );
}
