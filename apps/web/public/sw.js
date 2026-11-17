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
/* F5.4: "/icons/icon.svg" dihapus dari PRECACHE karena file itu tidak
   ada di public/icons (hanya icon-192.png, icon-512.png,
   apple-touch-icon.png, logo.png); cache.addAll gagal total bila satu
   saja item 404, jadi SW tidak pernah terpasang. */
const PRECACHE = ["/live/", "/login/", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      /* F5.4: per-item Promise.allSettled, bukan cache.addAll, supaya
         satu item gagal (mis. offline saat install) tidak menggagalkan
         seluruh install service worker. */
      .then((cache) =>
        Promise.allSettled(
          PRECACHE.map((u) => cache.add(u)),
        ),
      )
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
  // F6.10: shell /admin/ dan /embed/ JANGAN masuk cache navigasi.
  // Shell admin yang ter-cache bisa tampil sekilas setelah logout saat
  // offline; shell embed membawa ?key= di URL, tidak pantas di-cache.
  const noCacheNav =
    url.pathname.startsWith("/admin/") ||
    url.pathname === "/admin" ||
    url.pathname.startsWith("/embed/") ||
    url.pathname === "/embed";
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok && !noCacheNav) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => {
        // Offline: pakai cache, fallback ke /live/ untuk navigasi.
        // Path noCacheNav tidak pernah disajikan dari cache.
        return caches.match(request).then((cached) => {
          if (cached && !noCacheNav) return cached;
          if (request.mode === "navigate") return caches.match("/live/");
          throw new Error("offline");
        });
      }),
  );
});
