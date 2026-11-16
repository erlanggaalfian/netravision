import type { Stream, User } from "./types";

/* Cakupan kamera untuk admin biasa, paritas aturan backend
   (rbac._visible_streams dan mask_rtsp_url): admin hanya boleh melihat
   kamera yang ia pasang sendiri (created_by/owner_id) atau yang di-grant
   can_view oleh superadmin. Backend /admin/streams mengosongkan rtsp_url
   bila admin tidak berhak melihat kredensial RTSP, jadi rtsp_url yang
   terisi adalah sinyal cakupan itu; grant can_view milik sendiri dipakai
   sebagai sinyal kedua. Super admin melihat semua, jadi fungsi ini
   mengembalikan null = tanpa filter. Dipakai halaman Admin Kamera,
   Admin Grup Kamera, dan Dasbor supaya tidak ada kamera atau grup
   kamera milik grup lain yang tampil ke admin, walau endpoint daftar
   backend belum membatasi per grup. */

export function adminVisibleStreamIds(
  me: User | null | undefined,
  streams: Stream[],
  viewGrantIds?: Set<number>,
): Set<number> | null {
  if (!me || me.role === "super_admin") return null;
  const ids = new Set<number>();
  for (const s of streams) {
    if ((s.rtsp_url ?? "") !== "") ids.add(s.id);
  }
  if (viewGrantIds) {
    for (const id of viewGrantIds) ids.add(id);
  }
  return ids;
}

export function filterStreamsForRole(
  me: User | null | undefined,
  streams: Stream[],
  viewGrantIds?: Set<number>,
): Stream[] {
  const ids = adminVisibleStreamIds(me, streams, viewGrantIds);
  if (ids === null) return streams;
  return streams.filter((s) => ids.has(s.id));
}
