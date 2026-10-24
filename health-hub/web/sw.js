/* Pebble Health service worker.
   App shell: network-first with a versioned offline fallback.
   API and auth requests are network-only and are never stored in Cache Storage.
   Writes (POST/PUT/…) and every other request go straight to the network. */
'use strict';
const VERSION = 'v28';
const SHELL_CACHE = 'pebble-health-shell-' + VERSION;
const SHELL = [
  'styles.css', 'app.js', 'manifest.webmanifest',
  'icons/icon-192.png', 'icons/icon-512.png', 'icons/maskable-192.png',
  'icons/maskable-512.png', 'icons/apple-touch-icon.png', 'icons/favicon-32.png'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL_CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: 'reload' })))).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys
        .filter(k => k.startsWith('pebble-health-') && k !== SHELL_CACHE)
        .map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function shell(request) {
  const cache=await caches.open(SHELL_CACHE);
  try {
    const response=await fetch(request);
    // Login redirects must reach the browser, never an old offline dashboard.
    if(response.redirected || (response.status >= 300 && response.status < 400)) return response;
    if(response.ok) {
      try {await cache.put(request,response.clone());} catch(cacheError) { /* Fresh network response still wins when storage is full. */ }
      return response;
    }
    const hit=await cache.match(request,{ignoreSearch:request.mode==='navigate'});
    if(hit)return hit;
    if(request.mode==='navigate') {
      const page=await cache.match('index.html');
      if(page)return page;
    }
    return response;
  } catch(error) {
    const hit=await cache.match(request,{ignoreSearch:request.mode==='navigate'});
    if(hit)return hit;
    if(request.mode==='navigate') {
      const page=await cache.match('index.html');
      if(page)return page;
    }
    throw error;
  }
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  const scope = new URL(self.registration.scope);
  const rel = url.pathname.slice(scope.pathname.length);
  if (rel === 'login' || rel === 'login/' || rel.startsWith('api/') || rel.startsWith('auth/')) { event.respondWith(fetch(request)); return; }
  if (rel.startsWith('download/') || rel.startsWith('pair')) return;
  if (request.mode === 'navigate' || SHELL.includes(rel) || rel === '') event.respondWith(shell(request));
});
