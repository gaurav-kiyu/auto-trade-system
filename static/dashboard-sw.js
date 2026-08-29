// OPB Super-App Dashboard Service Worker
const CACHE_NAME = 'opb-cache-v2';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(
            keys.filter((key) => key.startsWith('opb-cache-') && key !== CACHE_NAME)
                .map((key) => caches.delete(key))
        )).then(() => clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    // Network-first caching strategy
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request);
        })
    );
});

// ── Native Web Push Notifications ────────────────────────────
self.addEventListener('push', (event) => {
    let payload = {
        title: 'OPB Trading Alert',
        body: 'New market event detected',
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/icon-192.png',
        data: { url: '/' }
    };
    try {
        if (event.data) {
            const data = event.data.json();
            payload = { ...payload, ...data };
        }
    } catch (e) {
        if (event.data) {
            payload.body = event.data.text();
        }
    }
    const options = {
        body: payload.body,
        icon: payload.icon || '/static/icons/icon-192.png',
        badge: payload.badge || '/static/icons/icon-192.png',
        vibrate: [100, 50, 100],
        data: payload.data || { url: '/' }
    };
    event.waitUntil(self.registration.showNotification(payload.title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
            for (let client of windowClients) {
                if (client.url.includes(targetUrl) && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
