// IRIS-BOX Air-Gapped Service Worker
// Strict Offline Policy: Zero outbound external requests, local cache-first app shell.

const CACHE_NAME = 'iris-mobile-shell-v1';
const APP_SHELL_URLS = [
  '/mobile',
  '/static/mobile/mobile.css',
  '/static/mobile/mobile.js',
  '/static/mobile/icon.svg',
  '/static/mobile/manifest.webmanifest'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(APP_SHELL_URLS);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keyList) => {
      return Promise.all(
        keyList.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1. Never cache API endpoints, WebSockets, or notification streams (Network-only)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws') || url.pathname.includes('/stream')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // 2. Air-gapped guard: reject any external domain requests
  if (url.origin !== self.location.origin) {
    event.respondWith(new Response('Air-gapped policy violation: external request blocked', { status: 403 }));
    return;
  }

  // 3. Cache-first strategy for app shell assets
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(event.request).then((response) => {
        // Cache dynamic local static assets
        if (response && response.status === 200 && url.pathname.startsWith('/static/mobile/')) {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return response;
      });
    })
  );
});
