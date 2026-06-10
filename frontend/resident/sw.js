const CACHE = 'mygate-resident-v1';
const SHELL = [
  '/frontend/resident/index.html',
  '/frontend/resident/manifest.json',
  '/frontend/shared/style.css',
  '/frontend/shared/api.js',
  '/frontend/resident/js/resident.js',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) return; // never cache API calls
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

// Push notifications
self.addEventListener('push', e => {
  const data = e.data?.json() || { title: 'MyGate', body: 'New notification' };
  e.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, icon: '/frontend/resident/icons/icon-192.png', badge: '/frontend/resident/icons/icon-192.png',
    data: data.url,
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data || '/'));
});
