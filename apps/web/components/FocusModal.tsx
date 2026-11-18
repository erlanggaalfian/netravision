"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { playWhep, stopWhep, WhepError } from "../lib/whep";
import { getMediaUrls, clearMediaTokenCache } from "../lib/media-token";
import { usePosterUrl } from "../lib/api";
import { AdBanner } from "./AdBanner";
import { Badge, Button } from "./ui";
import { useFullscreen } from "../hooks/useFullscreen";
import { useFocusTrap } from "../hooks/useFocusTrap";
import type { Stream, AdConfig } from "../lib/types";

interface Props {
  stream: Stream | null;
  onClose: () => void;
  /* Config iklan dari halaman Live (sudah diambil sekali per halaman),
     bukan fetch sendiri di sini. */
  ad?: AdConfig | null;
}

/* Modal fokus, pola v2 (openCameraPopup): SUB dulu agar langsung tampil,
   lalu MAIN (HD) disambung di latar dan ditukar mulus begitu frame pertama
   main siap. Main gagal, tetap di SUB. Tombol LQ/HQ untuk ganti manual.
   Banner iklan (bila aktif dan diizinkan untuk akun ini) tampil di bawah
   video (placement below), bukan overlay.
   Visual: header rapi (status + nama + info stream), kontrol jelas 44px. */
export function FocusModal({ stream, onClose, ad }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const switchRef = useRef<((url: string, target: "LQ" | "HQ") => void) | null>(null);
  const cancelSwitchRef = useRef<(() => void) | null>(null);
  /* URL WHEP yang sudah membawa token media (?token=), diisi setelah
     POST /api/media/token (K-1). Dipakai toggle LQ/HQ manual; URL mentah
     dari stream tidak lagi bisa dibuka tanpa token. */
  const urlsRef = useRef<{ main: string | null; sub: string | null } | null>(null);
  const hqTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  /* F3.3: id kamera yang tokennya sudah sekali diinvalidasi lalu
     diminta baru karena WHEP menolak 401/403. Per id supaya ganti
     kamera membuka jatah baru; token yang berhasil memutar mereset
     jatah (null) bila nanti dicabut lagi. */
  const authRetryForRef = useRef<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [failMsg, setFailMsg] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [retryTick, setRetryTick] = useState(0);
  /* Auto-retry TANPA BATAS (keputusan user 2026-11-13), sama seperti
     CameraTile: bila gagal atau putus di tengah jalan, coba lagi tiap
     10 dtk selama kamera masih online sampai berhasil. Sebelum ini
     FocusModal TIDAK punya auto-retry sama sekali dan putus di tengah
     jalan ("disconnected") bahkan tidak ditangani: video beku tanpa
     pemulihan sampai modal ditutup lalu dibuka lagi. */
  const AUTO_RETRY_DELAY_MS = 10000;
  const [vRatio, setVRati] = useState<string | null>(null);
  const [quality, setQuality] = useState<"LQ" | "HQ">("LQ");
  /* F2.9: tombol LQ/HQ dinonaktifkan sampai token media tiba. */
  const [urlsReady, setUrlsReady] = useState(false);
  const isDesktop = () =>
    typeof window !== "undefined" &&
    window.matchMedia("(min-width: 768px)").matches &&
    window.matchMedia("(pointer: fine)").matches;
  const [want, setWant] = useState<"LQ" | "HQ">(() => (isDesktop() ? "HQ" : "LQ"));
  /* Sinyal iklan: hover stage + tiap klik stage (perilaku marquee hover/click). */
  const [stageHovered, setStageHovered] = useState(false);
  const [adClickTick, setAdClickTick] = useState(0);
  /* Poster lewat blob object URL (header Authorization), bukan ?token= di URL. */
  const posterSrc = usePosterUrl(stream?.poster_url);
  const stageRef = useRef<HTMLDivElement>(null);
  const { fs, rotated, cssRotate, toggle: toggleFs, rotate } = useFullscreen(
    stageRef,
    videoRef,
  );

  /* Default seperti v2: desktop (>=768px) HQ, HP LQ. Tombol LQ/HQ bisa
     mengganti di keduanya. Kamera berganti -> kembali ke default. */
  useEffect(() => {
    setWant(isDesktop() ? "HQ" : "LQ");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream]);

  useEffect(() => {
    setFailed(false);
    setFailMsg(null);
    setPlaying(false);
    setVRati(null);
    setQuality("LQ");
    setUrlsReady(false);
    const video = videoRef.current;
    const hasMain = !!stream?.whep_main_url;
    const hasSub = !!stream?.whep_sub_url;
    /* Online tapi tidak ada URL WHEP sama sekali: gagal dengan pesan
       yang jelas, bukan spinner selamanya. */
    if (stream?.is_online && !(hasMain || hasSub)) {
      setFailed(true);
      setFailMsg("URL stream tidak tersedia");
      return;
    }
    if (!video || !(hasMain || hasSub) || !stream?.is_online) return;
    const streamId = stream.id;
    /* F3.3: token ditolak server (WHEP 401/403). Hapus cache kamera
       ini lalu picu satu percobaan ulang dengan token baru (lewat
       retryTick, effect berjalan lagi dan getUrls meminta token baru).
       Kembalikan true bila retry dijadwalkan, false bila jatah sudah
       habis atau error bukan karena token ditolak. */
    const retryWithFreshToken = (e: unknown): boolean => {
      if (
        !(e instanceof WhepError) ||
        (e.status !== 401 && e.status !== 403) ||
        authRetryForRef.current === streamId
      ) {
        return false;
      }
      authRetryForRef.current = streamId;
      clearMediaTokenCache(streamId);
      setRetryTick((v) => v + 1);
      return true;
    };
    let cancelled = false;
    let pending: RTCPeerConnection | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const fail = (msg?: string) => {
      if (cancelled) return;
      /* F2.10: tutup koneksi WHEP yang gagal, jangan dibiarkan hidup. */
      stopWhep(pcRef.current);
      pcRef.current = null;
      /* Gagal/putus: batalkan upgrade HQ yang tertunda dan switch yang
         masih jalan, supaya tidak ada sesi tersembunyi yang menukar
         srcObject saat modal sudah menampilkan error. */
      clearTimeout(timer);
      hqTimerRef.current = undefined;
      cancelSwitchRef.current?.();
      cancelSwitchRef.current = null;
      if (msg) setFailMsg(msg);
      setFailed(true);
    };

    /* K-1: URL WHEP yang sudah membawa token media (?token=) untuk
       main dan sub. URL mentah tidak lagi bisa dibuka tanpa token.
       Token di-cache per kamera di lib/media-token.ts. */
    const getUrls = async (): Promise<{
      main: string | null;
      sub: string | null;
    } | null> => {
      try {
        /* F5.7: token main hanya diminta bila dibutuhkan. Tanpa sub,
           main adalah satu-satunya jalur jadi wajib diminta; dengan
           sub dan want LQ (HP), main TIDAK diminta dulu, baru diminta
           saat pengguna menekan HQ (lihat toggleQuality). Sebelumnya
           modal selalu meminta 2 token dan membuka 2 sesi sekaligus. */
        const needMain = want === "HQ" || !hasSub;
        const [mainUrls, subUrls] = await Promise.all([
          needMain ? getMediaUrls(streamId, false) : Promise.resolve(null),
          hasSub ? getMediaUrls(streamId, true) : Promise.resolve(null),
        ]);
        if (cancelled) return null;
        const urls = { main: mainUrls?.whepUrl ?? null, sub: subUrls?.whepUrl ?? null };
        urlsRef.current = urls;
        setUrlsReady(true);
        return urls;
      } catch {
        if (!cancelled) fail("Stream tidak dapat diputar");
        return null;
      }
    };

    /* Ganti stream dengan smooth: sambung URL baru di elemen tersembunyi,
       tukar srcObject saat sudah bergambar (tanpa layar hitam/loading),
       lalu tutup koneksi lama. Dipakai untuk upgrade otomatis maupun
       toggle manual LQ/HQ dua arah. */
    const smoothSwitch = (url: string, target: "LQ" | "HQ") => {
      if (cancelled || !url) return;
      // Batalkan switch yang masih jalan bila ada, supaya tidak ada
      // dua sesi WHEP yang berebut srcObject saat toggle cepat atau
      // bersamaan dengan auto-upgrade.
      cancelSwitchRef.current?.();
      cancelSwitchRef.current = null;
      if (pending) {
        stopWhep(pending);
        pending = null;
      }
      const hidden = document.createElement("video");
      hidden.muted = true;
      hidden.playsInline = true;
      // Tandai switch ini sedang berjalan agar tidak tertimpa.
      let myCancelled = false;
      const cancelMine = () => {
        myCancelled = true;
      };
      cancelSwitchRef.current = cancelMine;
      /* Setelah swap, koneksi ini jadi koneksi live: putus/gagal di tengah
         jalan harus memicu fail + auto-retry seperti koneksi utama.
         Sebelum swap (masih tersembunyi), putus diabaikan supaya stream
         lama tetap jalan. Sebelum perbaikan ini, koneksi hasil switch
         (termasuk upgrade otomatis LQ ke HQ) tidak punya handler sama
         sekali, jadi putusnya tidak terdeteksi. */
      let isLive = false;
      let swapped = false;
      /* F2.11: bila video tersembunyi tidak pernah bergambar, batalkan
         switch setelah 12 detik dan tutup koneksi tersembunyi, supaya
         tidak ada sesi WHEP zombie per toggle gagal. */
      const switchTimer = setTimeout(() => {
        if (swapped || cancelled || myCancelled) return;
        myCancelled = true;
        if (cancelSwitchRef.current === cancelMine) {
          cancelSwitchRef.current = null;
        }
        if (pending) {
          stopWhep(pending);
          pending = null;
        }
      }, 12000);
      const onSwitchConnFail = () => {
        if (cancelled || myCancelled || !isLive) return;
        fail();
      };
      playWhep(hidden, url, onSwitchConnFail, undefined, onSwitchConnFail)
        .then((pc) => {
          if (cancelled || myCancelled) {
            clearTimeout(switchTimer);
            return stopWhep(pc);
          }
          pending = pc;
          const swap = () => {
            if (cancelled || myCancelled || hidden.videoWidth === 0) return;
            swapped = true;
            clearTimeout(switchTimer);
            video.srcObject = hidden.srcObject;
            video.play().catch(() => {});
            stopWhep(pcRef.current);
            pcRef.current = pc;
            pending = null;
            isLive = true;
            if (cancelSwitchRef.current === cancelMine) {
              cancelSwitchRef.current = null;
            }
            setQuality(target);
          };
          if (hidden.videoWidth > 0) swap();
          else hidden.addEventListener("resize", swap, { once: true });
        })
        .catch((e) => {
          /* gagal: tetap di stream lama, jangan tampilkan error.
             F3.3: token ditolak saat switch kualitas, hapus cache,
             minta token baru sekali, lalu coba switch lagi dengan URL
             baru; tetap di stream lama bila token baru juga gagal. */
          clearTimeout(switchTimer);
          if (cancelSwitchRef.current === cancelMine) {
            cancelSwitchRef.current = null;
          }
          if (
            e instanceof WhepError &&
            (e.status === 401 || e.status === 403) &&
            authRetryForRef.current !== streamId
          ) {
            authRetryForRef.current = streamId;
            clearMediaTokenCache(streamId);
            getMediaUrls(streamId, target === "LQ")
              .then((u) => {
                if (cancelled || myCancelled) return;
                smoothSwitch(u.whepUrl, target);
              })
              .catch(() => {});
          }
        });
      return cancelMine;
    };
    // Simpan agar toggle manual bisa pakai.
    switchRef.current = smoothSwitch;

    /* Sambung MAIN di elemen tersembunyi; tukar srcObject saat sudah
       bergambar (tanpa layar hitam), lalu tutup koneksi SUB (di dalam
       smoothSwitch, tepat setelah frame pertama main tampil). */
    const goHQ = () => {
      const main = urlsRef.current?.main;
      if (!main || cancelled) return;
      /* F5.7: jangan upgrade selagi sub belum benar-benar bergambar
         stabil; bila video belum punya frame, tunda 1 detik lagi. */
      if (!video.videoWidth || video.readyState < 2) {
        timer = setTimeout(goHQ, 1000);
        hqTimerRef.current = timer;
        return;
      }
      smoothSwitch(main, "HQ");
    };

    void getUrls().then((urls) => {
      if (!urls || cancelled) return;
      const { main, sub } = urls;
      if (want === "LQ" || !main || !sub) {
        /* Putus di tengah jalan ("disconnected") diperlakukan sama seperti
           gagal: tampilkan error lalu auto-retry tanpa batas (effect di
           bawah). Sebelumnya argumen onDisconnect tidak diisi, jadi putus
           di tengah jalan tidak terdeteksi sama sekali. */
        playWhep(video, (want === "HQ" ? main : sub) || main || sub!, fail, undefined, () => fail())
          .then((pc) => {
            if (cancelled) return stopWhep(pc);
            pcRef.current = pc;
            authRetryForRef.current = null;
            /* Tanpa sub, yang diputar adalah main -> kualitas HQ, bukan
               LQ (label subtitle harus benar). */
            setQuality(!sub || (want === "HQ" && main) ? "HQ" : "LQ");
          })
          .catch((e) => {
            /* F3.3: token ditolak, coba sekali dengan token baru
               sebelum menyatakan gagal. */
            if (!retryWithFreshToken(e)) fail();
          });
      } else {
        playWhep(video, sub, fail, undefined, () => fail())
          .then((pc) => {
            if (cancelled) return stopWhep(pc);
            pcRef.current = pc;
            authRetryForRef.current = null;
            /* F5.7: upgrade HD 2,5 detik setelah sub tampil (sebelumnya
               1 detik), supaya sub benar-benar bergambar stabil dulu;
               goHQ menunda lagi bila video belum punya frame. */
            timer = setTimeout(goHQ, 2500);
            hqTimerRef.current = timer;
          })
          .catch((e) => {
            if (cancelled) return;
            /* F3.3: token sub ditolak, coba sekali dengan token baru
               sebelum jatuh ke HQ. */
            if (!retryWithFreshToken(e)) goHQ();
          });
      }
    });
    return () => {
      cancelled = true;
      clearTimeout(timer);
      hqTimerRef.current = undefined;
      cancelSwitchRef.current?.();
      cancelSwitchRef.current = null;
      stopWhep(pending);
      stopWhep(pcRef.current);
      pcRef.current = null;
      switchRef.current = null;
      urlsRef.current = null;
    };
    /* P0 code-review 2026-11-18: dependensi dibatasi ke hal yang
       memengaruhi pemutaran (id/is_online/URL WHEP) + want/retryTick.
       Sebelumnya objek `stream` utuh jadi dependensi, sehingga
       perubahan nama/poster_url (yang tidak memengaruhi stream)
       ikut teardown total dan sambung ulang WHEP dari nol. Objek
       stream tetap dipakai di dalam effect, jadi disable exhaustive-deps
       di sini disengaja dan terdokumentasi. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream?.id, stream?.is_online, stream?.whep_main_url, stream?.whep_sub_url, want, retryTick]);

  /* Ganti LQ/HQ manual (dipakai tombol di header DAN tombol di overlay
     panggung, supaya kualitas bisa diganti saat layar penuh, saat tombol
     header tidak terlihat). Logika sama: batalkan auto-upgrade yang
     tertunda, sambung halus lewat switchRef. */
  const toggleQuality = useCallback(() => {
    const target = quality === "HQ" ? "LQ" : "HQ";
    /* K-1: pakai URL bertoken dari urlsRef, bukan URL mentah stream. */
    const urls = urlsRef.current;
    const url = target === "HQ" ? urls?.main : urls?.sub;
    if (hqTimerRef.current) {
      clearTimeout(hqTimerRef.current);
      hqTimerRef.current = undefined;
    }
    if (url && switchRef.current) {
      switchRef.current(url, target);
      return;
    }
    /* F5.7: token main belum diminta (modal dibuka sebagai LQ di HP):
       minta token main dulu, baru switch ke HQ. */
    if (target === "HQ" && stream && switchRef.current) {
      const switchFn = switchRef.current;
      getMediaUrls(stream.id, false)
        .then((u) => {
          urlsRef.current = { main: u.whepUrl, sub: urlsRef.current?.sub ?? null };
          switchFn(u.whepUrl, "HQ");
        })
        .catch(() => {
          /* token main gagal: tetap di LQ, jangan tampilkan error */
        });
    }
  }, [quality, stream]);

  /* Auto-retry TANPA BATAS: bila gagal (termasuk putus di tengah jalan,
     yang dipetakan ke fail) dan kamera masih online serta ada URL WHEP,
     coba lagi tiap 10 dtk sampai berhasil. Tanpa URL sama sekali
     ("URL stream tidak tersedia") tidak ikut loop. Berhenti bila modal
     ditutup (unmount, timeout dibersihkan) atau kamera offline. */
  useEffect(() => {
    if (!failed || !stream?.is_online) return;
    if (failMsg === "URL stream tidak tersedia") return;
    const t = setTimeout(() => {
      setFailed(false);
      setFailMsg(null);
      setRetryTick((v) => v + 1);
    }, AUTO_RETRY_DELAY_MS);
    return () => clearTimeout(t);
  }, [failed, failMsg, stream?.is_online]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.fullscreenElement) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  /* Focus trap bersama (F4.2), sama seperti Modal umum. */
  useFocusTrap(dialogRef, !!stream);

  if (!stream) return null;

  const canSnapshot =
    playing && !failed && !!stream?.is_online;
  const snapshot = () => {
    const video = videoRef.current;
    /* Jangan unduh JPEG 0x0 dan jangan diam tanpa umpan balik: tombol
       sudah dinonaktifkan bila belum ada frame, guard ini lapis kedua. */
    if (!video) return;
    if (!video.videoWidth || !video.videoHeight || video.readyState < 2) return;
    const c = document.createElement("canvas");
    c.width = video.videoWidth;
    c.height = video.videoHeight;
    c.getContext("2d")?.drawImage(video, 0, 0);
    const a = document.createElement("a");
    a.href = c.toDataURL("image/jpeg", 0.85);
    /* F6.8: nama file dari nama kamera disanitasi dulu: karakter yang
       tidak valid di nama file diganti "_", dipotong 80 karakter, dan
       titik di awal/akhir dibuang, supaya unduhan tidak menghasilkan
       nama file aneh atau terpotong. */
    const safeName = stream.name
      .replace(/[\\/:*?"<>|]/g, "_")
      .slice(0, 80)
      .replace(/^\.+|\.+$/g, "");
    a.download = `${safeName || "kamera"}-${Date.now()}.jpg`;
    a.click();
  };

  return (
    <div
      /* Backdrop blur disamakan di semua popup (FocusModal, Modal ui.tsx,
         Modal _nb.tsx): backdrop-blur-sm, tipis dan modern. Opasitas
         dilonggarkan 70 ke 60 supaya blur di balik video tetap terbaca. */
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 backdrop-blur-sm p-0 sm:items-center sm:p-6"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        className="nv-pop max-h-[calc(100dvh-1.5rem)] w-full max-w-5xl overflow-x-hidden overflow-y-auto rounded-t-2xl bg-ink-900 ring-1 ring-ink-600/20 pb-[env(safe-area-inset-bottom)] sm:max-h-[calc(100dvh-3rem)] sm:rounded-2xl sm:pb-0"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={stream.name}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-ink-800 px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <span
              className={`h-2.5 w-2.5 shrink-0 rounded-full ${stream.is_online ? "bg-ok-400" : "bg-bad-400"}`}
            />
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold text-white">
                {stream.name}
              </h2>
              <p className="text-xs text-slate-400">
                {quality === "HQ" ? "Main stream (HD)" : "Sub stream (LQ)"}
                {stream.brand ? `, ${stream.brand}` : ""}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {/* Tanpa sub stream tidak ada yang bisa diganti (hanya
               main): sembunyikan tombol kualitas supaya tidak
               membingungkan. */}
            {stream?.whep_sub_url && (
            <Button
              variant={quality === "HQ" ? "primary" : "subtle"}
              onClick={toggleQuality}
              disabled={!urlsReady}
              aria-label={quality === "HQ" ? "Ganti ke sub stream (LQ)" : "Ganti ke main stream (HD)"}
              title={
                quality === "HQ"
                  ? "Kualitas tinggi (main stream, HD). Klik untuk ganti ke kualitas rendah (sub stream, LQ)"
                  : "Kualitas rendah (sub stream, LQ). Klik untuk ganti ke kualitas tinggi (main stream, HD)"
              }
              className="h-11 min-w-11 px-3 text-xs font-bold tracking-wide"
            >
              {quality}
            </Button>
            )}
            <Button
              variant="subtle"
              onClick={snapshot}
              disabled={!canSnapshot}
              aria-label="Ambil snapshot"
              title={canSnapshot ? "Ambil snapshot" : "Snapshot tersedia setelah video mulai bergambar"}
              className="h-11"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 20 20"
                fill="none"
                aria-hidden
              >
                <path
                  d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="hidden sm:inline">Snapshot</span>
            </Button>
            <button
              onClick={onClose}
              data-focus-close
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl text-slate-400 transition-colors duration-150 hover:bg-ink-700 hover:text-slate-200"
              aria-label="Tutup"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                aria-hidden
              >
                <path
                  d="M3 3l10 10M13 3L3 13"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </div>

        {/* Video */}
        <div
          ref={stageRef}
          onMouseEnter={() => setStageHovered(true)}
          onMouseLeave={() => setStageHovered(false)}
          onClick={() => setAdClickTick((t) => t + 1)}
          className={`nv-stage relative ${vRatio ? "" : "aspect-video"} bg-black ${cssRotate ? "nv-rot" : ""}`}
          style={vRatio ? { aspectRatio: vRatio } : undefined}
        >
          <div className="nv-rot-inner relative h-full w-full">
          {failed || !stream.is_online ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
              <svg
                width="32"
                height="32"
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
              <p className="text-sm font-medium text-slate-300">
                {stream.is_online ? "Gagal memutar stream" : "Kamera offline"}
              </p>
              <p className="text-xs text-slate-400">
                {stream.is_online
                  ? (failMsg ?? "Coba tutup dan buka kembali")
                  : "Kamera tidak terjangkau saat ini"}
              </p>
            </div>
          ) : (
            <>
              {/* Tombol layar penuh bawaan video dimatikan: di Android ia
                  memaksa landscape. Pakai kontrol sendiri (ikut rotasi HP,
                  putar manual lewat tombol). */}
              <video
                ref={videoRef}
                controls
                controlsList="nofullscreen"
                disablePictureInPicture
                playsInline
                onPlaying={() => setPlaying(true)}
                onLoadedMetadata={(e) => {
                  const v = e.currentTarget;
                  if (v.videoWidth && v.videoHeight) {
                    setVRati(`${v.videoWidth} / ${v.videoHeight}`);
                  }
                }}
                className="h-full w-full object-contain"
              />
              {/* Poster langsung tampil saat popup dibuka agar tidak hitam/
                  loading dulu; hilang begitu video mulai bergambar. */}
              {!playing &&
                (posterSrc ? (
                  <img
                    src={posterSrc}
                    alt={stream.name}
                    className="pointer-events-none absolute inset-0 h-full w-full object-contain"
                  />
                ) : (
                  <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                    <span className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/15 border-t-accent-400 motion-reduce:animate-none" />
                      Menghubungkan…
                    </span>
                  </div>
                ))}
              <div className="absolute right-2 top-2 flex gap-2">
                {/* Tombol LQ/HQ di panggung: terlihat saat layar penuh,
                    saat tombol kualitas di header tidak terlihat. Tanpa
                    sub stream tidak ada yang bisa diganti, sembunyikan. */}
                {fs && stream?.whep_sub_url && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleQuality();
                    }}
                    disabled={!urlsReady}
                    className={`flex h-11 min-w-11 items-center justify-center rounded-xl px-3 text-xs font-bold tracking-wide text-white transition active:scale-95 disabled:cursor-not-allowed disabled:opacity-50 ${quality === "HQ" ? "bg-accent-600 hover:bg-accent-500" : "bg-white/10 hover:bg-white/25"}`}
                    aria-label={quality === "HQ" ? "Ganti ke sub stream (LQ)" : "Ganti ke main stream (HD)"}
                    title={
                      quality === "HQ"
                        ? "Kualitas tinggi (main stream, HD). Klik untuk ganti ke kualitas rendah (sub stream, LQ)"
                        : "Kualitas rendah (sub stream, LQ). Klik untuk ganti ke kualitas tinggi (main stream, HD)"
                    }
                  >
                    {quality}
                  </button>
                )}
                {fs && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      rotate();
                    }}
                    className={`flex h-11 w-11 items-center justify-center rounded-xl text-white transition active:scale-95 ${rotated ? "bg-accent-400/30 hover:bg-accent-400/40" : "bg-white/10 hover:bg-white/25"}`}
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
                  className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 text-white transition hover:bg-white/25 active:scale-95"
                  aria-label={fs ? "Keluar layar penuh" : "Layar penuh"}
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
              </div>
            </>
          )}
          </div>
        </div>

        {/* Iklan di bawah video (di luar area 16:9), bukan overlay. */}
        {ad?.is_active && (
          <AdBanner
            config={ad}
            hovered={stageHovered}
            clickTick={adClickTick}
            placement="below"
          />
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-2.5 sm:px-5">
          <Badge tone={stream.is_online ? "ok" : "bad"}>
            {stream.is_online ? "Online" : "Offline"}
          </Badge>
          <span className="hidden text-xs text-slate-400 sm:block">
            Tekan ESC untuk menutup
          </span>
        </div>
      </div>
    </div>
  );
}
