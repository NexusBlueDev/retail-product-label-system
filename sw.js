/**
 * Service Worker — NII Retail Product Scanner
 *
 * Strategy:
 *  - App shell (HTML, CSS, JS, icons): Cache-first, updated in background
 *  - API calls (Supabase REST, Edge Functions): Network-only (never cached)
 *  - Images from Supabase Storage: Network-first with cache fallback
 */

const CACHE_NAME = 'product-scanner-v4.5';

// App shell files to pre-cache on install
const APP_SHELL = [
    '/',
    '/index.html',
    '/manifest.json',
    '/logo.jpg',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/styles/main.css',
    '/styles/components.css',
    '/styles/modals.css',
    '/styles/desktop.css',
    '/js/app.js',
    '/js/config.js',
    '/js/state.js',
    '/js/dom.js',
    '/js/events.js',
    '/js/auth.js',
    '/js/user-auth.js',
    '/js/navigation.js',
    '/js/ui-utils.js',
    '/js/image-handler.js',
    '/js/image-compression.js',
    '/js/ai-extraction.js',
    '/js/barcode-scanner.js',
    '/js/form-manager.js',
    '/js/sku-generator.js',
    '/js/database.js',
    '/js/storage.js',
    '/js/quick-capture.js',
    '/js/desktop-processor.js'
];

// Domains that must NEVER be cached (API, auth, storage uploads)
const NETWORK_ONLY_PATTERNS = [
    'supabase.co',
    'supabase.com'
];

// Install: pre-cache app shell
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(APP_SHELL))
            .then(() => self.skipWaiting())
    );
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

// Fetch: route requests by strategy
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Network-only for all Supabase API/auth/storage calls
    if (NETWORK_ONLY_PATTERNS.some(p => url.hostname.includes(p))) {
        event.respondWith(fetch(event.request));
        return;
    }

    // Network-only for POST requests (form submissions, etc.)
    if (event.request.method !== 'GET') {
        event.respondWith(fetch(event.request));
        return;
    }

    // Cache-first for app shell, stale-while-revalidate
    event.respondWith(
        caches.match(event.request).then(cached => {
            const networkFetch = fetch(event.request).then(response => {
                // Update cache with fresh copy
                if (response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            }).catch(() => cached); // Offline fallback to cache

            return cached || networkFetch;
        })
    );
});
