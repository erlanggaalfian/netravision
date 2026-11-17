/* Pemutar WHEP (WebRTC), dipakai untuk live stream dari MediaMTX. */

/* Batas tunggu koneksi media (ICE) setelah sinyal WHEP sukses. Tanpa ini
   tile tampak "terhubung" tapi hitam selamanya bila UDP media tak sampai. */
const CONNECT_TIMEOUT_MS = 10000;
/* Batas tunggu respons awal POST sinyal WHEP (F3.2): bila server tidak
   menjawab, jangan menggantung selamanya. */
const SIGNAL_TIMEOUT_MS = 15000;

/* Error WHEP yang membawa status HTTP, supaya pemanggil bisa membedakan
   token ditolak (401/403, token media harus diinvalidasi lalu diminta
   baru, F3.3) dari gagal jaringan atau server. */
export class WhepError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

export async function playWhep(
  video: HTMLVideoElement,
  url: string,
  onFail?: () => void,
  signal?: AbortSignal,
  onDisconnect?: () => void,
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

  /* Sinyal WHEP dengan timeout sendiri (F3.2): AbortController lokal
     digabung dengan sinyal pemanggil, supaya pembatalan dari luar
     tetap bekerja dan timeout tidak menggantung. */
  const signalCtrl = new AbortController();
  const signalTimer = setTimeout(() => signalCtrl.abort(), SIGNAL_TIMEOUT_MS);
  const onOuterAbort = () => signalCtrl.abort();
  if (signal) {
    if (signal.aborted) signalCtrl.abort();
    else signal.addEventListener("abort", onOuterAbort, { once: true });
  }
  let res: Response;
  try {
    /* F6.5: url di sini membawa ?token= (lihat lib/media-token.ts).
       Risiko yang diterima: WHEP tidak bisa mengirim header
       Authorization, jadi token harus di URL. */
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: offer.sdp,
      signal: signalCtrl.signal,
    });
  } catch (e) {
    clearTimeout(signalTimer);
    signal?.removeEventListener("abort", onOuterAbort);
    pc.close();
    if (signal?.aborted || signalCtrl.signal.aborted) {
      throw new WhepError("WHEP dibatalkan");
    }
    throw e instanceof Error ? e : new WhepError("WHEP gagal");
  }
  clearTimeout(signalTimer);
  signal?.removeEventListener("abort", onOuterAbort);
  if (!res.ok) {
    pc.close();
    throw new WhepError(`WHEP gagal (${res.status})`, res.status);
  }
  const answerSdp = await res.text();
  if (signal?.aborted) throw new WhepError("dibatalkan");
  await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

  await new Promise<void>((resolve, reject) => {
    if (pc.connectionState === "connected") return resolve();
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      pc.removeEventListener("connectionstatechange", onStateChange);
      pc.close();
      reject(new WhepError("WebRTC tidak tersambung (media UDP tidak sampai)"));
    }, CONNECT_TIMEOUT_MS);
    /* F3.15: simpan referensi handler abort dan lepas di semua jalur
       keluar promise, supaya listener tidak menumpuk bila pemanggil
       memakai ulang satu sinyal. */
    const onAbort = () => {
      clearTimeout(timer);
      pc.removeEventListener("connectionstatechange", onStateChange);
      reject(new WhepError("dibatalkan"));
    };
    const onStateChange = () => {
      if (pc.connectionState === "connected") {
        clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        pc.removeEventListener("connectionstatechange", onStateChange);
        resolve();
      } else if (pc.connectionState === "failed") {
        clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        pc.removeEventListener("connectionstatechange", onStateChange);
        pc.close();
        reject(new WhepError("WebRTC gagal tersambung"));
      }
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    pc.addEventListener("connectionstatechange", onStateChange);
  });
  // Sudah tersambung: abort tidak lagi memutus koneksi yang sedang tampil.
  signal?.removeEventListener("abort", abort);

  // Putus di tengah jalan (jaringan/kamera), beri tahu pemanggil.
  // "disconnected" ditangani terpisah dari "failed": pemanggil bisa
  // menampilkan status terputus/mencoba lagi, bukan frame beku dengan
  // badge LIVE yang masih menyala.
  pc.addEventListener("connectionstatechange", () => {
    if (pc.connectionState === "failed") onFail?.();
    else if (pc.connectionState === "disconnected") onDisconnect?.();
  });

  try {
    await video.play();
  } catch {
    /* Autoplay bersuara ditolak browser, putar tanpa suara; pengguna
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
