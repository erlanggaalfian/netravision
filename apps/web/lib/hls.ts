/* Pemutar HLS (fallback bila WebRTC/WHEP gagal tersambung).
   Dipakai untuk live stream sub dari MediaMTX via Apache /hls/*, yang
   jalan di atas HTTP/TCP sehingga tembus jaringan yang memblokir UDP
   (NAT/CGNAT yang tidak meneruskan UDP 8189 ke server).
   Safari memutar HLS secara native; browser lain memakai hls.js. */

import Hls from "hls.js";

export interface HlsHandle {
  destroy: () => void;
}

/* Putar URL HLS pada elemen video. Kembalikan handle untuk cleanup.
   Melempar bila HLS tidak didukung atau gagal memuat manifest. */
export function playHls(
  video: HTMLVideoElement,
  url: string,
  onFail?: () => void,
): HlsHandle {
  // Safari / iOS: HLS native.
  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = url;
    const onErr = () => onFail?.();
    video.addEventListener("error", onErr, { once: true });
    video
      .play()
      .catch(() => {
        /* Autoplay bersuara ditolak; coba tanpa suara. */
        video.muted = true;
        video.play().catch(() => {});
      });
    return {
      destroy: () => {
        video.removeEventListener("error", onErr);
        try {
          video.pause();
        } catch {
          /* abaikan */
        }
        video.removeAttribute("src");
        video.load();
      },
    };
  }

  if (!Hls.isSupported()) {
    throw new Error("HLS tidak didukung browser ini");
  }

  const hls = new Hls({
    // HLS low-latency MediaMTX: segmen 1 dtk, part 500ms. Jaga buffer
    // tetap kecil supaya jeda dari live tidak membesar.
    maxBufferLength: 10,
    liveSyncDurationCount: 2,
  });
  let destroyed = false;
  hls.on(Hls.Events.ERROR, (_ev, data) => {
    if (destroyed) return;
    if (data.fatal) onFail?.();
  });
  hls.loadSource(url);
  hls.attachMedia(video);
  hls.on(Hls.Events.MANIFEST_PARSED, () => {
    video
      .play()
      .catch(() => {
        video.muted = true;
        video.play().catch(() => {});
      });
  });
  return {
    destroy: () => {
      destroyed = true;
      try {
        hls.destroy();
      } catch {
        /* abaikan */
      }
    },
  };
}

export function stopHls(handle: HlsHandle | null) {
  try {
    handle?.destroy();
  } catch {
    /* abaikan */
  }
}

/* Periksa apakah playlist HLS variant sudah bebas segmen gap.
   Muxer HLS MediaMTX (varian lowLatency) butuh ~10 dtk untuk hangat dari
   dingin; playlist awal berisi segmen `gap.mp4` bertanda #EXT-X-GAP.
   hls.js tetap mencoba memuat gap.mp4 (404) dan gagal fatal, jadi HLS
   tidak boleh dimulai selagi masih ada gap. Kembalikan true bila bebas
   gap, false bila masih ada gap atau gagal mengambil playlist. */
export async function isHlsWarm(masterUrl: string): Promise<boolean> {
  try {
    const masterRes = await fetch(masterUrl);
    if (!masterRes.ok) return false;
    const masterText = await masterRes.text();
    const variantLine = masterText
      .split("\n")
      .find((l) => l.includes(".m3u8") && !l.startsWith("#"));
    if (!variantLine) return false;
    /* masterUrl di sini relatif (/hls/stream_...), sedangkan new URL()
       butuh base absolut; tanpa ini selalu lempar "Invalid URL" dan
       fungsi selalu mengembalikan false (pemeriksaan hangat mati). */
    const base = new URL(masterUrl, window.location.href);
    const variantUrl = new URL(variantLine.trim(), base).toString();
    const variantRes = await fetch(variantUrl);
    if (!variantRes.ok) return false;
    const variantText = await variantRes.text();
    return !variantText.includes("gap.mp4");
  } catch {
    return false;
  }
}
