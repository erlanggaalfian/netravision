/* Pemutar WHEP (WebRTC) — dipakai untuk live stream dari MediaMTX. */

export async function playWhep(
  video: HTMLVideoElement,
  url: string,
): Promise<RTCPeerConnection> {
  const pc = new RTCPeerConnection();
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
  });
  if (!res.ok) {
    pc.close();
    throw new Error(`WHEP gagal (${res.status})`);
  }
  const answerSdp = await res.text();
  await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

  try {
    await video.play();
  } catch {
    /* autoplay muted ditangani pemanggil */
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
