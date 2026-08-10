// Web Push registration for the depot PWA — the browser half of ess/push.py.
//
// Three separate things have to line up before a phone can ring, and they fail in
// different ways, so `state.status` distinguishes them rather than collapsing everything
// into a single "off": the browser has to support push at all, the OS has to have granted
// permission, and the server has to hold a live subscription for this device.
//
// Permission must be asked from a user gesture — that is why nothing here runs on load.

import { reactive } from "vue"

const state = reactive({
	supported: false,
	permission: "default", // Notification.permission
	subscribed: false,
	busy: false,
	error: null,
})

export const push = state

export function pushSupported() {
	return (
		typeof window !== "undefined" &&
		"serviceWorker" in navigator &&
		"PushManager" in window &&
		"Notification" in window
	)
}

// base64url -> Uint8Array. `applicationServerKey` will not take the string form.
function urlBase64ToUint8Array(base64String) {
	const padding = "=".repeat((4 - (base64String.length % 4)) % 4)
	const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/")
	const raw = atob(base64)
	return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

async function api(path, body) {
	const res = await fetch(`/api/method/container_depot.ess.push.${path}`, {
		method: body ? "POST" : "GET",
		headers: {
			Accept: "application/json",
			...(body ? { "Content-Type": "application/json" } : {}),
			"X-Frappe-CSRF-Token": window.csrf_token || "",
		},
		...(body ? { body: JSON.stringify(body) } : {}),
	})
	if (!res.ok) throw new Error(`HTTP ${res.status}`)
	return (await res.json()).message
}

/** Read current state without prompting for anything. Safe to call on mount. */
export async function refreshPushState() {
	state.supported = pushSupported()
	if (!state.supported) return state
	state.permission = Notification.permission
	try {
		const reg = await navigator.serviceWorker.ready
		state.subscribed = !!(await reg.pushManager.getSubscription())
	} catch (e) {
		state.subscribed = false
	}
	return state
}

/** Ask permission, subscribe, and register the endpoint. Call from a click handler. */
export async function enablePush() {
	state.busy = true
	state.error = null
	try {
		if (!pushSupported()) throw new Error("unsupported")

		const cfg = await api("get_config")
		if (!cfg?.enabled || !cfg.public_key) throw new Error("server-off")

		// Chrome resolves a denied permission silently; check the result rather than
		// assuming the prompt was answered yes.
		state.permission = await Notification.requestPermission()
		if (state.permission !== "granted") throw new Error("denied")

		const reg = await navigator.serviceWorker.ready
		// An existing subscription is reused: re-subscribing with the same key returns the
		// same endpoint anyway, and unsubscribing first would drop pushes in between.
		const subscription =
			(await reg.pushManager.getSubscription()) ||
			(await reg.pushManager.subscribe({
				userVisibleOnly: true,
				applicationServerKey: urlBase64ToUint8Array(cfg.public_key),
			}))

		await api("subscribe", { subscription: subscription.toJSON() })
		state.subscribed = true
		return true
	} catch (e) {
		state.error = e.message || String(e)
		state.subscribed = false
		return false
	} finally {
		state.busy = false
	}
}

/** Drop this device's registration, server-side and in the browser. */
export async function disablePush() {
	state.busy = true
	state.error = null
	try {
		const reg = await navigator.serviceWorker.ready
		const subscription = await reg.pushManager.getSubscription()
		// Tell the server first: if the browser-side unsubscribe succeeds and the request
		// then fails, the row lives on and we would keep pushing to a dead endpoint until
		// it 410s.
		await api("unsubscribe", { endpoint: subscription?.endpoint || "" })
		if (subscription) await subscription.unsubscribe()
		state.subscribed = false
		return true
	} catch (e) {
		state.error = e.message || String(e)
		return false
	} finally {
		state.busy = false
	}
}
