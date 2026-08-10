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

// --- Web Push (container_depot/ess/push.py) ---------------------------------
// This is the half of notifications that works with the app closed: the bell only
// updates while someone is looking at it. The OS plays its own notification sound and
// vibration for these — that is not something the page can do for itself, and it is the
// whole reason for going through the push service rather than polling harder.
const ICON = "/assets/container_depot/ess/icons/icon-192.png"

self.addEventListener("push", (event) => {
	let data = {}
	try {
		data = event.data ? event.data.json() : {}
	} catch (e) {
		// A push with a non-JSON body is not worth dropping — show the raw text.
		data = { body: event.data ? event.data.text() : "" }
	}
	event.waitUntil(
		self.registration.showNotification(data.title || "Depot OAK", {
			body: data.body || "",
			icon: ICON,
			badge: ICON,
			// Tag is the source document. Two events about one order collapse into a
			// single banner; `renotify` makes that replacement still alert, so an update
			// worth knowing about is not swallowed by the collapsing.
			tag: data.tag || "depot",
			renotify: true,
			data: { url: data.url || "/depot" },
		})
	)
})

self.addEventListener("notificationclick", (event) => {
	event.notification.close()
	const target = (event.notification.data && event.notification.data.url) || "/depot"
	// Reuse an open depot window if there is one. Opening a second copy of a standalone
	// PWA is disorienting, and the operator loses whatever form they had in progress.
	event.waitUntil(
		self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
			for (const client of list) {
				if (client.url.includes("/depot") && "focus" in client) return client.focus()
			}
			return self.clients.openWindow(target)
		})
	)
})
