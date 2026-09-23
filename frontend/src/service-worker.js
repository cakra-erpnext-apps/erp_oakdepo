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
// One exception: the Lucide sprite every <Icon> draws from. It is Frappe's file, outside the
// precache manifest, so without this an offline app renders with no icons at all.
// Stale-while-revalidate: served from cache, refreshed in the background when online.
const ICON_SPRITE = "/assets/frappe/icons/lucide.svg"
self.addEventListener("fetch", (event) => {
	if (new URL(event.request.url).pathname !== ICON_SPRITE) return
	event.respondWith(
		caches.open("oak-icons").then(async (cache) => {
			const hit = await cache.match(event.request, { ignoreSearch: true })
			const fresh = fetch(event.request)
				.then((res) => {
					if (res.ok) cache.put(event.request, res.clone())
					return res
				})
				.catch(() => hit)
			return hit || fresh
		})
	)
})

// --- Web Push (container_depot/ess/push.py) ---------------------------------
// This is the half of notifications that works with the app closed: the bell only
// updates while someone is looking at it. The OS plays its own notification sound and
// vibration for these — that is not something the page can do for itself, and it is the
// whole reason for going through the push service rather than polling harder.

// Two icons, two completely different jobs — the app icon can do neither.
//
//   notif-192: the large icon, shown in colour. The brand disc edge to edge with
//     transparent corners, because Android keeps whatever is behind the artwork and
//     `icon-192` carries the white page the launcher icon needs.
//   badge-96: the small status-bar icon, which Android reads as an ALPHA MASK — colour
//     is thrown away and the opaque pixels get tinted. `icon-192` is RGB with no alpha
//     at all, so every pixel counted as opaque and the badge came out a blank square.
//     This one is the palm alone, white on transparent.
//
// Both are derived from icons/icon-192.png; re-cut them if the logo ever changes.
const ICON = "/assets/container_depot/ess/icons/notif-192.png"
const BADGE = "/assets/container_depot/ess/icons/badge-96.png"

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
			badge: BADGE,
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
