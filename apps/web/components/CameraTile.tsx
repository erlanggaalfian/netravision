"use client";

import { memo, useEffect, useRef, useState } from "react";
import { playWhep, stopWhep, WhepError } from "../lib/whep";
import { playHls, stopHls, isHlsWarm, type HlsHandle } from "../lib/hls";
import { getMediaUrls, isMediaTokenExpired, clearMediaTokenCache, type MediaUrls } from "../lib/media-token";
import { useFullscreen } from "../hooks/useFullscreen";
import { usePosterUrl } from "../lib/api";
import { AdBanner } from "./AdBanner";
import type { AdConfig, Stream } from "../lib/types";

interface Props {
  stream: Stream;
  onExpand: (stream: Stream) => void;
  ad?: AdConfig | null;
  /* Layar penuh grid Monitor: iklan masuk ke dalam frame (overlay di
     bawah area video), bukan di bawah video. */
  adInFrame?: boolean;
  /* Layar penuh grid Monitor: tile mengisi sel grid (stage fleksibel)
     supaya semua baris muat dan nama kamera tidak terpotong. */
  fillCell?: boolean;
}

/* Tile kamera: TIDAK PERNAH dilipat (aturan yang dikunci).
   Grid memakai sub stream (ringan); klik → modal pakai main stream (tajam).
   Kontrol overlay: tap-toggle di layar sentuh (class vk-touch-toggle).
   Visual konsol NVR: rounded-2xl, ring status 2px (ok/warn/bad),
   scrim netral untuk kontrol, empty/offline state rapi (ikon SVG + teks). */
/* F5.3: tile di-memo supaya satu pesan status WS tidak me-render
   ulang seluruh grid. Perbandingan memakai field yang memengaruhi
   tampilan/pemutaran, bukan identitas objek stream (halaman Live dan
   Monitor kini juga mempertahankan identitas objek stream yang tidak
   berubah statusnya, lihat merged di kedua halaman itu). */
function CameraTileInner({ stream, onExpand, ad, adInFrame = false, fillCell = false }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const hlsRef = useRef<HlsHandle | null>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const [failMsg, setFailMsg] = useState<string | null>(null);
  /* F5.6: status saat fallback HLS sedang dicoba, supaya pengguna
     tidak menatap spinner diam lebih dari 30 detik tanpa penjelasan. */
  const [hlsFallback, setHlsFallback] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const [retryTick, setRetryTick] = useState(0);
  /* F3.3: id kamera yang tokennya sudah sekali diinvalidasi lalu
     diminta baru karena WHEP menolak 401/403. Disimpan per id supaya
     ganti kamera membuka jatah coba ulang yang baru, dan token yang
     berhasil memutar mereset jatah (null) bila nanti dicabut lagi. */
  const authRetryForRef = useRef<number | null>(null);
  /* Auto-retry TANPA BATAS (keputusan user 2026-11-13): bila tile gagal
     atau koneksi putus di tengah jalan (mis. muxer HLS dingin, atau
     kamera RTSP putus sesaat), coba lagi otomatis tiap 10 dtk selama
     kamera masih online, sampai berhasil. Tidak ada lagi batas
     percobaan; tombol "Coba lagi" tetap tersedia untuk coba ulang
     manual seketika. */
  const AUTO_RETRY_DELAY_MS = 10000;
  const [showControls, setShowControls] = useState(false);
  /* Sinyal iklan: hover tile + tiap klik tile (perilaku marquee hover/click). */
  const [tileHovered, setTileHovered] = useState(false);
  const [adClickTick, setAdClickTick] = useState(0);

  const { fs, rotated, cssRotate, toggle: toggleFs, rotate } = useFullscreen(
    boxRef,
    videoRef,
  );

  /* Grid pakai sub stream bila kamera punya sub asli; bila TIDAK ADA
     sub (tidak punya sub_url asli), SELALU tampilkan MAIN stream
     (aturan user 2026-11-14, penegasan fallback). Transcoder mati
     total, jadi sub hanya ada bila sub_url asli tersedia; tile tidak
     boleh hitam/kosong hanya karena tidak ada sub. Keputusan lama
     "grid tidak pernah pakai main" SUDAH TIDAK BERLAKU (dibuat saat
     sub selalu ada via transcode). FocusModal (popup) memakai sub
     dulu lalu main (HD), dan tidak memakai komponen ini. */
  const hasSub = !!stream.whep_sub_url;
  /* K-1: URL WHEP/HLS mentah tidak lagi bisa dibuka tanpa kredensial
     (proxy API menolak tanpa token). Ambil URL yang sudah membawa token
     media (?token=) dari POST /api/media/token; token di-cache per
     kamera di lib/media-token.ts. hasSub menentukan varian yang dipakai
     (sub bila ada, main bila tidak ada sub), sama seperti sebelumnya. */
  const [mediaUrls, setMediaUrls] = useState<MediaUrls | null>(null);
  useEffect(() => {
    if (!stream.is_online) return;
    if (!stream.whep_main_url && !stream.whep_sub_url) return;
    let cancelled = false;
    getMediaUrls(stream.id, hasSub)
      .then((u) => {
        if (!cancelled) setMediaUrls(u);
      })
      .catch(() => {
        if (cancelled) return;
        setFailed(true);
        setFailMsg("Stream tidak dapat diputar");
      });
    return () => {
      cancelled = true;
    };
  }, [stream.id, stream.is_online, hasSub, retryTick]);

  /* Poster lewat blob object URL (header Authorization), bukan ?token= di URL. */
  const posterSrc = usePosterUrl(stream.poster_url);

  /* Pulih dari gagal: begitu kamera kembali online, URL berubah, atau
     kamera berganti, reset state gagal/terputus supaya tile mencoba
     ulang tanpa reload penuh. Effect WHEP di bawah memakai `failed`
     sebagai dependensi, jadi reset ini memicu percobaan ulang. */
  useEffect(() => {
    stopHls(hlsRef.current);
    hlsRef.current = null;
    setFailed(false);
    setFailMsg(null);
    setHlsFallback(false);
    setDisconnected(false);
    setPlaying(false);
    setMediaUrls(null);
  }, [stream.id, stream.is_online]);

  /* Auto-retry tile yang gagal ATAU terputus, TANPA BATAS: bila kamera
     masih online (is_online) tapi pemutaran gagal (failed) atau WHEP
     putus di tengah jalan (disconnected), coba lagi otomatis setelah
     jeda 10 dtk, terus menerus sampai berhasil. Reset bila kamera
     berganti/offline (effect di atas) atau bila berhasil memutar
     (onPlaying di tryHls / .then playWhep).
     Tidak ada URL WHEP sama sekali ("URL stream tidak tersedia") tidak
     ikut loop: tidak ada yang bisa dicoba sampai URL tersedia. */
  useEffect(() => {
    if ((!failed && !disconnected) || !stream.is_online) return;
    if (failMsg === "URL stream tidak tersedia") return;
    const t = setTimeout(() => {
      setFailed(false);
      setFailMsg(null);
      setDisconnected(false);
      setRetryTick((v) => v + 1);
    }, AUTO_RETRY_DELAY_MS);
    return () => clearTimeout(t);
  }, [failed, disconnected, stream.is_online, failMsg]);

  useEffect(() => {
    if (!stream.is_online) return;
    /* Online tapi tidak ada URL WHEP sama sekali: gagal dengan pesan
       yang jelas, bukan spinner selamanya. */
    if (!stream.whep_main_url && !stream.whep_sub_url) {
      setFailed(true);
      setFailMsg("URL stream tidak tersedia");
      return;
    }
    /* Token media belum tiba: tunggu effect pengambilan token di atas. */
    if (!mediaUrls) return;
    const url = mediaUrls.whepUrl;
    const hlsUrl = mediaUrls.hlsUrl;
    if (failed || disconnected) return;
    const box = boxRef.current;
    const video = videoRef.current;
    if (!box || !video) return;

    let cancelled = false;
    const fail = (msg: string) => {
      if (cancelled) return;
      stopWhep(pcRef.current);
      pcRef.current = null;
      stopHls(hlsRef.current);
      hlsRef.current = null;
      setPlaying(false);
      setFailed(true);
      setFailMsg(msg);
      setHlsFallback(false);
    };
    /* Fallback HLS bila WebRTC/WHEP gagal tersambung (UDP diblokir).
       HLS memakai varian yang sama dengan WHEP (sub bila ada, main
       bila tidak ada sub) via HTTP, jadi grid tetap menampilkan
       stream yang sama. Bila HLS juga gagal, baru fail.
       F6.5: hlsUrl membawa ?token= (lihat lib/media-token.ts).
       Risiko yang diterima, jangan tambahkan fitur salin URL stream.
       TUNGGU HANGAT: muxer HLS MediaMTX per-path butuh ~7-10 dtk untuk
       hangat (playlist awal berisi segmen gap, dan hls.js tetap mencoba
       memuat gap.mp4 lalu gagal fatal dengan 404). Sebelum memulai
       hls.js, periksa playlist variant hingga bebas gap (maks ~6 dtk);
       bila WHEP gagal cepat (bukan timeout 10 dtk), penantian ini yang
       menyelamatkan percobaan pertama. Bila setelah menunggu masih ada
       gap, tetap coba (retry di bawah yang menangani).
       RETRY (F5.6): maks 3 percobaan, jeda 2 detik (sebelumnya 5x
       jeda 4 detik, total menunggu bisa lebih dari 30 detik sebelum
       tampil gagal). Selama mencoba, tampilkan "Mencoba jalur
       cadangan..." lewat state hlsFallback. */
    const tryHls = async (attempt = 1) => {
      if (cancelled || hlsRef.current) return;
      setHlsFallback(true);
      /* Tunggu playlist bebas gap (maks 3x cek, jeda 2 dtk). */
      for (let i = 0; i < 3; i++) {
        if (cancelled || hlsRef.current) return;
        if (await isHlsWarm(hlsUrl)) break;
        await new Promise((r) => setTimeout(r, 2000));
      }
      if (cancelled || hlsRef.current) return;
      const v = videoRef.current;
      if (!v) {
        fail("Stream tidak dapat diputar");
        return;
      }
      try {
        v.srcObject = null;
      } catch {
        /* abaikan */
      }
      try {
        /* F5.1: playHls kini async (dynamic import hls.js). */
        const handle = await playHls(v, hlsUrl, () => {
          if (cancelled) return;
          stopHls(hlsRef.current);
          hlsRef.current = null;
          if (attempt < 3) {
            setTimeout(() => {
              if (!cancelled) tryHls(attempt + 1);
            }, 2000);
          } else {
            setHlsFallback(false);
            /* F3.3: HLS juga gagal setelah semua percobaan, token
               mungkin sudah dicabut. Hapus cache supaya percobaan
               auto-retry berikutnya memakai token baru, bukan URL
               bertoken lama yang sama. */
            clearMediaTokenCache(stream.id);
            fail("Stream tidak dapat diputar");
          }
        });
        hlsRef.current = handle;
        const onPlaying = () => {
          if (cancelled) return;
          setHlsFallback(false);
          setDisconnected(false);
          setPlaying(true);
        };
        v.addEventListener("playing", onPlaying, { once: true });
      } catch {
        setHlsFallback(false);
        fail("Stream tidak dapat diputar");
      }
    };
    const io = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry.isIntersecting && !pcRef.current && !hlsRef.current && !cancelled) {
          /* F2.12: tile kembali terlihat dengan token basi (cache
             kedaluwarsa) jangan diputar ulang dulu; minta URL baru,
             effect di atas memutar ulang begitu mediaUrls diperbarui. */
          if (isMediaTokenExpired(stream.id, hasSub)) {
            getMediaUrls(stream.id, hasSub)
              .then((u) => {
                if (!cancelled) setMediaUrls(u);
              })
              .catch(() => {});
            return;
          }
          /* F5.6: JANGAN panaskan HLS selagi WHEP dicoba. Pemanasan
             hanya di dalam tryHls (lewat isHlsWarm), yaitu setelah
             WHEP gagal atau timeout; sebelumnya tiap tile membayar
             1 request HLS sia-sia walau WHEP sukses. */
          playWhep(
            video,
            url,
            () => fail("Stream tidak dapat diputar"),
            undefined,
            () => {
              if (cancelled) return;
              stopWhep(pcRef.current);
              pcRef.current = null;
              setPlaying(false);
              setDisconnected(true);
            },
          )
            .then((pc) => {
              if (cancelled) {
                stopWhep(pc);
                return;
              }
              pcRef.current = pc;
              authRetryForRef.current = null;
              setDisconnected(false);
              setPlaying(true);
            })
            .catch((e) => {
              /* F3.3: token ditolak server (401/403). Hapus entri cache
                 kamera ini lalu minta token baru sekali; effect di atas
                 memutar ulang begitu mediaUrls diperbarui. Bila token
                 baru juga ditolak, baru jatuh ke HLS. */
              if (
                e instanceof WhepError &&
                (e.status === 401 || e.status === 403) &&
                authRetryForRef.current !== stream.id
              ) {
                authRetryForRef.current = stream.id;
                clearMediaTokenCache(stream.id);
                getMediaUrls(stream.id, hasSub)
                  .then((u) => {
                    if (!cancelled) setMediaUrls(u);
                  })
                  .catch(() => {
                    if (!cancelled) tryHls();
                  });
                return;
              }
              /* WebRTC gagal (biasanya UDP diblokir): coba HLS. */
              tryHls();
            });
        } else if (!entry.isIntersecting && (pcRef.current || hlsRef.current)) {
          stopWhep(pcRef.current);
          pcRef.current = null;
          stopHls(hlsRef.current);
          hlsRef.current = null;
          setPlaying(false);
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(box);
    return () => {
      cancelled = true;
      io.disconnect();
      stopWhep(pcRef.current);
      pcRef.current = null;
      stopHls(hlsRef.current);
      hlsRef.current = null;
    };
  }, [mediaUrls, stream.is_online, stream.id, stream.whep_main_url, stream.whep_sub_url, hasSub, failed, disconnected, retryTick]);

  const toggleControls = () => setShowControls((v) => !v);

  const online = stream.is_online && !failed && !disconnected;
  /* Kontrol disembunyikan hanya dengan opacity 0 + pointer-events none
     (CSS .cam-controls di globals.css), BUKAN visibility hidden, supaya
     tombol tetap bisa difokuskan keyboard saat :focus-within aktif. */

  return (
    <div
      ref={boxRef}
      /* Tile bisa difokuskan keyboard (F4.1): Enter saat fokus di tile
         membuka FocusModal, sama seperti klik Perbesar. Fokus di tombol
         dalam tile tidak memicu ini (target bukan tile itu sendiri). */
      tabIndex={0}
      role="group"
      aria-label={`Kamera ${stream.name}, tekan Enter untuk memperbesar`}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) {
          e.preventDefault();
          onExpand(stream);
        }
      }}
      onMouseEnter={() => setTileHovered(true)}
      onMouseLeave={() => setTileHovered(false)}
      /* Fallback keyboard untuk :focus-within (I1): tampilkan kontrol saat
         fokus keyboard masuk ke tile, sembunyikan saat fokus keluar. */
      onFocus={() => setShowControls(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) {
          setShowControls(false);
        }
      }}
      className={`vk-touch-toggle ${showControls ? "cam-show-controls" : ""} group relative select-none overflow-hidden transition-all duration-300 ${
        fs
          ? "fixed inset-0 z-[70] border-0 bg-black"
          : `rounded-2xl bg-ink-900 shadow-[0_8px_24px_-8px_rgba(0,0,0,0.35)] ${fillCell ? "flex h-full flex-col" : ""}`
      }`}
    >
      {/* Area video: selalu gelap (nv-stage), di kedua tema. Klik di sini
          saja yang toggle kontrol dan memberi sinyal klik iklan; klik pada
          footer atau banner iklan di bawah tidak ikut. */}
      <div
        onClick={() => {
          toggleControls();
          setAdClickTick((t) => t + 1);
        }}
        className={`nv-stage relative bg-black ${cssRotate ? "nv-rot" : ""} ${fs ? "h-full" : fillCell ? "min-h-0 flex-1" : "aspect-video"}`}
      >
      <div className="nv-rot-inner relative h-full w-full">
      {stream.is_online && !failed ? (
        <>
          <video
            ref={videoRef}
            muted
            playsInline
            className={`h-full w-full ${fs || fillCell ? "object-contain" : "object-cover"}`}
          />
          {!playing &&
            (posterSrc ? (
              <img
                src={posterSrc}
                alt={stream.name}
                loading="lazy"
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="flex items-center gap-2.5 rounded-full bg-black/50 px-4 py-2 text-xs font-medium text-slate-300">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/15 border-t-accent-400 motion-reduce:animate-none" />
                  {hlsFallback ? "Mencoba jalur cadangan…" : "Menghubungkan…"}
                </span>
              </div>
            ))}
          {playing && !disconnected && (
            <span className="pointer-events-none absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-[11px] font-bold tracking-wider text-white shadow-[0_4px_12px_rgba(0,0,0,0.4)]">
              <span className="h-1.5 w-1.5 rounded-full bg-bad-400 shadow-[0_0_8px_2px_rgba(248,113,113,0.6)]" />
              LIVE
            </span>
          )}
          {disconnected && !playing && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60 px-4 text-center">
              <span className="text-sm font-semibold text-slate-200">
                Koneksi terputus
              </span>
              <span className="text-xs text-slate-400">
                Mencoba lagi, atau ketuk Coba lagi di bawah.
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setDisconnected(false);
                  setRetryTick((t) => t + 1);
                }}
                className="mt-1 flex h-11 items-center rounded-xl bg-white/10 px-4 text-xs font-bold text-white transition hover:bg-white/25 active:scale-95"
              >
                Coba lagi
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="relative flex h-full w-full flex-col items-center justify-center gap-2.5 bg-ink-900 px-4 text-center">
          {posterSrc && (
            <img
              src={posterSrc}
              alt=""
              aria-hidden
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover opacity-20"
            />
          )}
          <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-ink-800">
            <svg
              width="26"
              height="26"
              viewBox="0 0 24 24"
              fill="none"
              className="text-slate-400"
              aria-hidden
            >
              <path
                d="M3 8.5A1.5 1.5 0 014.5 7h9A1.5 1.5 0 0115 8.5v6a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 013 14.5v-6z"
                stroke="currentColor"
                strokeWidth="1.6"
              />
              <path
                d="M15 10.5l5-3v9l-5-3"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path
                d="M4 4l16 16"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </div>
          <span className="relative text-sm font-semibold tracking-tight text-slate-200">
            {stream.is_online ? "Gagal memuat" : "Offline"}
          </span>
          <span className="relative text-xs text-slate-400">
            {stream.is_online
              ? (failMsg ?? "Stream tidak dapat diputar")
              : "Kamera tidak terjangkau"}
          </span>
          {stream.is_online && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setFailed(false);
                setFailMsg(null);
                setRetryTick((t) => t + 1);
              }}
              className="relative mt-1 flex h-11 items-center rounded-xl bg-ink-800 px-4 text-xs font-bold text-slate-100 transition hover:bg-ink-700 active:scale-95"
            >
              Coba lagi
            </button>
          )}
        </div>
      )}

      {/* Overlay kontrol: hanya tombol aksi (nama + status ada di footer kartu) */}
      <div className="cam-controls absolute inset-x-0 bottom-0 z-30 flex items-center justify-end gap-2 bg-gradient-to-t from-black/85 via-black/40 to-transparent px-3 pb-3 pt-8">
        <div className="flex shrink-0 items-center gap-2">
          {fs && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                rotate();
              }}
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-white transition active:scale-95 ${rotated ? "bg-accent-400/30 hover:bg-accent-400/40" : "bg-white/10 hover:bg-white/25"}`}
              aria-label={rotated ? "Ikuti rotasi HP" : "Putar ke landscape"}
              aria-pressed={rotated}
              title={rotated ? "Ikuti rotasi HP" : "Putar ke landscape"}
            >
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
                <rect
                  x="6"
                  y="2.5"
                  width="8"
                  height="13"
                  rx="1.5"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  transform={rotated ? "rotate(90 10 9)" : undefined}
                />
                <path
                  d="M3 13.5a7 7 0 004.5 4M17 6.5a7 7 0 00-4.5-4"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              toggleFs();
            }}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white shadow-[0_4px_12px_rgba(0,0,0,0.3)] transition-all duration-200 hover:bg-white/25 hover:shadow-[0_6px_16px_rgba(0,0,0,0.4)] active:scale-95"
            aria-label={fs ? `Keluar layar penuh ${stream.name}` : `Layar penuh ${stream.name}`}
            title={fs ? "Keluar layar penuh" : "Layar penuh"}
          >
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path
                d={fs ? "M6 2v4H2M14 6h-4V2M10 14v-4h4M2 10h4v4" : "M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"}
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              /* F2.1: FocusModal (z-50) terbuka di balik tile fullscreen
                 (z-[70]); keluar fullscreen dulu bila aktif. */
              if (fs) toggleFs();
              onExpand(stream);
            }}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white shadow-[0_4px_12px_rgba(0,0,0,0.3)] transition-all duration-200 hover:bg-white/25 hover:shadow-[0_6px_16px_rgba(0,0,0,0.4)] active:scale-95"
          aria-label={`Perbesar ${stream.name}`}
          title="Perbesar"
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
            <path
              d="M6 2H2v4M10 14h4v-4M2 2l4 4M14 14l-4-4"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          </svg>
        </button>
        </div>
      </div>
      </div>
      {/* Iklan di dalam frame (overlay) saat layar penuh grid Monitor:
          menempel di bawah area video, di dalam 16:9. */}
      {adInFrame && ad?.is_active && (
        <AdBanner
          config={ad}
          hovered={tileHovered}
          clickTick={adClickTick}
          placement="overlay"
        />
      )}
      </div>
      {/* Iklan di bawah video (di luar area 16:9), bukan overlay, supaya
          tidak menutupi tombol. Disembunyikan saat layar penuh dan saat
          iklan dipindah ke dalam frame (adInFrame). */}
      {!fs && !adInFrame && ad?.is_active && (
        <AdBanner
          config={ad}
          hovered={tileHovered}
          clickTick={adClickTick}
          placement="below"
        />
      )}
      {/* Footer kartu: titik status kecil + nama kamera saja (tanpa chip).
          Disembunyikan saat layar penuh grid Monitor (fillCell): nama
          kamera tidak ditampilkan di mode itu. */}
      {!fs && !fillCell && (
        <div className="flex items-center gap-2 border-t border-ink-800/60 px-3.5 py-3">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${online ? "bg-ok-400" : "bg-bad-400"}`}
            aria-label={online ? "Online" : "Offline"}
          />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight text-white">
            {stream.name}
          </span>
        </div>
      )}
    </div>
  );
}

function cameraTilePropsEqual(prev: Props, next: Props): boolean {
  return (
    prev.stream.id === next.stream.id &&
    prev.stream.is_online === next.stream.is_online &&
    prev.stream.name === next.stream.name &&
    prev.stream.poster_url === next.stream.poster_url &&
    prev.stream.whep_main_url === next.stream.whep_main_url &&
    prev.stream.whep_sub_url === next.stream.whep_sub_url &&
    prev.onExpand === next.onExpand &&
    prev.ad === next.ad &&
    prev.adInFrame === next.adInFrame &&
    prev.fillCell === next.fillCell
  );
}

export const CameraTile = memo(CameraTileInner, cameraTilePropsEqual);
