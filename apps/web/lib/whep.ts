/* Pemutar WHEP (WebRTC) — dipakai untuk live stream dari MediaMTX. */

/* Batas tunggu koneksi media (ICE) setelah sinyal WHEP sukses. Tanpa ini
   tile tampak "terhubung" tapi hitam selamanya bila UDP media tak sampai. */
const CONNECT_TIMEOUT_MS = 10000;

export async function playWhep(
  video: HTMLVideoElement,
  url: string,
  onFail?: () => void,
  signal?: AbortSignal,
): Promise<RTCPeerConnection> {
  const pc = new RTCPeerConnection();
  const abort = () => pc.close();
  signal?.addEventListener("abort", abort, { once: true });
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });

  const stream = new MediaStream();
  pc.ontrack = (ev) => {
    stream.addTrack(ev.track);
  };
  video.srcObject = stream;

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: offer.sdp,
    signal,
  });
  if (!res.ok) {
    pc.close();
    throw new Error(`WHEP gagal (${res.status})`);
  }
  const answerSdp = await res.text();
  if (signal?.aborted) throw new Error("dibatalkan");
  await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

  await new Promise<void>((resolve, reject) => {
    if (pc.connectionState === "connected") return resolve();
    const timer = setTimeout(() => {
      pc.close();
      reject(new Error("WebRTC tidak tersambung (media UDP tidak sampai)"));
    }, CONNECT_TIMEOUT_MS);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new Error("dibatalkan"));
    });
    pc.addEventListener("connectionstatechange", () => {
      if (pc.connectionState === "connected") {
        clearTimeout(timer);
        resolve();
      } else if (pc.connectionState === "failed") {
        clearTimeout(timer);
        pc.close();
        reject(new Error("WebRTC gagal tersambung"));
      }
    });
  });
  // Sudah tersambung: abort tidak lagi memutus koneksi yang sedang tampil.
  signal?.removeEventListener("abort", abort);

  // Putus di tengah jalan (jaringan/kamera) — beri tahu pemanggil.
  pc.addEventListener("connectionstatechange", () => {
    if (pc.connectionState === "failed") onFail?.();
  });

  try {
    await video.play();
  } catch {
    /* Autoplay bersuara ditolak browser — putar tanpa suara; pengguna
       bisa menyalakan suara lewat kontrol video. */
    video.muted = true;
    await video.play().catch(() => {});
  }
  return pc;
}

export function stopWhep(pc: RTCPeerConnection | null) {
  try {
    pc?.close();
  } catch {
    /* abaikan */
  }
}
