"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../../lib/api";
import type { Group, Stream, SubnetHost } from "../../../lib/types";
import { ErrorBox, Modal, Switch } from "../../../components/ui";
import { LocationInput } from "../../../components/LocationInput";
import { NBBadge, NBButton, NBCard, NBField, NBInput, NBSelect, NBTitle, NBTableWrap, NBTh, NBTd, NBTr } from "../_nb";

type Tone = "ok" | "bad" | "warn" | "info" | "muted";
const SCAN_STATUS: Record<string, { label: string; tone: Tone }> = {
  video: { label: "Video", tone: "ok" },
  no_video: { label: "Tanpa video", tone: "warn" },
  /* Auth gagal di semua path (termasuk setelah deteksi kredensial
     cadangan): password yang diisi bukan password kamera — user perlu
     cek password, bukan kamera yang hilang. */
  auth_failed: { label: "Perlu cek password", tone: "bad" },
  not_found: { label: "Tidak ada", tone: "muted" },
  timeout: { label: "Timeout", tone: "muted" },
  error: { label: "Gagal", tone: "muted" },
  unreachable: { label: "Tidak terjangkau", tone: "muted" },
  /* Funnel 3 tahap: IP hidup tapi port RTSP tertutup (gagal tahap 2). */
  port_closed: { label: "Port RTSP tertutup", tone: "muted" },
};

type ScanJobStatus = {
  status: "running" | "done" | "error";
  scanned: number;
  total: number;
  hosts: SubnetHost[];
  candidates: { host: string; main_url: string }[];
  error: string | null;
  /* Progres funnel 3 tahap (dari GET job). */
  stage: "reachability" | "port_check" | "discovery" | "done";
  reachable_count: number;
  port_open_count: number;
};

const STAGE_LABEL: Record<ScanJobStatus["stage"], string> = {
  reachability: "Tahap 1/3 · Cek IP terjangkau",
  port_check: "Tahap 2/3 · Cek port RTSP",
  discovery: "Tahap 3/3 · Cek kamera",
  done: "Selesai",
};

/* Urutkan host secara numerik per IP supaya daftar live tidak
   meloncat-loncat mengikuti urutan selesainya tiap host. */
function sortHosts(hosts: SubnetHost[]): SubnetHost[] {
  const num = (h: SubnetHost) =>
    h.host.split(".").reduce((acc, n) => acc * 256 + (parseInt(n, 10) || 0), 0);
  return [...hosts].sort((a, b) => num(a) - num(b));
}

/* Info video main: resolusi + fps bila ada; bila tidak, path-nya.
   Kamera terdaftar (main sudah tersimpan di database): bila scan
   kali ini tidak menemukan video (mis. password tidak cocok saat
   scan, kamera flapping, timeout), tampilkan path main yang
   terdaftar supaya kolom Video tidak kosong. */
function mainInfo(h: SubnetHost): string {
  const p = h.paths.find((x) => x.role === "main");
  if (p?.width && p.height) {
    const parts = [`${p.width}×${p.height}`];
    if (p.fps) parts.push(`${p.fps} fps`);
    return parts.join(" · ");
  }
  return p?.path ?? urlPath(h.known_main);
}

/* Path main/sub SAJA (tanpa IP/user/password/port): kolom 'Path main'
   dan 'Path sub' hanya menampilkan path, mis. /Streaming/Channels/101.
   best_main/best_sub adalah URL LENGKAP (rtsp://user:pass@ip:port/...)
   dan tetap dipakai utuh saat menambah kamera — jangan ditampilkan
   di sini supaya kredensial tidak bocor ke layar.
   Kamera terdaftar: bila scan tidak menemukan path main/sub
   (video tidak terverifikasi kali ini), pakai path yang terdaftar
   di database supaya kolom tetap terisi; "-" hanya bila tidak ada
   sama sekali (kamera baru yang videonya tidak ketemu). */
function mainPath(h: SubnetHost): string {
  return (
    h.paths.find((x) => x.role === "main")?.path ||
    urlPath(h.known_main) ||
    "-"
  );
}

function subPath(h: SubnetHost): string {
  return (
    h.paths.find((x) => x.role === "sub")?.path ||
    urlPath(h.known_sub) ||
    "-"
  );
}

/* Info sub stream (role 'sub' dari klasifikasi pintar backend):
   resolusi + fps bila ada, atau path-nya bila tanpa info video
   (mis. jalur cepat kamera dikenal). Bila scan tidak menemukan sub,
   tampilkan path sub yang terdaftar seperti mainInfo di atas. */
function subInfo(h: SubnetHost): string {
  const p = h.paths.find((x) => x.role === "sub");
  if (p?.width && p.height) {
    const parts = [`${p.width}×${p.height}`];
    if (p.fps) parts.push(`${p.fps} fps`);
    return parts.join(" · ");
  }
  return p?.path ?? urlPath(h.known_sub);
}

/* Path (+ query) dari URL RTSP lengkap, tanpa kredensial/host/port.
   Dipakai membandingkan main terdaftar dengan main hasil scan. */
function urlPath(u: string | null | undefined): string {
  if (!u) return "";
  try {
    const p = new URL(u);
    return p.pathname + (p.search || "");
  } catch {
    return "";
  }
}

/* "Lengkapi stream" untuk kamera terdaftar: tawarkan HANYA stream
   yang belum ada di database (jangan buat kamera duplikat). */
function canAddMain(h: SubnetHost): boolean {
  return !!h.known && !h.known_main && !!h.best_main;
}
function canAddSub(h: SubnetHost): boolean {
  return !!h.known && !h.known_sub && !!h.best_sub;
}
function isComplete(h: SubnetHost): boolean {
  return !!h.known && !!h.known_main && !!h.known_sub;
}
/* Sub terdaftar beda path dengan sub hasil scan (untuk tombol
   "Sesuaikan path": ganti sub yang sudah ada supaya sama dengan
   hasil scan). */
function subDiffers(h: SubnetHost): boolean {
  if (!h.known_sub || !h.best_sub) return false;
  return urlPath(h.known_sub) !== urlPath(h.best_sub);
}
/* "Sesuaikan path" tampil bila kamera terdaftar punya main/sub yang
   path-nya BERBEDA dengan hasil scan (ada yang bisa diganti). Bila
   path sudah sama dengan scan, tidak ada yang disesuaikan. */
function canAdjust(h: SubnetHost): boolean {
  if (!h.known || (!h.best_main && !h.best_sub)) return false;
  return mainDiffers(h) || subDiffers(h);
}
/* Main terdaftar beda path dengan main hasil scan: tampilkan info
   perbandingan supaya user bisa memutuskan sendiri. Penggantian main
   yang sudah ada TIDAK otomatis, hanya info. */
function mainDiffers(h: SubnetHost): boolean {
  if (!h.known_main || !h.best_main) return false;
  return urlPath(h.known_main) !== urlPath(h.best_main);
}
function mainCompare(h: SubnetHost): string | null {
  if (!mainDiffers(h)) return null;
  const regPath = urlPath(h.known_main);
  const reg = h.paths.find((x) => x.path === regPath);
  const regRes =
    reg?.width && reg?.height ? ` (${reg.width}×${reg.height})` : "";
  const scan = h.paths.find((x) => x.role === "main");
  const scanRes =
    scan?.width && scan?.height ? ` (${scan.width}×${scan.height})` : "";
  return `Main terdaftar: ${regPath}${regRes} · scan: ${urlPath(h.best_main)}${scanRes}`;
}

/* Penanda cara kamera terdeteksi (perintah user 2026-11-14): kamera
   yang passwordnya kosong atau masih default pabrik tetap tampil dan
   bisa ditambah. "none"/"empty" = tanpa password / password kosong;
   "default" = terdeteksi dengan password default pabrik (bukan
   password yang diisi user). */
function authBadge(h: SubnetHost): { label: string; tone: Tone } | null {
  if (h.auth_mode === "none" || h.auth_mode === "empty")
    return { label: "Tanpa password", tone: "info" };
  if (h.auth_mode === "default")
    return { label: "Password default", tone: "warn" };
  return null;
}

/* Aturan password (perintah user 2026-11-14): aksi scan TIDAK PERNAH
   mengubah password. URL hasil scan hanya dipakai PATH-nya, jadi
   userinfo (user/password hasil scan, termasuk password default
   hasil deteksi) DIBUANG sebelum dikirim; backend menyisipkan kembali
   password tersimpan dari database. Ini supaya frontend tidak pernah
   mengirim password scan/default tanpa sengaja. */
function stripScanAuth(scanUrl: string): string {
  return scanUrl.replace(/^(\w+:\/\/)[^/]*@/, "$1");
}

export default function AdminScannerPage() {
  const [ipRange, setIpRange] = useState("192.168.1.0/24");
  const [port, setPort] = useState("554");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState({
    scanned: 0,
    total: 0,
    stage: "reachability" as ScanJobStatus["stage"],
    reachable: 0,
    portOpen: 0,
  });
  const [hosts, setHosts] = useState<SubnetHost[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(0);
  const [error, setError] = useState("");
  /* Popup pengaturan "Tambah terpilih": grup, penamaan, koordinat,
     mode penyimpanan. Dibuka dulu sebelum menambah, bukan langsung. */
  const [showAddModal, setShowAddModal] = useState(false);
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupPicked, setGroupPicked] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [namePrefix, setNamePrefix] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [storageMode, setStorageMode] = useState<"local" | "drive" | "both">("local");
  /* Kamera aktif + Simpan rekaman ke disk (perintah user 2026-11-14):
     saklar di popup "Tambah terpilih". Default kamera aktif ON.
     Saklar rekaman mengikuti mode penyimpanan (ON bila Lokal/Keduanya,
     OFF bila Drive saja) SELAMA user belum mengubahnya manual;
     setelah disentuh manual, pilihan user tidak ditimpa lagi. */
  const [isActive, setIsActive] = useState(true);
  const [recordingEnabled, setRecordingEnabled] = useState(true);
  const recTouchedRef = useRef(false);
  function onStorageModeChange(mode: "local" | "drive" | "both") {
    setStorageMode(mode);
    if (!recTouchedRef.current) {
      setRecordingEnabled(mode !== "drive");
    }
  }
  function onRecordToggle(v: boolean) {
    recTouchedRef.current = true;
    setRecordingEnabled(v);
  }
  const [modalError, setModalError] = useState("");
  /* Lengkapi stream kamera terdaftar (tambah main/sub yang belum ada). */
  const [completing, setCompleting] = useState<Set<string>>(new Set());
  const [completedMsg, setCompletedMsg] = useState("");
  /* Sesuaikan path kamera terdaftar dengan hasil scan (ganti main/sub
     yang sudah ada). Per kamera dan bulk; TIDAK ADA penerapan otomatis. */
  const [adjusting, setAdjusting] = useState<Set<string>>(new Set());
  const [adjustingBulk, setAdjustingBulk] = useState(false);
  const [adjustMsg, setAdjustMsg] = useState("");
  /* Stream yang sudah dilengkapi di sesi ini (kunci host -> main/sub
     yang berhasil ditambah). Polling scan menimpa state hosts tiap
     2 detik, jadi hasil lengkapi harus digabungkan kembali ke data
     polling supaya tombol tidak muncul lagi sesudah diklik. Disimpan
     di ref supaya loop polling selalu melihat nilai terbaru. */
  const completedStreamsRef = useRef<
    Record<string, { main: boolean; sub: boolean }>
  >({});
  /* Batalkan polling saat unmount supaya tidak setState sesudah lepas. */
  const cancelledRef = useRef(false);
  useEffect(() => {
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const key = (h: SubnetHost) => `${h.host}:${h.port}`;
  /* Host 'unreachable' (IP mati) TIDAK ditampilkan di daftar hasil:
     hanya noise saat scan /24. Jumlahnya tetap dihitung dan tampil di
     ringkasan sebagai "tidak terjangkau (disembunyikan)". API tetap
     mengembalikannya supaya hitungan funnel benar. */
  const visibleHosts = (hosts ?? []).filter(
    (h) => h.status !== "unreachable",
  );
  const hiddenUnreachable = (hosts ?? []).length - visibleHosts.length;
  /* Kamera yang sudah terdaftar tidak ditawarkan untuk ditambah lagi
     (cegah duplikat): hanya host video yang BELUM dikenal yang bisa
     dipilih untuk "Tambah terpilih". */
  const selectable = (hosts ?? []).filter(
    (h) => h.status === "video" && !h.known,
  );
  /* Semua host video bisa dicentang, termasuk yang sudah terdaftar:
     centang dipakai dua aksi yang berbeda, "Tambah terpilih" untuk
     kamera BARU dan "Sesuaikan terpilih" untuk kamera terdaftar
     (ganti path supaya sama dengan hasil scan). */
  const checkable = (hosts ?? []).filter((h) => h.status === "video");
  /* Kamera BARU yang tercentang (untuk "Tambah terpilih") dan kamera
     TERDAFTAR yang tercentang (untuk "Sesuaikan terpilih"). */
  const checkedNewHosts = () =>
    selectable.filter((h) => checked.has(key(h)));
  const checkedKnownHosts = () =>
    (hosts ?? []).filter(
      (h) => h.known && h.status === "video" && checked.has(key(h)),
    );

  async function doScan() {
    setError("");
    setScanning(true);
    setProgress({
      scanned: 0,
      total: 0,
      stage: "reachability",
      reachable: 0,
      portOpen: 0,
    });
    setHosts(null);
    setChecked(new Set());
    setAdded(0);
    try {
      /* Scan async: POST langsung kembalikan 202 + job_id, lalu polling
         status tiap 2 detik sampai done/error. Hasil parsial
         ditampilkan langsung selagi jalan (bukan hanya saat selesai). */
      const created = await api.post<{ job_id: string }>("/admin/scan-subnet", {
        ip_range: ipRange.trim(),
        port: parseInt(port, 10) || 554,
        username: username.trim(),
        password,
      });
      const jobId = created.job_id;
      for (;;) {
        await new Promise((r) => setTimeout(r, 2000));
        if (cancelledRef.current) return;
        const job = await api.get<ScanJobStatus>(
          `/admin/scan-subnet/${jobId}`,
        );
        if (cancelledRef.current) return;
        setProgress({
          scanned: job.scanned,
          total: job.total,
          stage: job.stage ?? "reachability",
          reachable: job.reachable_count ?? 0,
          portOpen: job.port_open_count ?? 0,
        });
        /* Hasil live: host yang sudah selesai langsung terlihat.
           Gabungkan stream yang sudah dilengkapi di sesi ini supaya
           polling tidak mengembalikan tombol yang sudah diklik. */
        setHosts(
          sortHosts(job.hosts ?? []).map((h) => {
            const done = completedStreamsRef.current[key(h)];
            if (!done) return h;
            return {
              ...h,
              known_main:
                done.main && h.best_main ? h.best_main : h.known_main,
              known_sub:
                done.sub && h.best_sub ? h.best_sub : h.known_sub,
            };
          }),
        );
        if (job.status === "done") {
          if (job.hosts.length === 0)
            setError("Tidak ada kamera ditemukan di subnet ini.");
          break;
        }
        if (job.status === "error") {
          setError(job.error ?? "Scan gagal");
          break;
        }
      }
    } catch (e) {
      if (!cancelledRef.current)
        setError(e instanceof ApiError ? e.message : "Scan gagal");
    } finally {
      if (!cancelledRef.current) setScanning(false);
    }
  }

  function toggle(h: SubnetHost) {
    const k = key(h);
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  function toggleAll() {
    /* Pilih semua host video (baru + terdaftar): "Tambah terpilih"
       hanya memproses yang baru, "Sesuaikan terpilih" hanya yang
       terdaftar, jadi satu centang aman untuk dua aksi. */
    if (checked.size === checkable.length) setChecked(new Set());
    else setChecked(new Set(checkable.map(key)));
  }

  /* Host terpilih (dipakai popup dan proses tambah). */
  const selectedHosts = () => selectable.filter((h) => checked.has(key(h)));

  /* Nama kamera hasil pengaturan popup: prefix + nomor urut (1, 2, ...)
     mengikuti urutan IP; bila prefix kosong, pakai "Kamera <host>". */
  function previewNames(selected: SubnetHost[]): string[] {
    const prefix = namePrefix.trim();
    if (!prefix) return selected.map((h) => `Kamera ${h.host}`);
    return selected.map((_, i) => `${prefix} ${i + 1}`);
  }

  /* Buka popup pengaturan dulu (bukan langsung menambah): muat daftar
     grup dari server (bukan hardcode); gagal dimuat bukan penghalang,
     user tetap bisa ketik grup baru. */
  function openAddModal() {
    if (selectedHosts().length === 0) return;
    setModalError("");
    /* Default segar tiap buka popup: kamera aktif ON, rekaman mengikuti
       mode penyimpanan saat ini, pilihan manual sebelumnya direset. */
    setIsActive(true);
    recTouchedRef.current = false;
    setRecordingEnabled(storageMode !== "drive");
    setShowAddModal(true);
    api.get<Group[]>("/admin/groups").then(setGroups).catch(() => {});
  }

  /* Validasi koordinat: kosong berarti tanpa koordinat; bila diisi
     harus angka dalam rentang latitude -90..90, longitude -180..180. */
  function coordError(): string {
    if (lat.trim() !== "") {
      const v = Number(lat);
      if (!Number.isFinite(v) || v < -90 || v > 90)
        return "Latitude harus angka antara -90 dan 90.";
    }
    if (lng.trim() !== "") {
      const v = Number(lng);
      if (!Number.isFinite(v) || v < -180 || v > 180)
        return "Longitude harus angka antara -180 dan 180.";
    }
    return "";
  }

  async function confirmAdd() {
    const selected = selectedHosts();
    if (selected.length === 0) return;
    const NEW_GROUP = "__baru__";
    const groupName =
      groupPicked === NEW_GROUP ? newGroupName.trim() : groupPicked;
    if (groupPicked === NEW_GROUP && groupName === "") {
      setModalError("Isi nama grup baru.");
      return;
    }
    const cErr = coordError();
    if (cErr) {
      setModalError(cErr);
      return;
    }
    setModalError("");
    setError("");
    setAdding(true);
    setShowAddModal(false);
    const names = previewNames(selected);
    const latitude = lat.trim() === "" ? null : Number(lat);
    const longitude = lng.trim() === "" ? null : Number(lng);
    let ok = 0;
    /* E-S5: jangan berhenti di kegagalan pertama, lanjutkan sisanya
       dan laporkan mana yang gagal. */
    const failed: string[] = [];
    const failedKeys = new Set<string>();
    const createdIds: number[] = [];
    for (let i = 0; i < selected.length; i++) {
      const h = selected[i];
      try {
        // force: path sudah diverifikasi video saat scan.
        // sub_url: best_sub hasil scan bila ada (bukan turunan resolver).
        const created = await api.post<Stream>("/admin/streams", {
          name: names[i],
          rtsp_url: h.best_main,
          sub_url: h.best_sub ?? null,
          storage_mode: storageMode,
          is_active: isActive,
          recording_enabled: recordingEnabled,
          latitude,
          longitude,
          force: true,
        });
        createdIds.push(created.id);
        ok++;
      } catch {
        failed.push(h.host);
        failedKeys.add(key(h));
      }
    }
    /* Grup (bila dipilih): buat dulu bila grup baru, lalu gabungkan
       kamera baru ke anggota yang sudah ada (POST camera-grants
       mengganti seluruh anggota, jadi jangan timpa). */
    let groupFailed = false;
    if (groupName !== "" && createdIds.length > 0) {
      try {
        if (!groups.some((g) => g.name === groupName)) {
          await api.put(`/admin/groups/${encodeURIComponent(groupName)}`, {
            name: groupName,
            description: null,
          });
        }
        let current: number[] = [];
        try {
          const r = await api.get<{ stream_ids: number[] }>(
            `/admin/groups/${encodeURIComponent(groupName)}/camera-grants`,
          );
          current = r.stream_ids;
        } catch {
          /* grup baru: mulai dari kosong */
        }
        const merged = [...new Set([...current, ...createdIds])];
        await api.post(
          `/admin/groups/${encodeURIComponent(groupName)}/camera-grants`,
          { stream_ids: merged },
        );
      } catch {
        groupFailed = true;
      }
    }
    const msgs: string[] = [];
    if (failed.length > 0) {
      msgs.push(
        `Gagal menambah ${failed.length} kamera: ${failed.join(", ")}.`,
      );
    }
    if (groupFailed) {
      msgs.push(
        `Kamera berhasil ditambahkan tapi gagal dimasukkan ke grup ${groupName}.`,
      );
    }
    if (msgs.length > 0) {
      setError(`${msgs.join(" ")} ${ok} kamera berhasil ditambahkan.`);
    }
    setAdded(ok);
    /* Reset checked supaya klik kedua tidak membuat duplikat; bila
       ada yang gagal, hanya yang gagal yang tetap tercentang. */
    setChecked(failedKeys);
    setAdding(false);
  }

  /* Lengkapi stream kamera terdaftar: tambah HANYA main/sub yang
     belum ada di database (endpoint hanya mengisi field kosong,
     tidak menimpa yang sudah terisi). Setelah berhasil, state lokal
     diperbarui supaya tombol hilang / jadi "Sudah lengkap". */
  async function completeHost(h: SubnetHost, which: "main" | "sub" | "both") {
    if (!h.known_stream_id) return;
    const k = key(h);
    setError("");
    setCompletedMsg("");
    setCompleting((prev) => new Set(prev).add(k));
    try {
      const body: {
        stream_id: number;
        main_url?: string | null;
        sub_url?: string | null;
      } = { stream_id: h.known_stream_id };
      if ((which === "main" || which === "both") && h.best_main)
        body.main_url = stripScanAuth(h.best_main);
      if ((which === "sub" || which === "both") && h.best_sub)
        body.sub_url = stripScanAuth(h.best_sub);
      const res = await api.post<{
        updated_main: boolean;
        updated_sub: boolean;
      }>("/admin/scan-subnet/complete-streams", body);
      /* Catat di ref supaya polling berikutnya tidak mengembalikan
         tombol yang sudah diklik. */
      const prev = completedStreamsRef.current[k] ?? {
        main: false,
        sub: false,
      };
      completedStreamsRef.current[k] = {
        main: prev.main || res.updated_main,
        sub: prev.sub || res.updated_sub,
      };
      setHosts((prev) =>
        (prev ?? []).map((x) => {
          if (key(x) !== k) return x;
          return {
            ...x,
            known_main:
              res.updated_main && h.best_main ? h.best_main : x.known_main,
            known_sub:
              res.updated_sub && h.best_sub ? h.best_sub : x.known_sub,
          };
        }),
      );
      const parts: string[] = [];
      if (res.updated_main) parts.push("mainstream");
      if (res.updated_sub) parts.push("substream");
      if (parts.length > 0)
        setCompletedMsg(`Kamera ${h.host}: ${parts.join(" + ")} ditambahkan.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal melengkapi stream");
    } finally {
      setCompleting((prev) => {
        const next = new Set(prev);
        next.delete(k);
        return next;
      });
    }
  }

  /* Sesuaikan path kamera terdaftar dengan hasil scan (tombol
     "Sesuaikan path" per host dan "Sesuaikan terpilih" bulk).
     BERBEDA dengan "Lengkapi stream" yang hanya mengisi field kosong:
     ini MENIMPA main_url dan sub_url dengan best_main/best_sub hasil
     scan (bila ada di hasil scan; field yang tidak ada di hasil scan
     TIDAK diubah). Contoh: main /H.264 diganti ke /live/0/MAIN, sub
     diganti ke /live/0/SUB. TIDAK ADA penerapan otomatis: hanya jalan
     bila user mengklik tombol. */
  async function adjustHost(h: SubnetHost) {
    if (!h.known_stream_id) return;
    const k = key(h);
    setError("");
    setAdjustMsg("");
    setAdjusting((prev) => new Set(prev).add(k));
    try {
      const body: {
        stream_id: number;
        main_url?: string | null;
        sub_url?: string | null;
        replace: boolean;
      } = { stream_id: h.known_stream_id, replace: true };
      if (h.best_main) body.main_url = stripScanAuth(h.best_main);
      if (h.best_sub) body.sub_url = stripScanAuth(h.best_sub);
      const res = await api.post<{
        updated_main: boolean;
        updated_sub: boolean;
      }>("/admin/scan-subnet/complete-streams", body);
      const prev = completedStreamsRef.current[k] ?? {
        main: false,
        sub: false,
      };
      completedStreamsRef.current[k] = {
        main: prev.main || res.updated_main,
        sub: prev.sub || res.updated_sub,
      };
      setHosts((prevHosts) =>
        (prevHosts ?? []).map((x) => {
          if (key(x) !== k) return x;
          return {
            ...x,
            known_main:
              res.updated_main && h.best_main ? h.best_main : x.known_main,
            known_sub:
              res.updated_sub && h.best_sub ? h.best_sub : x.known_sub,
          };
        }),
      );
      const parts: string[] = [];
      if (res.updated_main) parts.push("main");
      if (res.updated_sub) parts.push("sub");
      setCompletedMsg(
        parts.length > 0
          ? `Kamera ${h.host}: ${parts.join(" dan ")} disesuaikan.`
          : `Kamera ${h.host}: sudah sesuai hasil scan.`,
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyesuaikan path");
    } finally {
      setAdjusting((prev) => {
        const next = new Set(prev);
        next.delete(k);
        return next;
      });
    }
  }

  /* Sesuaikan path SEMUA kamera terdaftar yang tercentang, satu per
     satu; lanjutkan bila satu gagal, laporkan mana yang berhasil dan
     mana yang gagal. Yang gagal tetap tercentang supaya bisa dicoba
     lagi; yang berhasil dicentang-nya dilepas. */
  async function adjustSelected() {
    const targets = checkedKnownHosts();
    if (targets.length === 0) return;
    setError("");
    setAdjustMsg("");
    setAdjustingBulk(true);
    let ok = 0;
    const failed: string[] = [];
    const failedKeys = new Set<string>();
    for (const h of targets) {
      if (!h.known_stream_id) continue;
      try {
        const body: {
          stream_id: number;
          main_url?: string | null;
          sub_url?: string | null;
          replace: boolean;
        } = { stream_id: h.known_stream_id, replace: true };
        if (h.best_main) body.main_url = stripScanAuth(h.best_main);
        if (h.best_sub) body.sub_url = stripScanAuth(h.best_sub);
        const res = await api.post<{
          updated_main: boolean;
          updated_sub: boolean;
        }>("/admin/scan-subnet/complete-streams", body);
        const k = key(h);
        const prev = completedStreamsRef.current[k] ?? {
          main: false,
          sub: false,
        };
        completedStreamsRef.current[k] = {
          main: prev.main || res.updated_main,
          sub: prev.sub || res.updated_sub,
        };
        setHosts((prevHosts) =>
          (prevHosts ?? []).map((x) => {
            if (key(x) !== k) return x;
            return {
              ...x,
              known_main:
                res.updated_main && h.best_main ? h.best_main : x.known_main,
              known_sub:
                res.updated_sub && h.best_sub ? h.best_sub : x.known_sub,
            };
          }),
        );
        ok++;
      } catch {
        failed.push(h.host);
        failedKeys.add(key(h));
      }
    }
    setAdjustingBulk(false);
    setChecked((prev) => {
      const next = new Set<string>();
      prev.forEach((k) => {
        if (failedKeys.has(k)) next.add(k);
      });
      return next;
    });
    setAdjustMsg(
      failed.length > 0
        ? `Disesuaikan ${ok} kamera, gagal ${failed.length}: ${failed.join(", ")}.`
        : `Disesuaikan ${ok} kamera.`,
    );
  }

  /* Tombol lengkapi untuk satu host terdaftar (dipakai kartu mobile
     dan baris tabel desktop). Mengembalikan null bila tidak ada
     stream yang perlu dilengkapi; lencana "Sudah lengkap" ditangani
     KnownHostActions di bawah. */
  function CompleteButton({ h }: { h: SubnetHost }) {
    const busy = completing.has(key(h));
    const both = canAddMain(h) && canAddSub(h);
    const label = both
      ? "Lengkapi stream"
      : canAddSub(h)
        ? "Tambah substream"
        : canAddMain(h)
          ? "Tambah mainstream"
          : null;
    if (!label) return null;
    return (
      <NBButton
        variant="secondary"
        onClick={() =>
          completeHost(h, both ? "both" : canAddSub(h) ? "sub" : "main")
        }
        /* Tombol tetap aktif selagi scan berjalan: hasil lengkapi
           digabungkan kembali ke data polling (completedStreamsRef),
           jadi tidak tertimpa. Hanya nonaktif saat sedang menambah. */
        disabled={busy}
        className="min-h-11 px-3 text-xs"
      >
        {busy ? "Menambah…" : label}
      </NBButton>
    );
  }

  /* Tombol "Sesuaikan path" untuk satu host terdaftar: GANTI main_url
     dan sub_url dengan best_main/best_sub hasil scan (bila ada di
     hasil scan; yang tidak ada tidak diubah). Berbeda dengan lengkapi
     yang hanya mengisi field kosong, ini menimpa path yang sudah ada
     supaya sama dengan hasil scan. */
  function AdjustButton({ h }: { h: SubnetHost }) {
    const busy = adjusting.has(key(h));
    if (!canAdjust(h)) return null;
    return (
      <NBButton
        variant="secondary"
        onClick={() => adjustHost(h)}
        disabled={busy}
        className="min-h-11 px-3 text-xs"
        title="Ganti main dan sub dengan hasil scan"
      >
        {busy ? "Menyesuaikan…" : "Sesuaikan path"}
      </NBButton>
    );
  }

  /* Aksi untuk satu host terdaftar di kolom AKSI: tombol lengkapi
     (bila ada stream yang belum ada) dan/atau tombol sesuaikan path
     (bila path terdaftar berbeda dengan hasil scan). Bila keduanya
     tidak perlu, tampilkan lencana "Sudah lengkap". */
  function KnownHostActions({ h }: { h: SubnetHost }) {
    const needsComplete = canAddMain(h) || canAddSub(h);
    const needsAdjust = canAdjust(h);
    if (!needsComplete && !needsAdjust)
      return <NBBadge tone="ok">Sudah lengkap</NBBadge>;
    return (
      <span className="flex flex-col gap-1.5">
        {needsComplete && <CompleteButton h={h} />}
        {needsAdjust && <AdjustButton h={h} />}
      </span>
    );
  }

  /* E-R5: dua komponen terpisah supaya HTML valid: kartu <li>
     hanya di dalam <ul> mobile, baris <tr> hanya di <tbody>. */
  function HostCheckbox({ h }: { h: SubnetHost }) {
    /* Semua host video bisa dicentang, termasuk yang sudah terdaftar:
       "Tambah terpilih" hanya memproses yang BARU (selectable), dan
       "Sesuaikan terpilih" hanya memproses yang TERDAFTAR, jadi satu
       centang aman untuk dua aksi. */
    const canPick = h.status === "video";
    return (
      <input
        type="checkbox"
        checked={checked.has(key(h))}
        onChange={() => toggle(h)}
        disabled={!canPick}
        className="h-5 w-5 shrink-0 accent-accent-500 disabled:opacity-40"
        aria-label={`Pilih ${h.host}`}
      />
    );
  }

  function HostCard({ h }: { h: SubnetHost }) {
    const st = SCAN_STATUS[h.status] ?? SCAN_STATUS.error;
    const compare = mainCompare(h);
    const auth = authBadge(h);
    return (
      <li className="flex items-center gap-3 rounded-xl bg-ink-900 shadow-sm p-3 md:hidden">
        <HostCheckbox h={h} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-sm text-white">
            {h.host}:{h.port}
          </p>
          <p className="mt-0.5 truncate text-xs text-slate-400">
            {h.best_main || h.known_main
              ? `Main: ${mainInfo(h)}`
              : "tanpa video"}
          </p>
          {(h.best_sub || h.known_sub) && (
            <p className="mt-0.5 truncate text-xs text-slate-400">
              Sub: {subInfo(h)}
            </p>
          )}
          {compare && (
            <p className="mt-0.5 text-xs leading-relaxed text-warn-300">
              {compare}
            </p>
          )}
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <NBBadge tone={st.tone}>{st.label}</NBBadge>
            {auth && <NBBadge tone={auth.tone}>{auth.label}</NBBadge>}
            {h.known && <NBBadge tone="info">Sudah terdaftar</NBBadge>}
          </div>
          {h.known && (
            <div className="mt-2">
              <KnownHostActions h={h} />
            </div>
          )}
        </div>
      </li>
    );
  }

  function HostRow({ h }: { h: SubnetHost }) {
    const st = SCAN_STATUS[h.status] ?? SCAN_STATUS.error;
    const compare = mainCompare(h);
    const auth = authBadge(h);
    return (
      <NBTr className="hidden md:table-row">
        <NBTd>
          <HostCheckbox h={h} />
        </NBTd>
        <NBTd className="font-mono">{h.host}</NBTd>
        <NBTd className="font-mono">{h.port}</NBTd>
        <NBTd>
          <span className="flex flex-wrap items-center gap-1.5">
            <NBBadge tone={st.tone}>{st.label}</NBBadge>
            {auth && <NBBadge tone={auth.tone}>{auth.label}</NBBadge>}
            {h.known && <NBBadge tone="info">Sudah terdaftar</NBBadge>}
          </span>
        </NBTd>
        <NBTd className="max-w-[280px] truncate font-mono text-xs">
          {mainPath(h)}
        </NBTd>
        <NBTd className="max-w-[280px] truncate font-mono text-xs">
          {subPath(h)}
        </NBTd>
        <NBTd className="text-xs">
          {(h.best_main || h.known_main) && (
            <span className="block leading-relaxed">
              <span className="block">Main: {mainInfo(h)}</span>
              {(h.best_sub || h.known_sub) && (
                <span className="block text-slate-400">
                  Sub: {subInfo(h)}
                </span>
              )}
              {compare && (
                <span className="block text-warn-300">{compare}</span>
              )}
            </span>
          )}
        </NBTd>
        <NBTd>
          {h.known ? <KnownHostActions h={h} /> : <span className="text-slate-600">-</span>}
        </NBTd>
      </NBTr>
    );
  }

  return (
    <div>
      <NBTitle
        title="Camera Scanner"
        desc="Pindai subnet jaringan lokal untuk menemukan kamera (maks 256 host)"
      />
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      <NBCard className="mb-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          <NBField label="IP Subnet (CIDR)" hint="cth: 192.168.1.0/24">
            <NBInput
              value={ipRange}
              onChange={(e) => setIpRange(e.target.value)}
              placeholder="192.168.1.0/24"
              className="font-mono"
            />
          </NBField>
          <NBField label="Port RTSP">
            <NBInput
              value={port}
              onChange={(e) => setPort(e.target.value)}
              inputMode="numeric"
              className="font-mono"
            />
          </NBField>
          <NBField label="Username">
            <NBInput
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
            />
          </NBField>
          <NBField label="Password">
            <NBInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
          </NBField>
          {/* Sel tombol sejajar kotak input: pelabel tak terlihat setinggi
              label field, supaya tombol tidak turun mengikuti hint di
              bawah field IP Subnet. */}
          <div className="flex flex-col">
            <span
              className="mb-1.5 block text-sm font-semibold invisible select-none"
              aria-hidden="true"
            >
              Aksi
            </span>
            <NBButton onClick={doScan} disabled={scanning} className="w-full sm:w-auto">
              {scanning ? "Memindai…" : "Scan Network"}
            </NBButton>
          </div>
        </div>

        {scanning && (
          <div className="mt-5 space-y-2 border-t border-ink-800 pt-4">
            <div className="flex flex-wrap justify-between gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <span>{STAGE_LABEL[progress.stage]}</span>
              <span>
                Memindai {progress.scanned} dari {progress.total} host
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-ink-700">
              <div
                className="h-full rounded-full bg-accent-500 transition-all duration-500"
                style={{
                  width: `${
                    progress.total > 0
                      ? Math.round((progress.scanned / progress.total) * 100)
                      : 0
                  }%`,
                }}
              />
            </div>
            <p className="text-xs text-slate-400">
              {progress.reachable} IP terjangkau
              {progress.stage !== "reachability" &&
                ` · ${progress.portOpen} port RTSP terbuka`}
              {progress.stage === "done" &&
                ` · ${selectable.length} kamera baru dengan video`}
            </p>
          </div>
        )}
      </NBCard>

      {hosts !== null && (
        <NBCard>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-white">
              Host terdeteksi{" "}
              <span className="text-slate-400">({visibleHosts.length})</span>
            </h3>
            {/* Dua aksi untuk yang tercentang, dibedakan jelas:
                "Tambah terpilih" hanya menambah kamera BARU, sedangkan
                "Sesuaikan terpilih" hanya mengganti path kamera yang
                SUDAH TERDAFTAR supaya sama dengan hasil scan. */}
            <span className="flex flex-wrap gap-2">
              {selectable.length > 0 && (
                <NBButton
                  variant="secondary"
                  onClick={openAddModal}
                  disabled={
                    scanning || adding || checkedNewHosts().length === 0
                  }
                >
                  {adding
                    ? "Menambah…"
                    : `+ Tambah terpilih (${checkedNewHosts().length})`}
                </NBButton>
              )}
              {(hosts ?? []).some((h) => h.known && h.status === "video") && (
                <NBButton
                  variant="secondary"
                  onClick={adjustSelected}
                  disabled={
                    scanning ||
                    adjustingBulk ||
                    checkedKnownHosts().length === 0
                  }
                  title="Ganti main dan sub kamera terdaftar yang tercentang dengan hasil scan"
                >
                  {adjustingBulk
                    ? "Menyesuaikan…"
                    : `Sesuaikan terpilih (${checkedKnownHosts().length})`}
                </NBButton>
              )}
            </span>
          </div>
          {!scanning && visibleHosts.length > 0 && (
            <p className="mb-3 text-xs text-slate-400">
              {progress.reachable} IP terjangkau · {progress.portOpen}{" "}
              port RTSP terbuka ·{" "}
              {visibleHosts.filter((h) => h.status === "video").length} dengan
              video
              {visibleHosts.some((h) => h.known) &&
                ` · ${visibleHosts.filter((h) => h.known).length} sudah terdaftar`}
              {hiddenUnreachable > 0 &&
                ` · ${hiddenUnreachable} tidak terjangkau (disembunyikan)`}
            </p>
          )}
          {added > 0 && (
            <p className="mb-3 text-sm text-ok-400">
              {added} kamera berhasil ditambahkan. Lihat di tab Kamera.
            </p>
          )}
          {completedMsg && (
            <p className="mb-3 text-sm text-ok-400">{completedMsg}</p>
          )}
          {adjustMsg && (
            <p className="mb-3 text-sm text-ok-400">{adjustMsg}</p>
          )}
          {visibleHosts.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
              {scanning
                ? "Memindai… hasil muncul di sini begitu ditemukan."
                : `Tidak ada kamera yang merespons di subnet ini.${
                    hiddenUnreachable > 0
                      ? ` (${hiddenUnreachable} IP tidak terjangkau, disembunyikan.)`
                      : ""
                  }`}
            </p>
          ) : (
            <>
              {/* Mobile: pilih semua + daftar kartu */}
              {checkable.length > 0 && (
                <label className="mb-2 flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-300 md:hidden">
                  <input
                    type="checkbox"
                    checked={checked.size === checkable.length}
                    onChange={toggleAll}
                    className="h-5 w-5 accent-accent-500"
                    aria-label="Pilih semua"
                  />
                  Pilih semua
                </label>
              )}
              <ul className="space-y-2 md:hidden">
                {visibleHosts.map((h) => (
                  <HostCard key={key(h)} h={h} />
                ))}
              </ul>
              {/* Desktop: tabel */}
              <div className="hidden md:block">
                <NBTableWrap>
                <table className="w-full text-left text-sm">
                  <thead>
                    <NBTr>
                      <NBTh className="w-10">
                        <input
                          type="checkbox"
                          checked={
                            checkable.length > 0 &&
                            checked.size === checkable.length
                          }
                          onChange={toggleAll}
                          className="h-5 w-5 accent-accent-500"
                          aria-label="Pilih semua"
                        />
                      </NBTh>
                      <NBTh>IP</NBTh>
                      <NBTh>Port</NBTh>
                      <NBTh>Status</NBTh>
                      <NBTh>Path main</NBTh>
                      <NBTh>Path sub</NBTh>
                      <NBTh>Video</NBTh>
                      <NBTh>Aksi</NBTh>
                    </NBTr>
                  </thead>
                  <tbody>
                    {visibleHosts.map((h) => (
                      <HostRow key={key(h)} h={h} />
                    ))}
                  </tbody>
                </table>
                </NBTableWrap>
              </div>
            </>
          )}
        </NBCard>
      )}
      {hosts === null && !scanning && !error && (
        <p className="py-10 text-center text-sm text-slate-400">
          Isi subnet lalu tekan “Scan Network” untuk mulai memindai.
        </p>
      )}

      {/* Popup pengaturan "Tambah terpilih": grup, penamaan, koordinat,
          mode penyimpanan. Modal bersama (bottom sheet di mobile,
          terpusat di desktop). */}
      {showAddModal && (
        <Modal
          title={`Tambah ${selectedHosts().length} kamera`}
          onClose={() => setShowAddModal(false)}
        >
          <div className="space-y-4">
            <NBField label={`Kamera terpilih (${selectedHosts().length})`}>
              <div className="max-h-32 overflow-y-auto rounded-xl bg-ink-800 p-2">
                {selectedHosts().map((h) => (
                  <p
                    key={key(h)}
                    className="truncate px-2 py-1 font-mono text-sm text-slate-200"
                  >
                    {h.host}:{h.port}
                    {h.best_sub && (
                      <span className="text-slate-400"> · sub ada</span>
                    )}
                  </p>
                ))}
              </div>
              <p className="mt-2 text-xs leading-relaxed text-slate-400">
                {selectedHosts().filter((h) => h.best_sub).length} dari{" "}
                {selectedHosts().length} kamera punya substream, akan
                disimpan sebagai sub.
              </p>
            </NBField>

            {/* Penanda deteksi kredensial (perintah user 2026-11-14):
                kamera tanpa password / password default tetap bisa
                ditambah. Bila ada yang terdeteksi password default,
                tampilkan peringatan: password default itu akan
                disimpan bersama kamera bila Simpan diklik (klik
                Simpan = konfirmasi user). Sebaiknya ganti password
                kamera setelah ditambah. */}
            {selectedHosts().some((h) => h.auth_mode === "default") && (
              <div className="rounded-xl bg-warn-500/10 p-3 text-xs leading-relaxed text-warn-200">
                {selectedHosts().filter((h) => h.auth_mode === "default").length}{" "}
                kamera terdeteksi memakai password default pabrik (bukan
                password yang diisi saat scan). Password default itu akan
                disimpan bersama kamera bila Simpan diklik. Sebaiknya
                ganti password kamera setelah ditambah.
              </div>
            )}
            {selectedHosts().some(
              (h) => h.auth_mode === "none" || h.auth_mode === "empty",
            ) && (
              <p className="text-xs leading-relaxed text-slate-400">
                {selectedHosts().filter(
                  (h) => h.auth_mode === "none" || h.auth_mode === "empty",
                ).length}{" "}
                kamera terdeteksi tanpa password (atau password kosong) dan
                akan ditambah tanpa password.
              </p>
            )}

            <NBField
              label="Grup"
              hint="Diterapkan ke semua kamera terpilih. Kosongkan untuk tanpa grup."
            >
              <NBSelect
                value={groupPicked}
                onChange={(e) => setGroupPicked(e.target.value)}
              >
                <option value="">Tanpa grup</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.name}>
                    {g.name}
                  </option>
                ))}
                <option value="__baru__">+ Grup baru…</option>
              </NBSelect>
            </NBField>
            {groupPicked === "__baru__" && (
              <NBField label="Nama grup baru">
                <NBInput
                  value={newGroupName}
                  onChange={(e) => setNewGroupName(e.target.value)}
                  placeholder="cth. Lantai 1"
                />
              </NBField>
            )}

            <NBField
              label="Nama kamera"
              hint="Prefix + nomor urut otomatis. Kosongkan untuk memakai nama default."
            >
              <NBInput
                value={namePrefix}
                onChange={(e) => setNamePrefix(e.target.value)}
                placeholder="cth. MIM MRI"
              />
              <p className="mt-2 text-xs leading-relaxed text-slate-400">
                Contoh:{" "}
                {previewNames(selectedHosts()).slice(0, 3).join(", ")}
                {selectedHosts().length > 3 &&
                  `, … (${selectedHosts().length} kamera)`}
              </p>
            </NBField>

            <div className="mb-3">
              <LocationInput
                lat={lat}
                lng={lng}
                onChange={(la, lo) => {
                  setLat(la);
                  setLng(lo);
                }}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <NBField label="Latitude" hint="-90 s.d. 90">
                <NBInput
                  value={lat}
                  onChange={(e) => setLat(e.target.value)}
                  inputMode="decimal"
                  placeholder="cth. -7,56"
                  className="font-mono"
                />
              </NBField>
              <NBField label="Longitude" hint="-180 s.d. 180">
                <NBInput
                  value={lng}
                  onChange={(e) => setLng(e.target.value)}
                  inputMode="decimal"
                  placeholder="cth. 110,83"
                  className="font-mono"
                />
              </NBField>
            </div>
            <p className="-mt-2 text-xs leading-relaxed text-slate-400">
              Kosongkan bila tanpa koordinat. Berlaku untuk semua kamera
              terpilih.
            </p>

            <NBField label="Mode penyimpanan">
              <NBSelect
                value={storageMode}
                onChange={(e) =>
                  onStorageModeChange(
                    e.target.value as "local" | "drive" | "both",
                  )
                }
              >
                <option value="local">Lokal</option>
                <option value="drive">Google Drive</option>
                <option value="both">Keduanya</option>
              </NBSelect>
            </NBField>

            {/* Kamera aktif + Penyimpanan rekaman (perintah user
                2026-11-14): saklar Switch bersama, bukan checkbox.
                "Simpan rekaman ke disk" bisa di-disable/enable;
                default-nya mengikuti mode penyimpanan sampai user
                mengubahnya manual (lihat onStorageModeChange). */}
            <div className="space-y-4 border-t border-ink-800 pt-5">
              <p className="text-[13px] font-medium text-slate-400">
                Kamera & rekaman
              </p>
              <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 text-sm text-slate-300">
                <span>Kamera aktif</span>
                <Switch
                  checked={isActive}
                  onChange={setIsActive}
                  label="Kamera aktif"
                />
              </label>
              <p className="-mt-2 text-xs leading-relaxed text-slate-400">
                Bila dimatikan, kamera ditambah dalam keadaan nonaktif dan
                tidak langsung streaming.
              </p>
              <p className="text-[13px] font-medium text-slate-400">
                Penyimpanan rekaman
              </p>
              <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 text-sm text-slate-300">
                <span>Simpan rekaman ke disk</span>
                <Switch
                  checked={recordingEnabled}
                  onChange={onRecordToggle}
                  label="Simpan rekaman ke disk"
                />
              </label>
              <p className="-mt-2 text-xs leading-relaxed text-slate-400">
                Bila dimatikan, kamera tetap streaming live tapi tidak
                merekam ke disk.
              </p>
            </div>

            {modalError && (
              <ErrorBox message={modalError} />
            )}
            <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:justify-end">
              <NBButton
                variant="secondary"
                onClick={() => setShowAddModal(false)}
                disabled={adding}
                className="h-12 w-full sm:w-auto"
              >
                Batal
              </NBButton>
              <NBButton
                onClick={confirmAdd}
                disabled={adding}
                className="h-12 w-full sm:w-auto"
              >
                {adding
                  ? "Menambah…"
                  : `Simpan (${selectedHosts().length} kamera)`}
              </NBButton>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
