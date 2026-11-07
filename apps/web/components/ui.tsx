"use client";

import { useState, type ReactNode } from "react";

/* Komponen UI bersama — "ruang kendali siaran": permukaan bertingkat,
   hairline white/8, radius 12–16px, satu aksen biru. API tidak berubah. */

function XIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
    >
      <path
        d="M4 4l8 8M12 4l-8 8"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ChevronIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
    >
      <path
        d="M4 6l4 4 4-4"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl bg-ink-900 p-5 shadow-[0_2px_8px_-2px_rgba(0,0,0,0.1),0_8px_24px_-8px_rgba(0,0,0,0.12)] ${className}`}
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
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-[28px] font-extrabold tracking-tight text-slate-100">
          {title}
        </h1>
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
    <Card className="p-5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">
        {label}
      </p>
      <p className="tnum mt-2 text-[32px] font-extrabold leading-none tracking-tight text-slate-100">
        {value}
      </p>
      {sub && <p className="mt-2 text-xs text-slate-400">{sub}</p>}
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
    "inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-all duration-150 ease-out disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]";
  const styles: Record<BtnVariant, string> = {
    primary:
      "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)] hover:shadow-[0_6px_20px_-4px_var(--nv-accent-600)]",
    ghost: "bg-transparent text-slate-200 hover:bg-ink-800",
    danger:
      "bg-bad-400/15 text-bad-400 hover:bg-bad-400/25 hover:shadow-[0_4px_16px_-6px_var(--nv-bad-400)]",
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
      <span className="mb-1.5 block text-sm font-medium text-slate-300">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-slate-400">{hint}</span>}
    </label>
  );
}

const inputCls =
  "w-full rounded-xl bg-ink-800 px-4 py-2.5 text-[15px] text-slate-100 placeholder:text-slate-400 shadow-sm outline-none transition-all duration-150 ease-out focus:ring-2 focus:ring-accent-500/30";

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

/* Toggle switch bersama (dipindah dari app/admin/ads/page.tsx).
   Warna track memakai token ok-400 agar adaptif di kedua tema. */
export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      /* Perluas area sentuh ke ~48px tanpa mengubah visual track 24px. */
      className={`relative h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors duration-150 after:absolute after:-inset-3 after:rounded-full after:content-[''] ${
        checked ? "bg-ok-400" : "bg-ink-600"
      }`}
    >
      <span
        className={`absolute left-[2px] top-[2px] h-5 w-5 rounded-full bg-onaccent shadow transition-transform duration-150 ${
          checked ? "translate-x-5" : "translate-x-0"
        }`}
      />
    </button>
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
    ok: "bg-ok-400/12 text-ok-300",
    bad: "bg-bad-400/12 text-bad-300",
    warn: "bg-warn-400/12 text-warn-300",
    info: "bg-accent-500/12 text-accent-300",
    muted: "bg-ink-800 text-slate-400",
  } as const;
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold tracking-wide ${styles[tone]}`}
    >
      {children}
    </span>
  );
}

/* Segmented control bersama — gantikan 6 varian tab/pill custom di
   halaman (live, playback, monitors, streams, access). Memakai radiogroup
   yang benar untuk aksesibilitas keyboard. */
export function SegmentedControl<T extends string | number>({
  options,
  value,
  onChange,
  ariaLabel,
  size = "md",
}: {
  options: { value: T; label: ReactNode; title?: string }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel?: string;
  size?: "sm" | "md";
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="inline-flex items-center gap-1 rounded-full bg-ink-800 p-1 shadow-sm"
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={active}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={`inline-flex cursor-pointer items-center justify-center rounded-full px-4 text-sm font-semibold transition-all duration-150 active:scale-[0.97] ${
              size === "sm" ? "min-h-[36px]" : "min-h-[44px]"
            } ${
              active
                ? "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
                : "text-slate-400 hover:bg-ink-700 hover:text-slate-200"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
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
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 sm:items-center sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`nv-pop max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl bg-ink-900 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:rounded-2xl ${
          wide ? "sm:max-w-2xl" : "sm:max-w-lg"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-800 px-5 py-4 sm:px-6">
          <h2 className="text-lg font-bold tracking-tight text-white">
            {title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Tutup"
            className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl text-slate-400 transition-colors duration-150 hover:bg-ink-700 hover:text-slate-200"
          >
            <XIcon />
          </button>
        </div>
        <div className="px-5 py-5 sm:px-6 sm:py-6">
          {children}
        </div>
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
      <p className="text-[15px] leading-relaxed text-slate-300">{message}</p>
      <div className="mt-6 grid gap-2.5 sm:flex sm:justify-end">
        <Button variant="ghost" onClick={onCancel} className="min-h-[48px] w-full sm:w-auto">
          Batal
        </Button>
        <Button variant="danger" onClick={onConfirm} className="min-h-[48px] w-full sm:w-auto">
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
    <div className="rounded-2xl bg-ink-900 shadow-sm">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex min-h-[44px] w-full cursor-pointer items-center justify-between gap-3 p-4 text-left transition-colors duration-150 hover:bg-ink-800"
      >
        <span className="min-w-0 flex-1">{summary}</span>
        <ChevronIcon
          className={`shrink-0 text-slate-400 transition-transform duration-200 ease-out ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="border-t border-ink-800 p-4">{children}</div>
      )}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-xl bg-bad-400/10 px-3.5 py-2.5 text-sm text-bad-400">
      {message}
    </div>
  );
}

export function EmptyState({
  text,
  icon,
  action,
}: {
  text: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-ink-700 bg-ink-900/50 px-4 py-12 text-center text-sm text-slate-400">
      {icon && <div className="mb-3 flex justify-center">{icon}</div>}
      <p>{text}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
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

/* Ikon grid mini: kotak-kotak sesuai jumlah kolom (1×1, 2×2, 3×3, 4×4).
   Dipakai tombol pemilih grid di Live dan Putar Ulang (PC). */
export function GridIcon({ cols, size = 16 }: { cols: number; size?: number }) {
  return (
    <span
      className="grid shrink-0"
      style={{
        gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
        gap: cols === 1 ? 0 : 1.5,
        width: size,
        height: size,
      }}
      aria-hidden
    >
      {Array.from({ length: cols * cols }).map((_, i) => (
        <span key={i} className="rounded-[1px] bg-currentColor" />
      ))}
    </span>
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
