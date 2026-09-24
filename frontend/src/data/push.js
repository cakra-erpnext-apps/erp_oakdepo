// Web Push registration for the depot PWA — the browser half of ess/push.py.
//
// Three separate things have to line up before a phone can ring, and they fail in
// different ways, so `state.status` distinguishes them rather than collapsing everything
// into a single "off": the browser has to support push at all, the OS has to have granted
// permission, and the server has to hold a live subscription for this device.
//
// Permission must be asked from a user gesture — that is why nothing here runs on load.

import { reactive } from "vue"
import { session } from "@/data/session"
import { mutedEvents } from "@/utils/notifMute"

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

// `navigator.serviceWorker.ready` never rejects and never times out: with no registration
// whose scope covers this page it simply stays pending, and the button sits on "Memproses…"
// for the rest of the session. A scope mismatch already caused exactly that once. Cap the
// wait so a broken registration surfaces as an error the operator can report.
const SW_READY_TIMEOUT_MS = 5000

function swReady() {
	return Promise.race([
		navigator.serviceWorker.ready,
		new Promise((_, reject) =>
			setTimeout(() => reject(new Error("sw-timeout")), SW_READY_TIMEOUT_MS)
		),
	])
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

/**
 * Read current state without prompting for anything. Safe to call on mount.
 *
 * A browser subscription is only half the truth, and the half that outlives the other:
 * it survives a logout into a different account, a wiped `Depot Push Subscription` table,
 * and any bug that drops the row server-side. In that state `getSubscription()` still
 * answers yes, so the gate stays quiet and the profile toggle reads "aktif" — while the
 * server holds nothing for this device and no code path ever offers to register it again.
 * The phone is then permanently silent, and the same person's OTHER phone still rings,
 * which is what makes it look like a routing problem rather than a missing row.
 *
 * So re-register on every read. `subscribe` is an upsert keyed by the endpoint, needs no
 * permission prompt, and is one request per app load.
 */
export async function refreshPushState() {
	state.supported = pushSupported()
	if (!state.supported) return state
	state.permission = Notification.permission
	try {
		const reg = await swReady()
		const subscription = await reg.pushManager.getSubscription()
		state.subscribed = !!subscription
		if (subscription) {
			// Swallowed: a network blip here must not report the device as unsubscribed
			// and drag the gate up over a working phone. The next load retries.
			await api("subscribe", { subscription: subscription.toJSON(), muted: mutedEvents(session.user) }).catch(() => {})
		}
	} catch (e) {
		state.subscribed = false
	}
	return state
}

// Skipping is a pause, never a decision. A browser or a deployment that genuinely cannot
// subscribe must not take someone's shift with it, but a phone that CAN ring has to be
// asked again — an operator who skips once still misses every job until push is on.
//
// So the snooze is deliberately weak in two ways at once:
//   - sessionStorage, so closing the app and reopening it brings the gate straight back;
//   - plus a short time cap, so a handset that is never closed is asked again within
//     half an hour.
//
// `depot.push.gateOff` = "1" is the one permanent opt-out, in localStorage and set from
// the console: for a dev machine or a site that will never have push. An operator never
// finds it.
// ponytail: two storage keys, no server-side preference until someone asks who skipped
const GATE_OFF_KEY = "depot.push.gateOff"
const GATE_SNOOZE_KEY = "depot.push.gateSnoozeUntil"
export const GATE_SNOOZE_MS = 30 * 60 * 1000

function gateSnoozed() {
	try {
		if (localStorage.getItem(GATE_OFF_KEY) === "1") return true
		return Date.now() < (parseInt(sessionStorage.getItem(GATE_SNOOZE_KEY), 10) || 0)
	} catch (e) {
		return false // private mode has no memory, so the gate stays on
	}
}

/** Pause the gate for GATE_SNOOZE_MS, this app session only. Called by the skip button. */
export function snoozePushGate() {
	try {
		sessionStorage.setItem(GATE_SNOOZE_KEY, String(Date.now() + GATE_SNOOZE_MS))
	} catch (e) {
		/* nothing to remember; the gate comes back on the next check */
	}
}

/**
 * Should this device be blocked until notifications are on?
 *
 * Only when a push actually could arrive: a browser that supports it AND a server that
 * holds VAPID keys. Without the key check a bench with push unconfigured would lock every
 * operator out of the app over a switch that can never flip.
 */
export async function pushGateNeeded() {
	if (!pushSupported()) return false
	if (gateSnoozed()) return false
	state.supported = true
	state.permission = Notification.permission

	const cfg = await api("get_config").catch(() => null)
	if (!cfg?.enabled || !cfg.public_key) return false

	// Permission first, and deliberately WITHOUT refreshPushState: that one waits on
	// `serviceWorker.ready`, which on a failed registration only gives up after
	// SW_READY_TIMEOUT_MS — ten seconds of the normal app on screen before the gate
	// appears. Nothing about an unanswered permission needs the worker.
	if (state.permission !== "granted") return true

	// Granted: the only open question is whether a subscription still exists, and that
	// does need the worker.
	await refreshPushState()
	return !state.subscribed
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

		const reg = await swReady()
		// An existing subscription is reused: re-subscribing with the same key returns the
		// same endpoint anyway, and unsubscribing first would drop pushes in between.
		const subscription =
			(await reg.pushManager.getSubscription()) ||
			(await reg.pushManager.subscribe({
				userVisibleOnly: true,
				applicationServerKey: urlBase64ToUint8Array(cfg.public_key),
			}))

		await api("subscribe", { subscription: subscription.toJSON(), muted: mutedEvents(session.user) })
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

/**
 * Kirim push percobaan ke PERANGKAT INI. Mengembalikan jumlah perangkat terkirim (0/1).
 *
 * Endpoint-nya dikirim supaya yang diuji adalah HP yang menekan tombolnya. Tanpa itu
 * server mengirim ke semua perangkat orang tersebut, jadi HP kedua yang belum terdaftar
 * tetap membaca "terkirim" karena HP pertama yang berbunyi.
 */
export async function testPush() {
	state.busy = true
	state.error = null
	try {
		const reg = await swReady()
		const subscription = await reg.pushManager.getSubscription()
		const res = await api("send_test", { endpoint: subscription?.endpoint || "" })
		if (res?.error) throw new Error(res.error)
		return res?.sent ?? 0
	} catch (e) {
		state.error = e.message || String(e)
		return null
	} finally {
		state.busy = false
	}
}

/** Drop this device's registration, server-side and in the browser. */
export async function disablePush() {
	state.busy = true
	state.error = null
	try {
		const reg = await swReady()
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
