/* Token media per-stream (K-1): live stream tanpa auth.
   URL WHEP/HLS publik tidak lagi bisa dibuka tanpa kredensial: proxy API
   (/api/media/whep/* dan /api/media/hls/*) menolak request tanpa token
   media (?token=) atau token sesi embed (?session=).
   Helper ini meminta token media singkat (60 menit, terikat satu kamera)
   ke POST /api/media/token lalu mengembalikan URL WHEP/HLS yang sudah
   membawa token. Token di-cache per kamera sampai 60 detik sebelum
   kedaluwarsa, supaya tile yang retry tiap 10 detik tidak menembak
   endpoint token terus menerus. Halaman embed TIDAK memakai helper ini:
   URL WHEP embed sudah membawa ?session= dari /external/stream. */

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

export async function getMediaUrls(
  streamId: number,
  sub: boolean,
): Promise<MediaUrls> {
  const key = `${streamId}:${sub ? "sub" : "main"}`;
  const hit = cache.get(key);
  if (hit && hit.expiresAt - Date.now() > 60_000) return hit.urls;
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
}

/* Hapus token cache satu kamera (mis. kamera berganti) atau semuanya. */
export function clearMediaTokenCache(streamId?: number): void {
  if (streamId === undefined) {
    cache.clear();
    return;
  }
  cache.delete(`${streamId}:main`);
  cache.delete(`${streamId}:sub`);
}
