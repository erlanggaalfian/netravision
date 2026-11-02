"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import "leaflet/dist/leaflet.css";
import type * as LType from "leaflet";
import { AppShell } from "../../components/AppShell";
import { FocusModal } from "../../components/FocusModal";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
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
  const color = online ? "#34d399" : "#f87171"; // ok-400 / bad-400
  return L.divIcon({
    className: "nv-marker",
    html: `<span style="display:block;width:18px;height:18px;border-radius:9999px;background:${color};border:3px solid #0c0e12;box-shadow:0 0 0 2px ${color}55, 0 2px 6px rgba(0,0,0,.5)"></span>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -10],
  });
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

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LType.Map | null>(null);
  const layerRef = useRef<LType.LayerGroup | null>(null);
  const LRef = useRef<typeof LType | null>(null);
  const fittedRef = useRef(false);
  const focusRef = useRef(setFocus);
  focusRef.current = setFocus;

  const isAdmin = user?.role === "admin";

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
    () =>
      merged.filter(
        (s) => s.latitude != null && s.longitude != null,
      ),
    [merged],
  );
  const unmapped = useMemo(
    () =>
      merged.filter((s) => s.latitude == null || s.longitude == null),
    [merged],
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
      el.className = "nv-popup";
      el.innerHTML = `
        <div style="font-weight:600;font-size:13px;margin-bottom:2px;color:#111">${escapeHtml(s.name)}</div>
        <div style="font-size:11px;margin-bottom:8px;color:${s.is_online ? "#059669" : "#dc2626"}">${s.is_online ? "● Online" : "● Offline"}</div>
      `;
      const btn = document.createElement("button");
      btn.textContent = "Lihat live";
      btn.style.cssText =
        "width:100%;padding:8px 12px;border-radius:8px;background:#4f46e5;color:#fff;font-size:12px;font-weight:600;border:none;cursor:pointer;min-height:40px";
      btn.onclick = () => {
        map.closePopup();
        focusRef.current(s);
      };
      el.appendChild(btn);
      marker.bindPopup(el);

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
      <div className="flex h-[calc(100dvh-220px)] min-h-[420px] flex-col gap-3 p-4 md:h-[calc(100dvh-64px)] md:flex-row">
        {/* Peta */}
        <div className="relative min-h-[320px] flex-1 overflow-hidden rounded-xl ring-1 ring-white/10">
          <div ref={containerRef} className="absolute inset-0 z-0" />
          {fetching && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-ink-950/60">
              <span className="text-sm text-neutral-400">Memuat peta…</span>
            </div>
          )}
          {isAdmin && (
            <div className="absolute left-3 top-3 z-10 rounded-lg bg-ink-900/90 px-3 py-2 text-[11px] text-neutral-300 ring-1 ring-white/10 backdrop-blur">
              Seret marker untuk memindahkan posisi kamera
            </div>
          )}
        </div>

        {/* Panel samping */}
        <div className="flex w-full flex-col gap-3 md:w-72 md:shrink-0">
          {error && (
            <div className="rounded-lg bg-bad-400/10 px-3 py-2 text-xs text-bad-400 ring-1 ring-bad-400/30">
              {error}
            </div>
          )}
          {saveError && (
            <div className="rounded-lg bg-bad-400/10 px-3 py-2 text-xs text-bad-400 ring-1 ring-bad-400/30">
              {saveError}
            </div>
          )}

          <div className="rounded-xl bg-ink-900 p-3 ring-1 ring-white/10">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
              Belum dipetakan ({unmapped.length})
            </div>
            {unmapped.length === 0 ? (
              <div className="text-xs text-neutral-500">
                Semua kamera sudah punya posisi.
              </div>
            ) : (
              <ul className="flex max-h-48 flex-col gap-1.5 overflow-y-auto md:max-h-64">
                {unmapped.map((s) => (
                  <li
                    key={s.id}
                    className="flex items-center justify-between gap-2 rounded-lg bg-ink-800 px-2.5 py-2"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                      />
                      <span className="truncate text-xs text-neutral-200">
                        {s.name}
                      </span>
                    </div>
                    {isAdmin && (
                      <button
                        onClick={() => placeAtCenter(s)}
                        disabled={savingId === s.id}
                        className="shrink-0 rounded-md bg-accent-600 px-2 py-1.5 text-[11px] font-medium text-white transition hover:bg-accent-500 active:scale-95 disabled:opacity-50"
                      >
                        {savingId === s.id ? "…" : "Tengah peta"}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {isAdmin && unmapped.length > 0 && (
              <p className="mt-2 text-[11px] leading-relaxed text-neutral-500">
                Geser peta ke lokasi kamera, lalu tekan “Tengah peta”.
              </p>
            )}
          </div>

          <div className="rounded-xl bg-ink-900 p-3 ring-1 ring-white/10">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
              Di peta ({mapped.length})
            </div>
            <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto md:max-h-56">
              {mapped.map((s) => (
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
                    className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition hover:bg-ink-800 active:scale-[0.99]"
                  >
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${s.is_online ? "bg-ok-400" : "bg-bad-400"}`}
                    />
                    <span className="truncate text-xs text-neutral-200">
                      {s.name}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <FocusModal stream={focus} onClose={() => setFocus(null)} />
    </AppShell>
  );
}
