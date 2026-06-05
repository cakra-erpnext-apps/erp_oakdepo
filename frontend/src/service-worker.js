// Minimal service worker — enough to make the PWA installable (Lighthouse
// "installable": manifest + a fetch-handling SW) without caching API data.
// `precacheAndRoute(self.__WB_MANIFEST)` is replaced at build time by
// vite-plugin-pwa (injectManifest) with the hashed app-shell asset list.
import { precacheAndRoute } from "workbox-precaching"

precacheAndRoute(self.__WB_MANIFEST || [])

self.addEventListener("install", () => {
	self.skipWaiting()
})

self.addEventListener("activate", (event) => {
	event.waitUntil(self.clients.claim())
})

// App-shell only: never cache /api or /files responses here — live data must
// stay fresh. Offline data queueing (IndexedDB) is a later phase (PRD §7).
self.addEventListener("fetch", () => {
	// No-op handler; presence of a fetch listener satisfies installability.
})
