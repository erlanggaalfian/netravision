import { Spinner } from "../../components/ui";

/* P0 code-review 2026-11-18: skeleton bawaan framework saat navigasi
   ke /live, supaya tidak ada jeda kosong tanpa umpan balik. */
export default function Loading() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-ink-950">
      <Spinner />
    </div>
  );
}
