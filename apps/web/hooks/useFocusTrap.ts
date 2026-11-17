import { useEffect, type RefObject } from "react";

/* Focus trap bersama (F4.2): fokus awal ke tombol tutup bila ada,
   Tab berputar di dalam dialog, fokus dikembalikan ke pemicu saat
   dialog ditutup. Dipakai Modal (ui.tsx), NBConfirmModal (_nb.tsx),
   dan FocusModal. */
const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(
  ref: RefObject<HTMLElement | null>,
  active = true,
) {
  useEffect(() => {
    if (!active) return;
    const dialog = ref.current;
    if (!dialog) return;
    const prev = document.activeElement as HTMLElement | null;
    const focusables = () =>
      Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.getClientRects().length > 0,
      );
    const closeBtn = dialog.querySelector<HTMLElement>("[data-focus-close]");
    (closeBtn ?? focusables()[0])?.focus({ preventScroll: true });
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const els = focusables();
      if (els.length === 0) return;
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener("keydown", onKeyDown);
    return () => {
      dialog.removeEventListener("keydown", onKeyDown);
      prev?.focus?.({ preventScroll: true });
    };
  }, [ref, active]);
}
