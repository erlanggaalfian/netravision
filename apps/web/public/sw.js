/* NetraVision service worker — static export, tanpa runtime Node.
 *
 * Strategi:
 * - /api/* dan /ws  -> network-only (JANGAN pernah di-cache)
 * - navigasi (HTML) -> network-first ("nv-shell-v3"), fallback cache saat offline.
 *   HTML tidak di-cache-first agar refresh selalu dapat versi terbaru dari server.
 * - aset _next/static/* (JS/CSS ber-hash) -> cache-first, aman karena nama file
 *   berubah tiap build.
 */

const CACHE = "nv-shell-v3";
const PRECACHE = ["/live/", "/login/", "/manifest.webmanifest", "/icons/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API & WebSocket: selalu ke jaringan, jangan sentuh cache.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws")) return;

  // Aset _next/static/*: cache-first (nama file ber-hash, aman).
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      }),
    );
    return;
  }

  // Navigasi & HTML lain: network-first agar selalu versi terbaru.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => {
        // Offline: pakai cache, fallback ke /live/ untuk navigasi.
        return caches.match(request).then((cached) => {
          if (cached) return cached;
          if (request.mode === "navigate") return caches.match("/live/");
          throw new Error("offline");
        });
      }),
  );
});
