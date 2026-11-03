"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import "leaflet/dist/leaflet.css";
import type * as LType from "leaflet";
import { AppShell } from "../../components/AppShell";
import { FocusModal } from "../../components/FocusModal";
import { Button, Card, ErrorBox, SectionTitle } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { isAdminRole, useAuth } from "../../lib/auth";
import { useCameraStatus } from "../../hooks/useCameraStatus";
import type { Stream } from "../../lib/types";

/* Peta kamera (Leaflet, client-only — aman untuk static export).
   Marker: hijau = online, merah = offline.
   Admin bisa drag marker → PUT /api/admin/streams/{id} {latitude, longitude}. */

const DEFAULT_CENTER: [number, number] = [-2.5, 118];
const DEFAULT_ZOOM = 5;

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function markerIcon(L: typeof LType, online: boolean): LType.DivIcon {
  const color = online ? "var(--nv-ok-400)" : "var(--nv-bad-400)";
  const size = L.Browser.touch ? 28 : 20; // lebih besar di layar sentuh
  const half = size / 2;
  return L.divIcon({
    className: "nv-marker",
    html: `<span style="display:block;width:${size}px;height:${size}px;border-radius:9999px;background:${color};border:3px solid var(--nv-ink-950);box-shadow:0 0 0 2px ${color}, 0 2px 8px rgba(0,0,0,.55)"></span>`,
    iconSize: [size, size],
    iconAnchor: [half, half],
    popupAnchor: [0, -half - 1],
  });
}

function popupHtml(s: Stream): string {
  const sub = s.brand ? escapeHtml(s.brand) : "";
  return `
    <div style="min-width:170px">
      <div style="font-weight:700;font-size:14px;color:var(--nv-white);margin-bottom:2px">${escapeHtml(s.name)}</div>
      ${sub ? `<div style="font-size:11px;color:var(--nv-neutral-400,#a3a3a3);margin-bottom:6px">${sub}</div>` : `<div style="margin-bottom:6px"></div>`}
      <div style="font-size:11px;font-weight:600;margin-bottom:10px;color:${s.is_online ? "var(--nv-ok-400)" : "var(--nv-bad-400)"}">${s.is_online ? "● Online" : "● Offline"}</div>
    </div>
  `;
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
  const [focus, setFocus] = useState<Stream | null>(null);
  const [mapQuery, setMapQuery] = useState("");

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LType.Map | null>(null);
  const layerRef = useRef<LType.LayerGroup | null>(null);
  const LRef = useRef<typeof LType | null>(null);
  const fittedRef = useRef(false);
  const focusRef = useRef(setFocus);
  focusRef.current = setFocus;

  const isAdmin = isAdminRole(user?.role);

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
      const L = await import("leaflet");
      if (cancelled || !containerRef.current || mapRef.current) return;
      LRef.current = L;
      const map = L.map(containerRef.current, {
        center: DEFAULT_CENTER,
        zoom: DEFAULT_ZOOM,
        zoomControl: true,
      });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map);
      layerRef.current = L.layerGroup().addTo(map);
      mapRef.current = map;
    })();
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
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

  /* Gambar ulang marker setiap data/status berubah. */
  useEffect(() => {
    const L = LRef.current;
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!L || !map || !layer) return;
    layer.clearLayers();
    const bounds: LType.LatLngExpression[] = [];

    for (const s of mapped) {
      const lat = s.latitude as number;
      const lng = s.longitude as number;
      const marker = L.marker([lat, lng], {
        icon: markerIcon(L, s.is_online),
        draggable: isAdmin,
        title: s.name,
      });

      const el = document.createElement("div");
      el.innerHTML = popupHtml(s);
      const btn = document.createElement("button");
      btn.textContent = "Lihat live";
      btn.style.cssText =
        "width:100%;padding:10px 12px;border-radius:10px;background:var(--nv-accent-600);color:#fff;font-size:13px;font-weight:600;border:none;cursor:pointer;min-height:44px";
      btn.onclick = () => {
        map.closePopup();
        focusRef.current(s);
      };
      el.appendChild(btn);
      marker.bindPopup(el, { closeButton: false });

      if (isAdmin) {
        marker.on("dragend", async () => {
          const ll = marker.getLatLng();
          setSavingId(s.id);
          setSaveError(null);
          try {
            await api.put(`/admin/streams/${s.id}`, {
              latitude: ll.lat,
              longitude: ll.lng,
            });
            setStreams((prev) =>
              prev.map((p) =>
                p.id === s.id
                  ? { ...p, latitude: ll.lat, longitude: ll.lng }
                  : p,
              ),
            );
          } catch (e) {
            setSaveError(
              `Gagal menyimpan posisi ${s.name}: ${e instanceof ApiError ? e.message : "unknown"}`,
            );
            marker.setLatLng([lat, lng]); // kembalikan
          } finally {
            setSavingId(null);
          }
        });
      }

      marker.addTo(layer);
      bounds.push([lat, lng]);
    }

    if (bounds.length > 0 && !fittedRef.current) {
      map.fitBounds(L.latLngBounds(bounds).pad(0.25));
      fittedRef.current = true;
    }
  }, [mapped, isAdmin]);

  /* Admin: tandai kamera belum-dipetakan di tengah peta. */
  const placeAtCenter = async (s: Stream) => {
    const map = mapRef.current;
    if (!map || !isAdmin) return;
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

  return (
    <AppShell>
      {/* Override tema Leaflet: popup + kontrol zoom ikut data-theme */}
      <style>{`
        .leaflet-popup-content-wrapper { background: var(--nv-ink-900); color: var(--nv-white); border-radius: 14px; }
        .leaflet-popup-content { margin: 14px 16px; line-height: 1.4; }
        .leaflet-popup-tip { background: var(--nv-ink-900); }
        .leaflet-bar a { width: 44px !important; height: 44px !important; line-height: 44px !important; }
      `}</style>
      <div className="px-4 pt-5 md:px-5 md:pt-7">
        <SectionTitle
          title="Peta Kamera"
          desc="Lokasi semua kamera. Seret marker untuk memindahkan posisi (admin)."
        />
      </div>
      <div className="flex h-[calc(100dvh-300px)] min-h-[420px] flex-col gap-4 p-4 md:h-[calc(100dvh-150px)] md:flex-row md:p-5">
        {/* Peta */}
        <div className="relative min-h-[320px] flex-1 overflow-hidden rounded-2xl ring-1 ring-white/10">
          <div ref={containerRef} className="absolute inset-0 z-0" />
          {fetching && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-ink-950/60">
              <span className="flex items-center gap-2 text-sm text-neutral-400">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-ink-700 border-t-accent-400 motion-reduce:animate-none" />
                Memuat peta…
              </span>
            </div>
          )}
          {isAdmin && (
            <div className="absolute bottom-8 right-3 z-10 max-w-[calc(100%-24px)] rounded-xl bg-ink-900/95 px-3.5 py-2.5 text-xs text-neutral-300 ring-1 ring-white/10">
              Seret marker untuk memindahkan posisi kamera
            </div>
          )}
          <div className="absolute bottom-3 left-3 z-10 flex items-center gap-3 rounded-xl bg-ink-900/95 px-3.5 py-2.5 text-[11px] font-medium text-neutral-300 ring-1 ring-white/10">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-ok-400" /> Online
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-bad-400" /> Offline
            </span>
          </div>
        </div>

        {/* Panel samping */}
        <div className="flex w-full flex-col gap-4 md:w-80 md:shrink-0">
          {/* Pencarian CCTV */}
          <div className="relative">
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-500"
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
              className="h-11 w-full rounded-xl bg-ink-900 pl-10 pr-4 text-base text-white ring-1 ring-white/10 placeholder:text-neutral-500 focus:outline-none focus:ring-2 focus:ring-accent-500"
            />
          </div>

          {error && <ErrorBox message={error} />}
          {saveError && <ErrorBox message={saveError} />}

          <Card className="!p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white">
                Belum dipetakan
              </h2>
              <span className="rounded-full bg-ink-800 px-2.5 py-0.5 text-[11px] font-medium text-neutral-400">
                {unmappedShown.length}
              </span>
            </div>
            {unmappedShown.length === 0 ? (
              <p className="text-xs leading-relaxed text-neutral-500">
                {q ? "Tidak ada yang cocok." : "Semua kamera sudah punya posisi."}
              </p>
            ) : (
              <ul className="flex max-h-48 flex-col gap-1.5 overflow-y-auto md:max-h-64">
                {unmappedShown.map((s) => (
                  <li
                    key={s.id}
                    className="flex items-center justify-between gap-2 rounded-xl bg-ink-800/70 px-3 py-2"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                      />
                      <span className="truncate text-sm text-neutral-200">
                        {s.name}
                      </span>
                    </div>
                    {isAdmin && (
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
            {isAdmin && unmappedShown.length > 0 && (
              <p className="mt-3 text-[11px] leading-relaxed text-neutral-500">
                Geser peta ke lokasi kamera, lalu tekan “Tengah peta”.
              </p>
            )}
          </Card>

          <Card className="!p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white">Di peta</h2>
              <span className="rounded-full bg-ink-800 px-2.5 py-0.5 text-[11px] font-medium text-neutral-400">
                {mappedShown.length}
              </span>
            </div>
            {mappedShown.length === 0 ? (
              <p className="text-xs leading-relaxed text-neutral-500">
                {q ? "Tidak ada yang cocok." : "Belum ada kamera yang dipetakan."}
              </p>
            ) : (
              <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto md:max-h-56">
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
                      className="flex min-h-[44px] w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition hover:bg-ink-800 active:scale-[0.99]"
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
                        className="shrink-0 text-neutral-500"
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
          </Card>
        </div>
      </div>

      <FocusModal stream={focus} onClose={() => setFocus(null)} />
    </AppShell>
  );
}
