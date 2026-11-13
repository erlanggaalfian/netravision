"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import type * as LType from "leaflet";
import { AppShell } from "../../components/AppShell";
import { FocusModal } from "../../components/FocusModal";
import { Button, Card, ErrorBox, SectionTitle } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import type { Stream } from "../../lib/types";

/* Peta kamera (Leaflet, client-only, aman untuk static export).
   Marker: hijau = online, merah = offline.
   Admin bisa drag marker → PUT /api/admin/streams/{id} {latitude, longitude}. */

const DEFAULT_CENTER: [number, number] = [-2.5, 118];
const DEFAULT_ZOOM = 5;

function markerIcon(L: typeof LType, online: boolean): LType.DivIcon {
  const color = online ? "var(--nv-ok-400)" : "var(--nv-bad-400)";
  const size = L.Browser.touch ? 28 : 20; // lebih besar di layar sentuh
  const hit = 44; // area sentuh minimum 44px, titik visual tetap di tengah
  const half = hit / 2;
  return L.divIcon({
    className: "nv-marker",
    html: `<span style="display:flex;width:${hit}px;height:${hit}px;align-items:center;justify-content:center"><span style="display:block;width:${size}px;height:${size}px;border-radius:9999px;background:${color};border:3px solid var(--nv-ink-950);box-shadow:0 0 0 2px ${color}, 0 2px 8px rgba(0,0,0,.55)"></span></span>`,
    iconSize: [hit, hit],
    iconAnchor: [half, half],
    popupAnchor: [0, -half - 1],
  });
}

/* Ikon klaster: lingkaran berisi jumlah kamera di titik itu. Saat zoom
   out, kamera yang lokasinya berdekatan digabung jadi satu titik ini;
   saat zoom in, klaster pecah kembali jadi marker tunggal.
   Warna mengikuti status kamera di dalamnya: hijau bila semua nyala,
   merah bila semua mati, kuning bila ada yang mati (campuran). */
type ClusterStatus = "ok" | "bad" | "warn";
function clusterIcon(
  L: typeof LType,
  count: number,
  status: ClusterStatus = "ok",
): LType.DivIcon {
  return L.divIcon({
    html: `<span class="nv-cluster-num">${count}</span>`,
    className: `nv-cluster nv-cluster-${status}`,
    iconSize: [44, 44],
    iconAnchor: [22, 22],
  });
}

/* Isi popup marker sebagai React (bukan template string HTML). */
function MarkerPopup({
  s,
  onClose,
  onLive,
  isSuperAdmin,
  editing,
  pendingCoords,
  onEditLocation,
  onSaveLocation,
  onCancelLocation,
}: {
  s: Stream;
  onClose: () => void;
  onLive: () => void;
  isSuperAdmin: boolean;
  editing: boolean;
  pendingCoords: string | null;
  onEditLocation: () => void;
  onSaveLocation: () => void;
  onCancelLocation: () => void;
}) {
  const coords =
    s.latitude != null && s.longitude != null
      ? `${s.latitude.toFixed(5)}, ${s.longitude.toFixed(5)}`
      : null;
  return (
    <div className="min-w-[170px]">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-bold text-white">{s.name}</div>
          {s.brand ? (
            <div className="mt-0.5 truncate text-xs text-neutral-400">{s.brand}</div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Tutup popup"
          className="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-full text-neutral-400 transition-colors hover:bg-ink-800 hover:text-white"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
            <path
              d="M2 2l10 10M12 2L2 12"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
      <div
        className={`mb-2.5 text-xs font-semibold ${s.is_online ? "text-ok-400" : "text-bad-400"}`}
      >
        {s.is_online ? "● Online" : "● Offline"}
      </div>
      {coords ? (
        <div className="mb-3 text-xs text-neutral-400">{coords}</div>
      ) : null}
      {/* Edit lokasi (super_admin): marker baru bisa diseret setelah
          tombol ini diklik; tombol berubah jadi Save Lokasi. */}
      {isSuperAdmin && (
        <div className="mb-2">
          {editing ? (
            <div className="flex flex-col gap-2">
              {pendingCoords ? (
                <div className="text-xs font-medium text-accent-400">
                  Posisi baru: {pendingCoords}
                </div>
              ) : (
                <div className="text-xs text-neutral-400">
                  Seret marker ke posisi baru.
                </div>
              )}
              <Button variant="primary" className="w-full" onClick={onSaveLocation}>
                Save Lokasi
              </Button>
              <Button variant="subtle" className="w-full" onClick={onCancelLocation}>
                Batal
              </Button>
            </div>
          ) : (
            <Button variant="subtle" className="w-full" onClick={onEditLocation}>
              Edit Lokasi
            </Button>
          )}
        </div>
      )}
      <Button variant="primary" className="w-full" onClick={onLive}>
        Lihat live
      </Button>
    </div>
  );
}

/* Panel samping: akordion collapsed-first di HP, selalu terbuka di desktop. */
function SideAccordion({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="!rounded-xl !p-4 nv-panel-modern">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex min-h-[44px] w-full cursor-pointer items-center justify-between gap-3 text-left md:cursor-default"
      >
        <h2 className="text-[15px] font-extrabold tracking-tight text-white">{title}</h2>
        <span className="flex shrink-0 items-center gap-2">
          <span className="rounded-full bg-ink-800 px-2.5 py-0.5 text-xs font-medium text-neutral-400 shadow-sm">
            {count}
          </span>
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            aria-hidden
            className={`shrink-0 text-neutral-400 transition-transform duration-200 md:hidden ${open ? "rotate-180" : ""}`}
          >
            <path
              d="M4 6l4 4 4-4"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </button>
      <div className={`${open ? "mt-3 block" : "hidden"} md:mt-3 md:block`}>{children}</div>
    </Card>
  );
}

export default function MapsPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const { status } = useCameraStatus();

  const [streams, setStreams] = useState<Stream[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  /* Edit lokasi: hanya satu kamera dalam mode edit; marker tidak bisa
     diseret sebelum tombol Edit Lokasi diklik. */
  const [editingLocationId, setEditingLocationId] = useState<number | null>(
    null,
  );
  const [pendingPos, setPendingPos] = useState<{
    lat: number;
    lng: number;
  } | null>(null);
  const editOriginRef = useRef<{ lat: number; lng: number } | null>(null);
  const [focus, setFocus] = useState<Stream | null>(null);
  const [mapQuery, setMapQuery] = useState("");
  const [locating, setLocating] = useState(false);
  const [locateMsg, setLocateMsg] = useState<string | null>(null);
  /* Peta + klaster siap: sinkronisasi marker menunggu ini, supaya tidak
     jalan saat layer klaster belum dibuat (balapan dengan pemuatan data). */
  const [mapReady, setMapReady] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LType.Map | null>(null);
  const layerRef = useRef<LType.LayerGroup | null>(null);
  const meLayerRef = useRef<LType.LayerGroup | null>(null);
  /* D-S5: cache marker per id supaya perubahan status hanya memperbarui
     marker yang berubah, bukan menghancurkan semuanya (popup yang
     terbuka ikut tertahan). */
  const markersRef = useRef(new Map<number, LType.Marker>());
  const popupRootsRef = useRef(
    new Map<number, ReturnType<typeof createRoot>>(),
  );
  const locateTimerRef = useRef<number | null>(null);
  const LRef = useRef<typeof LType | null>(null);
  const fittedRef = useRef(false);
  const focusRef = useRef(setFocus);
  focusRef.current = setFocus;

  /* D-T1: drag/penempatan marker hanya super_admin; backend
     PUT /admin/streams hanya super_admin, admin biasa selalu 403. */
  const isSuperAdmin = user?.role === "super_admin";

  /* Mulai edit lokasi: simpan posisi asal (untuk Batal), aktifkan drag
     pada marker ini saja. Bila kamera lain sedang diedit, kembalikan
     dulu marker itu ke posisi asalnya. */
  const startEditLocation = (s: Stream) => {
    if (editingLocationId !== null && editingLocationId !== s.id) {
      const prev = markersRef.current.get(editingLocationId);
      if (prev && editOriginRef.current) {
        prev.setLatLng([editOriginRef.current.lat, editOriginRef.current.lng]);
      }
      prev?.dragging?.disable();
    }
    editOriginRef.current =
      s.latitude != null && s.longitude != null
        ? { lat: s.latitude, lng: s.longitude }
        : null;
    setPendingPos(null);
    setEditingLocationId(s.id);
    markersRef.current.get(s.id)?.dragging?.enable();
  };

  /* Simpan posisi marker yang sedang diedit (posisi hasil seret). */
  const saveLocation = async (s: Stream) => {
    const marker = markersRef.current.get(s.id);
    const pos =
      pendingPos ??
      (marker
        ? { lat: marker.getLatLng().lat, lng: marker.getLatLng().lng }
        : null);
    if (!pos) return;
    setSavingId(s.id);
    setSaveError(null);
    try {
      await api.put(`/admin/streams/${s.id}`, {
        latitude: pos.lat,
        longitude: pos.lng,
      });
      setStreams((prev) =>
        prev.map((p) =>
          p.id === s.id
            ? { ...p, latitude: pos.lat, longitude: pos.lng }
            : p,
        ),
      );
      setEditingLocationId(null);
      setPendingPos(null);
      editOriginRef.current = null;
      marker?.dragging?.disable();
    } catch (e) {
      setSaveError(
        `Gagal menyimpan posisi ${s.name}: ${e instanceof ApiError ? e.message : "unknown"}`,
      );
    } finally {
      setSavingId(null);
    }
  };

  /* Batal edit: kembalikan marker ke posisi asal, matikan drag. */
  const cancelLocation = (s: Stream) => {
    const marker = markersRef.current.get(s.id);
    if (marker && editOriginRef.current) {
      marker.setLatLng([editOriginRef.current.lat, editOriginRef.current.lng]);
    }
    marker?.dragging?.disable();
    setEditingLocationId(null);
    setPendingPos(null);
    editOriginRef.current = null;
  };

  const load = useCallback(async () => {
    setFetching(true);
    setError(null);
    try {
      const data = await api.get<Stream[]>("/streams");
      setStreams(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat kamera");
    } finally {
      setFetching(false);
    }
  }, []);

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
      return;
    }
    if (user) load();
  }, [loading, user, router, load]);

  /* Inisialisasi peta sekali (client-only). */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const leafletNs = await import("leaflet");
      /* Pakai objek Leaflet ASLI (module.exports) lewat .default, BUKAN
         namespace hasil import() dinamis. Webpack membuat namespace BARU
         (Object.create(null)) di tiap import("leaflet") dinamis, sedangkan
         plugin markercluster (UMD, membaca global L) menempelkan class
         klaster (MarkerClusterGroup, MarkerCluster, MarkerClusterNonAnimated)
         ke namespace import PERTAMA saja. Saat remount (pindah tab),
         namespace baru tidak punya class klaster: grup klaster yang dibuat
         lalu membaca L.MarkerCluster dari window.L (namespace baru) yang
         undefined, sehingga addTo melempar dan kode jatuh ke layer biasa
         tanpa klaster (titik tunggal). module.exports Leaflet adalah satu
         objek yang sama untuk semua import, jadi class klaster yang
         menempel di sana tetap ada di semua mount dan klaster bekerja
         konsisten, baik muat segar maupun setelah pindah tab. */
      const L = (
        (leafletNs as unknown as { default?: typeof LType }).default ??
        leafletNs
      ) as typeof LType;
      /* leaflet.markercluster (UMD) mengharapkan Leaflet sebagai global
         window.L; tanpa ini L.markerClusterGroup tidak terdaftar. */
      (window as unknown as { L?: typeof LType }).L = L;
      /* Jangan jadikan mapRef sebagai penjaga: bila cleanup mount
         sebelumnya tidak men-null-kannya, penjaga ini memblokir init
         ulang dan peta tidak pernah jadi saat kembali lewat navigasi
         client-side (marker hilang, klik tidak jalan). */
      if (cancelled || !containerRef.current) return;
      const container = containerRef.current;
      /* React bisa memakai ulang node DOM container saat navigasi
         client-side. Leaflet menolak L.map bila _leaflet_id lama masih
         menempel ("Map container is already initialized"), jadi
         bersihkan dulu. */
      const containerWithId = container as unknown as {
        _leaflet_id?: unknown;
      };
      if (containerWithId._leaflet_id != null) {
        delete containerWithId._leaflet_id;
      }
      LRef.current = L;
      /* Peta dibuat DULU, sebelum plugin klaster dicoba. Bila pembuatan
         klaster gagal (pernah terjadi di staging: tile tampil tapi
         mapRef tidak pernah diset, marker tidak muncul dan klik nama
         kamera tidak menggeser peta), peta tetap jadi, mapRef terisi,
         dan marker tetap ditambahkan lewat layer biasa. */
      let map: LType.Map;
      try {
        map = L.map(container, {
          center: DEFAULT_CENTER,
          zoom: DEFAULT_ZOOM,
          zoomControl: false, // kontrol zoom React sendiri (44px) di wadah kiri atas
        });
      } catch {
        /* Coba sekali lagi setelah membersihkan _leaflet_id. */
        delete containerWithId._leaflet_id;
        map = L.map(container, {
          center: DEFAULT_CENTER,
          zoom: DEFAULT_ZOOM,
          zoomControl: false,
        });
      }
      if (cancelled) {
        map.remove();
        return;
      }
      /* Isi mapRef segera supaya klik nama kamera (flyTo) tetap jalan
         walau pembuatan layer di bawah gagal. */
      mapRef.current = map;
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map);
      /* Klaster marker: kamera berdekatan digabung jadi satu titik berisi
         jumlah kamera saat zoom out. Klik klaster memperbesar peta ke
         titik itu; di zoom maksimal, marker menyebar (spiderfy) supaya
         tiap kamera tetap bisa diklik. Marker tunggal tetap membuka
         popup dan bisa di-drag (super_admin) seperti biasa. Bila plugin
         tidak bisa dipakai (factory global hilang, class exports tidak
         ketemu, atau import melempar), pakai L.layerGroup biasa supaya
         titik kamera tetap tampil, hanya tanpa pengelompokan. */
      const clusterOptions = {
        showCoverageOnHover: false,
        zoomToBoundsOnClick: true,
        spiderfyOnMaxZoom: true,
        iconCreateFunction: (cluster: {
          getAllChildMarkers: () => unknown[];
          getChildCount: () => number;
        }) => {
          /* Warna klaster dari status kamera di dalamnya (dibaca dari
             properti _nvOnline tiap marker). */
          const markers = cluster.getAllChildMarkers();
          const online = markers.filter(
            (m) =>
              (m as unknown as { _nvOnline?: boolean })._nvOnline !== false,
          ).length;
          const status: ClusterStatus =
            online === markers.length
              ? "ok"
              : online === 0
                ? "bad"
                : "warn";
          return clusterIcon(L, cluster.getChildCount(), status);
        },
      };
      let layer: LType.LayerGroup | null = null;
      try {
        const mc = await import("leaflet.markercluster");
        /* Jangan hanya mengandalkan efek samping global: UMD menempelkan
           class klaster di exports modul juga. Ambil class dari
           mana pun yang menyediakannya. */
        const MarkerClusterGroup =
          (L as unknown as { MarkerClusterGroup?: unknown })
            .MarkerClusterGroup ??
          (mc as unknown as { MarkerClusterGroup?: unknown })
            .MarkerClusterGroup ??
          (mc as unknown as { default?: { MarkerClusterGroup?: unknown } })
            .default?.MarkerClusterGroup;
        if (
          typeof (L as unknown as { markerClusterGroup?: unknown })
            .markerClusterGroup === "function"
        ) {
          layer = (
            L as unknown as {
              markerClusterGroup: (o: unknown) => LType.LayerGroup;
            }
          ).markerClusterGroup(clusterOptions);
        } else if (MarkerClusterGroup) {
          layer = new (
            MarkerClusterGroup as new (o: unknown) => LType.LayerGroup
          )(clusterOptions);
        }
      } catch {
        layer = null;
      }
      if (!layer) layer = L.layerGroup();
      /* addTo seharusnya tidak lagi melempar saat navigasi client-side:
         peta dan layer klaster kini dibuat dari objek Leaflet asli yang
         sama (lihat .default di atas). try/catch ini tinggal sebagai
         pengaman terakhir supaya titik tetap tampil bila klaster gagal
         karena alasan lain. mapRef sudah terisi di atas, dan mapReady
         tetap diset. */
      try {
        layer.addTo(map);
      } catch {
        layer = L.layerGroup();
        layer.addTo(map);
      }
      layerRef.current = layer;
      setMapReady(true);
    })();
    return () => {
      cancelled = true;
      popupRootsRef.current.forEach((r) => r.unmount());
      popupRootsRef.current.clear();
      markersRef.current.clear();
      try {
        mapRef.current?.remove();
      } catch {
        /* abaikan: peta mungkin sudah rusak/hilang */
      }
      mapRef.current = null;
      layerRef.current = null;
      LRef.current = null;
      fittedRef.current = false;
      /* Bersihkan _leaflet_id container supaya navigasi kembali bisa
         membuat peta baru di node DOM yang sama. */
      const c = containerRef.current as unknown as {
        _leaflet_id?: unknown;
      } | null;
      if (c && c._leaflet_id != null) {
        try {
          delete c._leaflet_id;
        } catch {
          /* abaikan */
        }
      }
    };
  }, []);

  /* Status gabungan: API + override WebSocket. */
  const merged = useMemo(
    () =>
      streams.map((s) =>
        status.has(s.id) ? { ...s, is_online: status.get(s.id)! } : s,
      ),
    [streams, status],
  );

  const mapped = useMemo(
    () => merged.filter((s) => s.latitude != null && s.longitude != null),
    [merged],
  );
  const unmapped = useMemo(
    () => merged.filter((s) => s.latitude == null || s.longitude == null),
    [merged],
  );

  /* Pencarian daftar CCTV (filter nama). */
  const q = mapQuery.trim().toLowerCase();
  const mappedShown = useMemo(
    () => (q ? mapped.filter((s) => s.name.toLowerCase().includes(q)) : mapped),
    [mapped, q],
  );
  const unmappedShown = useMemo(
    () =>
      q ? unmapped.filter((s) => s.name.toLowerCase().includes(q)) : unmapped,
    [unmapped, q],
  );

  /* Sinkronisasi marker secara inkremental (D-S5, D-S6): hanya marker
     yang berubah yang diperbarui, marker yang hilang dihapus, popup yang
     sedang terbuka dipertahankan. Marker digambar dari mappedShown
     sehingga pencarian juga memfilter peta, bukan hanya panel samping. */
  useEffect(() => {
    const L = LRef.current;
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!L || !map || !layer || !mapReady) return;
    const wanted = new Map(mappedShown.map((s) => [s.id, s]));

    for (const [id, marker] of markersRef.current) {
      if (wanted.has(id)) continue;
      layer.removeLayer(marker);
      marker.remove();
      popupRootsRef.current.get(id)?.unmount();
      popupRootsRef.current.delete(id);
      markersRef.current.delete(id);
    }

    const bounds: LType.LatLngExpression[] = [];
    for (const s of mappedShown) {
      const lat = s.latitude as number;
      const lng = s.longitude as number;
      bounds.push([lat, lng]);
      const existing = markersRef.current.get(s.id);
      if (existing) {
        /* Saat kamera ini sedang diedit, jangan kembalikan posisi marker
           ke koordinat lama (hasil seret harus dipertahankan). */
        if (editingLocationId !== s.id) existing.setLatLng([lat, lng]);
        existing.setIcon(markerIcon(L, s.is_online));
        (existing as unknown as { _nvOnline?: boolean })._nvOnline =
          s.is_online;
        const canDrag = isSuperAdmin && editingLocationId === s.id;
        existing.options.draggable = canDrag;
        if (canDrag) existing.dragging?.enable();
        else existing.dragging?.disable();
        popupRootsRef.current.get(s.id)?.render(
          <MarkerPopup
            s={s}
            onClose={() => map.closePopup()}
            onLive={() => {
              map.closePopup();
              focusRef.current(s);
            }}
            isSuperAdmin={isSuperAdmin}
            editing={editingLocationId === s.id}
            pendingCoords={
              editingLocationId === s.id && pendingPos
                ? `${pendingPos.lat.toFixed(5)}, ${pendingPos.lng.toFixed(5)}`
                : null
            }
            onEditLocation={() => startEditLocation(s)}
            onSaveLocation={() => saveLocation(s)}
            onCancelLocation={() => cancelLocation(s)}
          />,
        );
        continue;
      }

      const marker = L.marker([lat, lng], {
        icon: markerIcon(L, s.is_online),
        draggable: isSuperAdmin && editingLocationId === s.id,
        title: s.name,
      });
      (marker as unknown as { _nvOnline?: boolean })._nvOnline = s.is_online;

      const el = document.createElement("div");
      const popupRoot = createRoot(el);
      popupRoot.render(
        <MarkerPopup
          s={s}
          onClose={() => map.closePopup()}
          onLive={() => {
            map.closePopup();
            focusRef.current(s);
          }}
          isSuperAdmin={isSuperAdmin}
          editing={editingLocationId === s.id}
          pendingCoords={
            editingLocationId === s.id && pendingPos
              ? `${pendingPos.lat.toFixed(5)}, ${pendingPos.lng.toFixed(5)}`
              : null
          }
          onEditLocation={() => startEditLocation(s)}
          onSaveLocation={() => saveLocation(s)}
          onCancelLocation={() => cancelLocation(s)}
        />,
      );
      popupRootsRef.current.set(s.id, popupRoot);
      marker.bindPopup(el, { closeButton: false });

      if (isSuperAdmin) {
        /* Seret hanya mencatat posisi baru; penyimpanan terjadi saat
           tombol Save Lokasi diklik. */
        marker.on("dragend", () => {
          const ll = marker.getLatLng();
          setPendingPos({ lat: ll.lat, lng: ll.lng });
        });
      }

      marker.addTo(layer);
      markersRef.current.set(s.id, marker);
    }

    /* Segarkan ikon klaster agar warnanya mengikuti status online
       terbaru (hijau/kuning/merah). */
    (
      layer as unknown as { refreshClusters?: () => void }
    ).refreshClusters?.();

    if (bounds.length > 0 && !fittedRef.current) {
      map.fitBounds(L.latLngBounds(bounds).pad(0.25));
      fittedRef.current = true;
    }
  }, [mappedShown, isSuperAdmin, mapReady, editingLocationId, pendingPos]);

  /* Admin: tandai kamera belum-dipetakan di tengah peta. */
  const placeAtCenter = async (s: Stream) => {
    const map = mapRef.current;
    if (!map || !isSuperAdmin) return;
    const c = map.getCenter();
    setSavingId(s.id);
    setSaveError(null);
    try {
      await api.put(`/admin/streams/${s.id}`, {
        latitude: c.lat,
        longitude: c.lng,
      });
      setStreams((prev) =>
        prev.map((p) =>
          p.id === s.id ? { ...p, latitude: c.lat, longitude: c.lng } : p,
        ),
      );
    } catch (e) {
      setSaveError(
        `Gagal menyimpan posisi ${s.name}: ${e instanceof ApiError ? e.message : "unknown"}`,
      );
    } finally {
      setSavingId(null);
    }
  };

  /* Tombol "lokasi saya": terbangkan peta ke posisi GPS pengguna. */
  const flashLocate = (msg: string) => {
    setLocateMsg(msg);
    if (locateTimerRef.current) window.clearTimeout(locateTimerRef.current);
    locateTimerRef.current = window.setTimeout(() => setLocateMsg(null), 4000);
  };
  const locateMe = () => {
    const map = mapRef.current;
    const L = LRef.current;
    if (!map || !L || locating) return;
    if (!("geolocation" in navigator)) {
      flashLocate("Lokasi tidak didukung di browser ini");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const { latitude: lat, longitude: lng, accuracy } = pos.coords;
        if (!meLayerRef.current) {
          meLayerRef.current = L.layerGroup().addTo(map);
        }
        meLayerRef.current.clearLayers();
        if (accuracy && isFinite(accuracy)) {
          L.circle([lat, lng], {
            radius: accuracy,
            color: "#3b82f6",
            weight: 1,
            opacity: 0.5,
            fillColor: "#3b82f6",
            fillOpacity: 0.12,
          }).addTo(meLayerRef.current);
        }
        L.circleMarker([lat, lng], {
          radius: 8,
          color: "#ffffff",
          weight: 3,
          fillColor: "#3b82f6",
          fillOpacity: 1,
        }).addTo(meLayerRef.current);
        map.flyTo([lat, lng], Math.max(map.getZoom(), 15), { duration: 0.8 });
      },
      (err) => {
        setLocating(false);
        flashLocate(
          err.code === err.PERMISSION_DENIED
            ? "Izin lokasi ditolak, aktifkan izin lokasi untuk situs ini"
            : "Posisi tidak ditemukan, coba lagi",
        );
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  };

  return (
    <AppShell>
      {/* Override tema Leaflet: popup + kontrol zoom ikut data-theme */}
      <style>{`
        .leaflet-popup-content-wrapper { background: var(--nv-ink-900); color: var(--nv-white); border-radius: 16px; border: 1px solid var(--nv-ink-700); box-shadow: 0 12px 32px -8px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06); }
        .leaflet-popup-content { margin: 14px 16px; line-height: 1.4; }
        .leaflet-popup-tip { background: var(--nv-ink-900); }
        [data-theme="light"] .leaflet-popup-content-wrapper { box-shadow: 0 12px 32px -12px rgba(15,23,42,0.25), inset 0 1px 0 rgba(255,255,255,0.8); }
      `}</style>
      <div className="px-4 pt-5 md:px-5 md:pt-7">
        <SectionTitle
          title="Peta Kamera"
          desc={
            isSuperAdmin
              ? "Lokasi semua kamera. Klik marker, lalu Edit Lokasi untuk memindahkan posisi (super admin)."
              : "Lokasi semua kamera."
          }
          action={
            <div className="relative w-full sm:w-80">
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-400"
                aria-hidden
              >
                <path
                  d="M7.5 12.5a5 5 0 100-10 5 5 0 000 10zM11.5 11.5L14 14"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
              <input
                type="search"
                value={mapQuery}
                onChange={(e) => setMapQuery(e.target.value)}
                placeholder="Cari CCTV…"
                aria-label="Cari CCTV"
                className="h-11 w-full rounded-full bg-ink-800 pl-10 pr-4 text-base text-white shadow-sm placeholder:text-neutral-400 outline-none transition-all duration-150 focus:ring-2 focus:ring-accent-500/30"
              />
            </div>
          }
        />
      </div>
      <div className="flex flex-col gap-4 p-4 md:h-[calc(100dvh-150px)] md:min-h-[420px] md:flex-row md:p-5">
        {/* Peta */}
        <div className="relative min-h-[320px] flex-1 overflow-hidden rounded-2xl shadow-[0_12px_40px_-12px_rgba(0,0,0,0.45)]">
          <div ref={containerRef} className="absolute inset-0 z-0" />
          {fetching && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-ink-950/60">
              <span className="flex items-center gap-2 text-sm text-neutral-400">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-ink-700 border-t-accent-400 motion-reduce:animate-none" />
                Memuat peta…
              </span>
            </div>
          )}
          {isSuperAdmin && (
            <div className="nv-frost absolute left-1/2 top-3 z-10 -translate-x-1/2 whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs text-neutral-300">
              Klik marker, lalu Edit Lokasi untuk memindahkan posisi
            </div>
          )}
          {/* Kontrol peta kiri atas: zoom, lokasi saya, dan pesan hasil
              dalam satu wadah bertumpuk (tanpa angka posisi tetap).
              Di HP untuk admin wadah turun sedikit supaya tidak menutupi
              pil petunjuk di tengah atas. */}
          <div
            className={`absolute left-2.5 z-10 flex flex-col items-start gap-2.5 ${isSuperAdmin ? "top-14 md:top-2.5" : "top-2.5"}`}
          >
            <div className="nv-frost flex flex-col overflow-hidden rounded-full">
              <button
                type="button"
                onClick={() => mapRef.current?.zoomIn()}
                aria-label="Perbesar peta"
                title="Perbesar"
                className="flex h-11 w-11 cursor-pointer items-center justify-center text-lg font-bold text-white transition-colors hover:bg-ink-800"
              >
                +
              </button>
              <span className="h-px bg-ink-700" aria-hidden />
              <button
                type="button"
                onClick={() => mapRef.current?.zoomOut()}
                aria-label="Perkecil peta"
                title="Perkecil"
                className="flex h-11 w-11 cursor-pointer items-center justify-center text-lg font-bold text-white transition-colors hover:bg-ink-800"
              >
                -
              </button>
            </div>
            <button
              type="button"
              onClick={locateMe}
              disabled={locating}
              aria-label="Tunjukkan lokasi saya"
              title="Lokasi saya"
              className="nv-frost flex h-11 w-11 cursor-pointer items-center justify-center rounded-full text-neutral-200 transition-transform duration-150 active:scale-95 disabled:opacity-70"
            >
              {locating ? (
                <svg className="animate-spin" width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.25" />
                  <path d="M21 12a9 9 0 00-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                  <circle cx="12" cy="12" r="6.5" />
                  <circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
                  <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
                </svg>
              )}
            </button>
            {locateMsg && (
              <div className="nv-frost max-w-[240px] rounded-2xl px-3 py-2 text-xs leading-snug text-neutral-200">
                {locateMsg}
              </div>
            )}
          </div>
          <div className="nv-frost absolute bottom-3 left-3 z-10 rounded-xl px-4 py-3">
            <div className="mb-2 text-xs font-bold text-white">Legenda</div>
            <div className="flex items-center gap-3 text-xs font-medium text-neutral-300">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-ok-400" /> Online
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-bad-400" /> Offline
              </span>
            </div>
          </div>
        </div>

        {/* Panel samping */}
        <div className="flex w-full flex-col gap-4 md:w-80 md:shrink-0">
          {error && <ErrorBox message={error} />}
          {saveError && <ErrorBox message={saveError} />}

          <SideAccordion title="Belum dipetakan" count={unmappedShown.length}>
            {unmappedShown.length === 0 ? (
              <div className="rounded-xl bg-ink-800 px-4 py-6 text-center text-xs leading-relaxed text-neutral-400 shadow-sm">
                {q ? "Tidak ada yang cocok." : "Semua kamera sudah punya posisi."}
              </div>
            ) : (
              <ul className="flex max-h-48 flex-col gap-1.5 overflow-y-auto md:max-h-64">
                {unmappedShown.map((s) => (
                  <li
                    key={s.id}
                    className="flex min-h-[44px] items-center justify-between gap-2 rounded-xl bg-ink-800 px-4 py-2 shadow-sm"
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2.5">
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                      />
                      <span className="min-w-0 flex-1 truncate text-sm text-neutral-200">
                        {s.name}
                      </span>
                    </div>
                    {isSuperAdmin && (
                      <Button
                        variant="primary"
                        onClick={() => placeAtCenter(s)}
                        disabled={savingId === s.id}
                        className="h-11 shrink-0 px-3 text-xs"
                      >
                        {savingId === s.id ? "…" : "Tengah peta"}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {isSuperAdmin && unmappedShown.length > 0 && (
              <p className="mt-3 text-xs leading-relaxed text-neutral-400">
                Geser peta ke lokasi kamera, lalu tekan “Tengah peta”.
              </p>
            )}
          </SideAccordion>

          <SideAccordion title="Di peta" count={mappedShown.length}>
            {mappedShown.length === 0 ? (
              <div className="rounded-xl bg-ink-800 px-4 py-6 text-center text-xs leading-relaxed text-neutral-400 shadow-sm">
                {q ? "Tidak ada yang cocok." : "Belum ada kamera yang dipetakan."}
              </div>
            ) : (
              <ul className="flex max-h-40 flex-col gap-2 overflow-y-auto md:max-h-56">
                {mappedShown.map((s) => (
                  <li key={s.id}>
                    <button
                      onClick={() => {
                        const map = mapRef.current;
                        if (map && s.latitude != null && s.longitude != null) {
                          map.flyTo([s.latitude, s.longitude], 15, {
                            duration: 0.8,
                          });
                        }
                      }}
                      className="flex min-h-[44px] w-full cursor-pointer items-center gap-2.5 rounded-xl bg-ink-800 px-4 py-2.5 text-left shadow-sm transition-all duration-150 hover:bg-ink-700 active:scale-[0.99]"
                    >
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                      />
                      <span className="min-w-0 flex-1 truncate text-sm text-neutral-200">
                        {s.name}
                      </span>
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 16 16"
                        fill="none"
                        className="shrink-0 text-neutral-400"
                        aria-hidden
                      >
                        <path
                          d="M8 14s5-4.6 5-8a5 5 0 10-10 0c0 3.4 5 8 5 8z"
                          stroke="currentColor"
                          strokeWidth="1.5"
                        />
                        <circle cx="8" cy="6" r="1.8" stroke="currentColor" strokeWidth="1.5" />
                      </svg>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </SideAccordion>
        </div>
      </div>

      <FocusModal stream={focus} onClose={() => setFocus(null)} />
    </AppShell>
  );
}
