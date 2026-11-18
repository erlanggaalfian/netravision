/* Token media per-stream (K-1): live stream tanpa auth.
   URL WHEP/HLS publik tidak lagi bisa dibuka tanpa kredensial: proxy API
   (/api/media/whep/* dan /api/media/hls/*) menolak request tanpa token
   media (?token=) atau token sesi embed (?session=).
   Helper ini meminta token media singkat (60 menit, terikat satu kamera)
   ke POST /api/media/token lalu mengembalikan URL WHEP/HLS yang sudah
   membawa token. Token di-cache per kamera sampai 60 detik sebelum
   kedaluwarsa, supaya tile yang retry tiap 10 detik tidak menembak
   endpoint token terus menerus. Halaman embed TIDAK memakai helper ini:
   URL WHEP embed sudah membawa ?session= dari /external/stream.
   RISIKO YANG DITERIMA (F6.5): token tampil di URL (?token=), jadi
   terlihat di tab Network DevTools dan bisa disalin dari sana selama
   60 menit. Ini disengaja, bukan kebocoran: <video> dan sinyal WHEP
   tidak bisa mengirim header Authorization, jadi token di URL adalah
   satu-satunya cara membawa kredensial. Token TIDAK masuk histori
   browser (URL tidak pernah dimasukkan ke address bar) dan log akses
   Apache menutupi query string untuk path media (format noquery).
   JANGAN tambahkan fitur "salin URL stream" tanpa tinjauan keamanan,
   karena URL itu mengandung token yang masih berlaku. */

import { api } from "./api";

export interface MediaTokenResponse {
  token: string;
  expires_at: string;
  path: string;
  whep_url: string;
  hls_url: string;
}

export interface MediaUrls {
  whepUrl: string;
  hlsUrl: string;
}

interface CacheEntry {
  urls: MediaUrls;
  expiresAt: number;
}

const cache = new Map<string, CacheEntry>();
/* F3.9: promise yang sedang berjalan per kunci, supaya dua pemanggil
   bersamaan untuk kamera yang sama memakai satu request token saja
   (backend membatasi endpoint ini 60 request per 60 detik). */
const inflight = new Map<string, Promise<MediaUrls>>();

export async function getMediaUrls(
  streamId: number,
  sub: boolean,
): Promise<MediaUrls> {
  const key = `${streamId}:${sub ? "sub" : "main"}`;
  /* P0 code-review 2026-11-18: hapus entri kedaluwarsa saat dibaca,
     supaya cache tidak menumpuk sejumlah kamera x 2 selama tab hidup. */
  pruneExpiredMediaTokens();
  const hit = cache.get(key);
  if (hit && hit.expiresAt - Date.now() > 60_000) return hit.urls;
  const running = inflight.get(key);
  if (running) return running;
  const p = (async (): Promise<MediaUrls> => {
    const data = await api.post<MediaTokenResponse>("/media/token", {
      stream_id: streamId,
      sub,
    });
    const urls: MediaUrls = { whepUrl: data.whep_url, hlsUrl: data.hls_url };
    cache.set(key, {
      urls,
      expiresAt: new Date(data.expires_at).getTime(),
    });
    return urls;
  })();
  inflight.set(key, p);
  try {
    return await p;
  } finally {
    if (inflight.get(key) === p) inflight.delete(key);
  }
}

function pruneExpiredMediaTokens(): void {
  const now = Date.now();
  for (const [key, entry] of cache) {
    if (entry.expiresAt - now <= 60_000) cache.delete(key);
  }
}

/* F2.12: true bila tidak ada entri cache untuk kunci ini, atau entri
   sudah kedaluwarsa (ambang yang sama dengan getMediaUrls: 60 detik
   sebelum kedaluwarsa). Dipakai tile saat kembali terlihat, supaya
   tidak memutar ulang dengan token basi. */
export function isMediaTokenExpired(streamId: number, sub: boolean): boolean {
  const key = `${streamId}:${sub ? "sub" : "main"}`;
  const hit = cache.get(key);
  if (!hit) return true;
  return hit.expiresAt - Date.now() <= 60_000;
}

/* F3.3: minta URL baru dengan cache dihapus dulu, dipakai pemanggil
   saat token ditolak server (WHEP 401/403 atau HLS 401): token lama
   yang dicabut tidak dipakai ulang sampai kedaluwarsa. */
export async function refreshMediaUrls(
  streamId: number,
  sub: boolean,
): Promise<MediaUrls> {
  clearMediaTokenCache(streamId);
  return getMediaUrls(streamId, sub);
}

/* Hapus token cache satu kamera (mis. kamera berganti) atau semuanya. */
export function clearMediaTokenCache(streamId?: number): void {
  if (streamId === undefined) {
    cache.clear();
    inflight.clear();
    return;
  }
  cache.delete(`${streamId}:main`);
  cache.delete(`${streamId}:sub`);
  inflight.delete(`${streamId}:main`);
  inflight.delete(`${streamId}:sub`);
}
