// RealEstate India — Service Worker v1.0
// ─────────────────────────────────────────────────────────────────────────────
// Cache-first for static assets, network-first for API calls,
// fallback to cached content when offline.
// ─────────────────────────────────────────────────────────────────────────────

const CACHE_NAME = "re-cache-v1";
const API_CACHE = "re-api-cache-v1";
const STATIC_CACHE = "re-static-cache-v1";

// ── Assets to pre-cache on install ───────────────────────────────────────────
const PRECACHE_URLS = [
  "/static/tailwind.min.js",
  "/static/fontawesome.min.css",
  "/static/re-icon-192.svg",
  "/static/re-icon-512.svg",
  "/realestate",
  "/realestate/search",
];

// ── Install: pre-cache critical assets ───────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch((err) => {
        console.warn("[SW] Pre-cache failed for some assets:", err);
      });
    }).then(() => self.skipWaiting())
  );
});

// ── Activate: clean old caches ───────────────────────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME && name !== API_CACHE && name !== STATIC_CACHE)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// ── Fetch: intelligent caching strategy ──────────────────────────────────────
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const path = url.pathname;

  // ── API requests (network-first with cache fallback) ───────────────────────
  if (path.startsWith("/api/")) {
    event.respondWith(networkFirstWithCache(event.request, API_CACHE));
    return;
  }

  // ── Static assets (cache-first) ────────────────────────────────────────────
  if (path.startsWith("/static/")) {
    event.respondWith(cacheFirstWithNetwork(event.request, STATIC_CACHE));
    return;
  }

  // ── Navigation / pages (network-first) ─────────────────────────────────────
  if (event.request.mode === "navigate") {
    event.respondWith(networkFirstWithCache(event.request, CACHE_NAME));
    return;
  }

  // ── Everything else (network-only) ─────────────────────────────────────────
  event.respondWith(fetch(event.request).catch(() => {
    return new Response("Offline", { status: 503, statusText: "Offline" });
  }));
});

// ── Cache-First Strategy ─────────────────────────────────────────────────────
async function cacheFirstWithNetwork(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) {
    // Refresh cache in background (stale-while-revalidate)
    fetch(request).then((response) => {
      if (response.ok) {
        caches.open(cacheName).then((cache) => cache.put(request, response));
      }
    }).catch(() => {});
    return cached;
  }

  try {
    const response = await fetch(request);
    if (response.ok) {
      const clone = response.clone();
      caches.open(cacheName).then((cache) => cache.put(request, clone));
    }
    return response;
  } catch (err) {
    return new Response("Offline", { status: 503 });
  }
}

// ── Network-First Strategy ───────────────────────────────────────────────────
async function networkFirstWithCache(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const clone = response.clone();
      caches.open(cacheName).then((cache) => cache.put(request, clone));
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    // Return a meaningful offline page for navigations
    if (request.mode === "navigate") {
      return new Response(
        `<!DOCTYPE html><html><head><title>Offline</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>body{font-family:sans-serif;background:#080b10;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:2rem;}
        h1{font-size:2rem;margin-bottom:1rem;}p{color:#64748b;}</style></head>
        <body><div><h1>📡 You're Offline</h1>
        <p>RealEstate India needs an internet connection.<br>Please check your connection and try again.</p></div></body></html>`,
        { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } }
      );
    }
    return new Response("Offline", { status: 503 });
  }
}

// ── Background Sync for offline form submissions ─────────────────────────────
self.addEventListener("sync", (event) => {
  if (event.tag === "sync-enquiries") {
    event.waitUntil(syncEnquiries());
  }
});

async function syncEnquiries() {
  try {
    const cache = await caches.open("re-pending-enquiries");
    const requests = await cache.keys();
    for (const req of requests) {
      try {
        const response = await fetch(req);
        if (response.ok) {
          await cache.delete(req);
        }
      } catch (err) {
        console.warn("[SW] Sync failed for enquiry, will retry:", err);
      }
    }
  } catch (err) {
    console.warn("[SW] Background sync error:", err);
  }
}

// ── Push Notification Handler ────────────────────────────────────────────────
self.addEventListener("push", (event) => {
  if (!event.data) return;

  try {
    const data = event.data.json();
    const title = data.title || "RealEstate India";
    const options = {
      body: data.body || "",
      icon: "/static/re-icon-192.svg",
      badge: "/static/re-icon-192.svg",
      vibrate: [200, 100, 200],
      data: { url: data.url || "/realestate" },
      requireInteraction: true,
      actions: [
        { action: "open", title: "View" },
        { action: "dismiss", title: "Dismiss" },
      ],
    };
    event.waitUntil(self.registration.showNotification(title, options));
  } catch (err) {
    console.warn("[SW] Push notification error:", err);
  }
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  if (event.action === "dismiss") return;

  const url = event.notification.data?.url || "/realestate";
  event.waitUntil(clients.openWindow(url));
});
