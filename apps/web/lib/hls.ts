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
