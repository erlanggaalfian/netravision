import { api } from "./api";
import type { Stream, User } from "./types";

/* Cakupan kamera untuk admin biasa, paritas aturan backend
   (rbac._visible_streams dan mask_rtsp_url): admin hanya boleh melihat
   kamera yang ia pasang sendiri (created_by/owner_id) atau yang di-grant
   can_view oleh superadmin.
   KONTRAK MASKING (F3.14, didokumentasikan eksplisit karena rapuh):
   backend /admin/streams mengosongkan rtsp_url bila admin tidak berhak
   melihat kredensial RTSP, jadi rtsp_url yang terisi dipakai sebagai
   sinyal cakupan di fungsi ini. Bila backend mengubah perilaku masking
   itu (mis. selalu mengisi rtsp_url, atau mengosongkannya untuk semua
   admin), filter tampilan di sini ikut salah: admin bisa melihat kamera
   grup lain di UI. Ini HANYA soal tampilan, bukan kebocoran akses data,
   karena backend tetap menegakkan otorisasi akhir di tiap endpoint.
   SINYAL UTAMA YANG EKSPLISIT: endpoint GET
   /admin/admins/{id-pengguna}/camera-grants mengembalikan daftar id
   kamera dengan can_view (admin boleh membaca grant dirinya sendiri,
   lihat A-S7 di routers/admin_users.py). Pemanggil yang sudah memakai
   sinyal itu (mis. halaman Admin Kamera) mengoper daftar id-nya lewat
   parameter viewGrantIds di bawah; helper fetchOwnViewGrantIds di
   bawah mengambil daftar itu untuk pemanggil lain yang membutuhkannya.
   Bila endpoint grants gagal dimuat, pemanggil tetap memakai sinyal
   masking rtsp_url sebagai cadangan, bukan menampilkan semua kamera. */

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

/* F3.14: ambil daftar id kamera yang di-grant can_view untuk pengguna
   itu sendiri dari endpoint grants backend, sebagai sinyal eksplisit
   utama cakupan admin (pengganti ketergantungan pada masking rtsp_url).
   Mengembalikan Set kosong bila endpoint gagal (mis. jaringan), supaya
   pemanggil jatuh kembali ke sinyal masking, bukan menampilkan semua. */
export async function fetchOwnViewGrantIds(
  me: User | null | undefined,
): Promise<Set<number>> {
  const empty = new Set<number>();
  if (!me || me.role === "super_admin") return empty;
  try {
    const d = await api.get<{
      stream_ids?: number[];
      grants?: { stream_id: number; can_view: boolean }[];
    }>(`/admin/admins/${me.id}/camera-grants`);
    if (Array.isArray(d.stream_ids)) return new Set(d.stream_ids);
    if (Array.isArray(d.grants)) {
      return new Set(
        d.grants.filter((g) => g.can_view).map((g) => g.stream_id),
      );
    }
    return empty;
  } catch {
    return empty;
  }
}
