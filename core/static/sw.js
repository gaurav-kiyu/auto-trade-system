/**
 * RealEstate India — Service Worker
 *
 * Provides offline caching for static assets and property API responses,
 * install prompt support, and notification push stubs.
 *
 * Cache Strategy:
 *   - Static assets (JS, CSS, fonts): Cache-first with background refresh
 *   - API responses: Network-first with offline fallback to cache
 *   - HTML pages: Network-first (fresh data preferred)
 *
 * Cache Version: v1 (bump to clear all caches on deploy)
 */

const CACHE_VERSION = 're-india-v1';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const API_CACHE = `${CACHE_VERSION}-api`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;

const STATIC_URLS = [
  '/static/tailwind.min.js',
  '/static/fontawesome.min.css',
  '/static/leaflet-map.js',
  '/static/manifest.json',
  '/static/re-icon-192.png',
  '/static/re-icon-512.png',
];

const API_PREFIXES = [
  '/api/realestate/properties',
  '/api/realestate/neighborhood',
  '/api/realestate/languages',
  '/api/realestate/recommendations',
  '/api/realestate/notifications/unread-count',
];

const PAGE_URLS = [
  '/realestate',
  '/realestate/search',
  '/realestate/tenant',
  '/realestate/leads',
  '/realestate/admin',
];

// ── Install ──
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      // Only cache what's available at install time
      return cache.addAll(STATIC_URLS).catch((err) => {
        console.warn('[SW] Static cache warm failed (non-critical):', err);
      });
    })
  );
  // Activate immediately — don't wait for page reload
  self.skipWaiting();
});

// ── Activate ──
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE && key !== API_CACHE && key !== PAGE_CACHE)
          .map((key) => caches.delete(key))
      );
    })
  );
  // Take control of all clients immediately
  self.clients.claim();
});

// ── Fetch ──
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET, non-HTTP(S) requests
  if (event.request.method !== 'GET' || !url.protocol.startsWith('http')) return;

  // ── Static assets: Cache-first ──
  if (STATIC_URLS.some((s) => url.pathname === s)) {
    event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    return;
  }

  // ── API requests: Network-first ──
  if (API_PREFIXES.some((p) => url.pathname.startsWith(p))) {
    event.respondWith(networkFirst(event.request, API_CACHE));
    return;
  }

  // ── Page navigations: Network-first ──
  if (event.request.mode === 'navigate') {
    event.respondWith(networkFirst(event.request, PAGE_CACHE));
    return;
  }

  // ── Everything else: Network-only fallback to cache ──
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});

// ── Push Notifications (stub for future Web Push integration) ──
self.addEventListener('push', (event) => {
  let data = { title: 'RealEstate India', body: 'You have a new update!' };
  try {
    if (event.data) data = event.data.json();
  } catch (e) {
    // Use defaults
  }

  const options = {
    body: data.body,
    icon: '/static/re-icon-192.png',
    badge: '/static/re-icon-192.png',
    vibrate: [200, 100, 200],
    data: { url: data.url || '/realestate' },
    actions: [
      { action: 'open', title: 'Open App' },
      { action: 'dismiss', title: 'Dismiss' },
    ],
    tag: 're-india-notification',
    renotify: true,
    requireInteraction: true,
  };

  event.waitUntil(self.registration.showNotification(data.title, options));
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || '/realestate';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes('/realestate') && 'focus' in client) {
          client.focus();
          client.navigate(targetUrl);
          return;
        }
      }
      clients.openWindow(targetUrl);
    })
  );
});

// ── Cache Strategies ──

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) {
    // Background refresh (fire-and-forget)
    fetch(request)
      .then((response) => {
        if (response.ok) {
          caches.open(cacheName).then((cache) => cache.put(request, response));
        }
      })
      .catch(() => {});
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
    return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
  }
}

async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const clone = response.clone();
      caches.open(cacheName).then((cache) => cache.put(request, clone));
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
  }
}
