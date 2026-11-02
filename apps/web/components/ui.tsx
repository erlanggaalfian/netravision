"use client";

import { useState, type ReactNode } from "react";

/* Komponen UI bersama — dark-first, bahasa vibekoding. */

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-ink-700/60 bg-ink-900 p-4 shadow-sm sm:p-5 ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({
  title,
  desc,
  action,
}: {
  title: string;
  desc?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-white sm:text-2xl">
          {title}
        </h1>
        {desc && <p className="mt-1 text-sm text-slate-400">{desc}</p>}
      </div>
      {action}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold text-white">{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-400">{sub}</p>}
    </Card>
  );
}

type BtnVariant = "primary" | "ghost" | "danger" | "subtle";

export function Button({
  children,
  variant = "primary",
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: BtnVariant;
}) {
  const base =
    "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const styles: Record<BtnVariant, string> = {
    primary: "bg-accent-600 text-white hover:bg-accent-500",
    ghost:
      "border border-ink-700 bg-transparent text-slate-200 hover:border-accent-500 hover:text-white",
    danger: "bg-red-600/15 text-bad-400 hover:bg-red-600/25 border border-red-500/30",
    subtle: "bg-ink-800 text-slate-200 hover:bg-ink-700",
  };
  return (
    <button className={`${base} ${styles[variant]} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function Field({
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
      <span className="mb-1 block text-sm font-medium text-slate-300">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

const inputCls =
  "w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2.5 text-slate-100 placeholder:text-slate-600 outline-none transition-colors focus:border-accent-500";

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputCls} ${props.className ?? ""}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${inputCls} ${props.className ?? ""}`} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea {...props} className={`${inputCls} ${props.className ?? ""}`} />
  );
}

export function Badge({
  tone,
  children,
}: {
  tone: "ok" | "bad" | "warn" | "info" | "muted";
  children: ReactNode;
}) {
  const styles = {
    ok: "bg-emerald-500/15 text-ok-400 border-emerald-500/30",
    bad: "bg-red-500/15 text-bad-400 border-red-500/30",
    warn: "bg-amber-500/15 text-warn-400 border-amber-500/30",
    info: "bg-accent-500/15 text-accent-300 border-accent-500/30",
    muted: "bg-ink-800 text-slate-400 border-ink-700",
  } as const;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${styles[tone]}`}
    >
      {children}
    </span>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-0 sm:items-center sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`max-h-[92vh] w-full overflow-y-auto rounded-t-2xl border border-ink-700 bg-ink-900 p-5 sm:rounded-2xl ${
          wide ? "sm:max-w-2xl" : "sm:max-w-lg"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Tutup"
            className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 hover:bg-ink-800 hover:text-white"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmModal({
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
    <Modal title={title} onClose={onCancel}>
      <p className="text-sm text-slate-300">{message}</p>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          Batal
        </Button>
        <Button variant="danger" onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

/* Accordion collapsed-first untuk daftar panjang di mobile. */
export function Accordion({
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
    <div className="rounded-xl border border-ink-700/60 bg-ink-900">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 p-4 text-left"
      >
        <span className="min-w-0 flex-1">{summary}</span>
        <span
          className={`shrink-0 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        >
          ⌄
        </span>
      </button>
      {open && <div className="border-t border-ink-700/60 p-4">{children}</div>}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-bad-400">
      {message}
    </div>
  );
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-ink-700 bg-ink-900/50 px-4 py-10 text-center text-sm text-slate-500">
      {text}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-10" aria-label="Memuat">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-ink-700 border-t-accent-400" />
    </div>
  );
}

export function fmtBytes(n: number): string {
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${u[i]}`;
}
