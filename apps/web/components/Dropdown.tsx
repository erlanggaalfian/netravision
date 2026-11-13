"use client";

/* Dropdown custom BERSAMA (pengganti <select> native di semua halaman).
   Dibuat dari dropdown filter grup Live (app/live/page.tsx): pemicu pill /
   field, panel bertema, opsi terpilih gradient accent SOLID + teks putih
   + lencana bg-black/20 + centang, hover bg-ink-800, keyboard + ARIA
   listbox, buka ke atas bila ruang bawah kurang, opsi min 44px.

   Panel dirender lewat portal ke document.body dengan position: fixed
   (bukan absolute di dalam wadah): form tambah/edit kamera admin dirender
   di Modal (components/ui.tsx) yang punya overflow-y-auto + max-h-[92dvh],
   jadi panel absolute di dalam modal AKAN terpotong. Dengan portal +
   fixed, panel selalu tampil penuh di atas modal (z-70, modal z-50),
   posisinya dihitung dari getBoundingClientRect() pemicu saat dibuka
   dan dihitung ulang saat scroll/resize selama panel terbuka.

   Token warna memakai class yang sama persis dengan dropdown Live
   (bg-ink-900, bg-ink-800, from-accent-600 to-accent-500, text-onaccent,
   bg-ink-500/25 text-neutral-300), jadi enak di KEDUA tema: token
   bertukar nilai di globals.css (terang ink-900 #ffffff, ink-800
   #e2e8f0, accent #0097fc/#0284c7; gelap ink-900 #0d141c, ink-800
   #16202c, accent #3b82f6/#2563eb). */

import { createPortal } from "react-dom";
import {
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

export type DropdownOption = {
  value: string;
  label: string;
  badge?: string | number;
  disabled?: boolean;
};

export type DropdownVariant = "pill" | "field";

/* Konversi children <option> (dipakai adapter NBSelect / Select supaya
   API lama <select> tetap jalan) jadi data opsi. Menangani kondisional
   yang false/null, fragment, dan children teks bersarang. */
function optionText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(optionText).join("");
  if (isValidElement(node))
    return optionText((node.props as { children?: ReactNode }).children);
  return "";
}

export function selectChildrenToOptions(children: ReactNode): DropdownOption[] {
  const out: DropdownOption[] = [];
  const walk = (node: ReactNode): void => {
    if (node == null || typeof node === "boolean") return;
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (!isValidElement(node)) return;
    const props = node.props as {
      value?: unknown;
      children?: ReactNode;
      disabled?: boolean;
    };
    /* Fragment: telusuri isinya, bukan dianggap opsi. */
    if (typeof node.type === "symbol") {
      walk(props.children);
      return;
    }
    if (node.type !== "option") return;
    out.push({
      value: props.value == null ? "" : String(props.value),
      label: optionText(props.children),
      disabled: Boolean(props.disabled),
    });
  };
  walk(children);
  return out;
}

type PanelRect = {
  left: number;
  top: number;
  width: number;
  maxHeight: number;
};

export function Dropdown({
  options,
  value,
  onChange,
  ariaLabel,
  placeholder = "Pilih",
  variant = "field",
  className = "",
  disabled = false,
  id,
}: {
  options: DropdownOption[];
  value: string;
  onChange: (v: string) => void;
  ariaLabel?: string;
  placeholder?: string;
  variant?: DropdownVariant;
  className?: string;
  disabled?: boolean;
  id?: string;
}) {
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [rect, setRect] = useState<PanelRect | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const selected = options.find((o) => o.value === value);
  const selectedLabel =
    selected?.label ?? (value ? value : placeholder);
  const selectedBadge = selected?.badge;
  /* Varian pill (Live): opsi pertama ("Semua") netral, sisanya gradient.
     Varian field selalu netral seperti NBSelect / input. */
  const pillSelected = variant === "pill" && options.length > 0 && value !== options[0].value;

  const measure = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const isDesktop = window.innerWidth >= 640;
    const panelWidth =
      variant === "pill" && isDesktop ? 260 : r.width;
    const left =
      variant === "pill" && isDesktop
        ? Math.max(8, Math.min(r.right - panelWidth, window.innerWidth - panelWidth - 8))
        : Math.max(8, Math.min(r.left, window.innerWidth - panelWidth - 8));
    const estH = Math.min(Math.max(options.length, 1), 7) * 48 + 12;
    const below = window.innerHeight - r.bottom - 8;
    const above = r.top - 8;
    const openUp = below < estH && above > below;
    const maxHeight = Math.max(96, Math.min(320, openUp ? above : below));
    const panelH = Math.min(estH, maxHeight);
    setRect({
      left,
      top: openUp ? Math.max(8, r.top - panelH - 8) : r.bottom + 8,
      width: panelWidth,
      maxHeight,
    });
  }, [options.length, variant]);

  const close = useCallback((refocus = false) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }, []);

  const openMenu = useCallback(() => {
    if (disabled) return;
    const idx = Math.max(0, options.findIndex((o) => o.value === value));
    setActive(idx);
    measure();
    setOpen(true);
    requestAnimationFrame(() => optionRefs.current[idx]?.focus());
  }, [disabled, options, value, measure]);

  const select = useCallback(
    (v: string) => {
      onChange(v);
      close(true);
    },
    [onChange, close],
  );

  /* Selama panel terbuka: hitung ulang posisi saat scroll (termasuk
     scroll di dalam modal, via capture) / resize, dan Escape menutup. */
  useEffect(() => {
    if (!open) return;
    measure();
    const onScroll = () => measure();
    const onResize = () => measure();
    /* Escape ditangkap di fase capture: Modal di bawah dropdown
       (components/ui.tsx, _nb.tsx) juga menutup lewat Escape di window;
       tanpa capture + stopPropagation, Escape saat dropdown terbuka
       akan menutup modal beserta formnya, bukan cuma dropdown. */
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close(true);
      }
    };
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [open, measure, close]);

  const onTriggerKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (
      e.key === "ArrowDown" ||
      e.key === "ArrowUp" ||
      e.key === "Enter" ||
      e.key === " "
    ) {
      e.preventDefault();
      openMenu();
    }
  };

  const onPanelKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = options.length;
    if (n === 0) return;
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = (active + 1) % n;
      setActive(next);
      optionRefs.current[next]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = (active - 1 + n) % n;
      setActive(prev);
      optionRefs.current[prev]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
      optionRefs.current[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(n - 1);
      optionRefs.current[n - 1]?.focus();
    } else if (e.key === "Tab") {
      close(false);
    }
  };

  const triggerCls =
    variant === "pill"
      ? `flex h-11 w-full items-center justify-between gap-2 rounded-full pl-4 pr-3 text-sm font-semibold shadow-sm outline-none transition-all duration-200 focus:ring-2 focus:ring-accent-500/30 active:scale-[0.98] sm:w-auto sm:min-w-[190px] sm:max-w-[260px] ${
          pillSelected
            ? "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent shadow-[0_4px_16px_-4px_var(--nv-accent-600)]"
            : "bg-ink-800 text-slate-100"
        }`
      : "flex min-h-[44px] w-full items-center justify-between gap-2 rounded-xl bg-ink-800 px-3.5 py-2.5 text-[15px] text-slate-100 shadow-sm outline-none transition-all duration-150 focus:ring-2 focus:ring-accent-500/30";

  return (
    <>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        disabled={disabled}
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={onTriggerKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel ?? selectedLabel}
        className={`${triggerCls} ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"} ${className}`}
      >
        <span className="min-w-0 truncate">
          {selectedLabel}
          {variant === "pill" && selectedBadge != null ? ` · ${selectedBadge}` : ""}
        </span>
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
          className={`shrink-0 transition-transform duration-200 ${open ? "rotate-180" : ""} ${
            pillSelected ? "text-onaccent" : "text-neutral-400"
          }`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open &&
        rect &&
        createPortal(
          <>
            {/* Lapisan penutup: klik di luar menutup menu (bukan modal
                di bawahnya). z-60 di atas modal z-50. */}
            <div
              className="fixed inset-0 z-[60] cursor-default"
              onClick={() => close()}
              aria-hidden
            />
            <div
              id={listboxId}
              role="listbox"
              aria-label={ariaLabel ?? "Pilih opsi"}
              onKeyDown={onPanelKeyDown}
              style={{
                left: rect.left,
                top: rect.top,
                width: rect.width,
                maxHeight: rect.maxHeight,
              }}
              className="fixed z-[70] overflow-y-auto rounded-2xl bg-ink-900 p-1.5 shadow-[0_16px_40px_-8px_rgba(0,0,0,0.55)] ring-1 ring-ink-600/20"
            >
              {options.length === 0 ? (
                <p className="px-3.5 py-3 text-sm text-slate-400">
                  Tidak ada opsi
                </p>
              ) : (
                options.map((o, i) => {
                  const isSelected = o.value === value;
                  const isActive = i === active;
                  return (
                    <button
                      key={o.value}
                      ref={(el) => {
                        optionRefs.current[i] = el;
                      }}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      disabled={o.disabled}
                      onClick={() => select(o.value)}
                      onMouseEnter={() => setActive(i)}
                      className={`flex min-h-[44px] w-full items-center justify-between gap-2 rounded-xl px-3.5 text-sm font-semibold transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/40 ${
                        o.disabled
                          ? "cursor-not-allowed opacity-50"
                          : isSelected
                            ? "bg-gradient-to-r from-accent-600 to-accent-500 text-onaccent"
                            : isActive
                              ? "bg-ink-800 text-slate-100"
                              : "text-slate-200 hover:bg-ink-800"
                      }`}
                    >
                      <span className="min-w-0 truncate text-left">{o.label}</span>
                      <span className="flex shrink-0 items-center gap-1.5">
                        {o.badge != null && (
                          <span
                            className={`rounded-full px-1.5 py-0.5 text-xs font-bold leading-none ${
                              isSelected
                                ? "bg-black/20 text-onaccent"
                                : "bg-ink-500/25 text-neutral-300"
                            }`}
                          >
                            {o.badge}
                          </span>
                        )}
                        {isSelected && (
                          <svg
                            width="15"
                            height="15"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="3"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden
                            className="text-onaccent"
                          >
                            <path d="M20 6L9 17l-5-5" />
                          </svg>
                        )}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </>,
          document.body,
        )}
    </>
  );
}
