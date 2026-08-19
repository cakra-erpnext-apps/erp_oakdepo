// Tiny global toast bus for the Depot PWA — ephemeral feedback for submits/saves
// and errors. Import `toast` anywhere and call `toast.success("…")`; the single
// <ToastHost> mounted in App.vue renders the stack. An optional short beep (Web
// Audio, no asset) plays per toast; the preference is remembered in localStorage.
//
// Work in progress gets a toast too: `toast.busy("Mengunggah foto 1/3…")` shows a
// spinner and stays put until something replaces it, so the operator can see that a
// save is actually moving rather than guessing at a frozen button. Pass the same
// `key` to a later toast and it REPLACES that one in place instead of stacking a
// second card — how a "Menyimpan… → Tersimpan" pair is one toast that changes, and
// how a debounced autosave firing every second never builds a tower of cards.
//
// One card is still one card too many when the work was never slow. A busy toast may
// carry a `delay`: it is only scheduled, and paints only if the save is STILL running
// when the delay is up (same idea as utils/deferredShow.js for skeletons). A surveyor
// typing a note fires an autosave every second and, on a link that is behaving, sees
// nothing at all; when the link drags, the toast appears and stays until it lands.
// A "Tersimpan" is likewise only worth saying if a "Menyimpan…" was ever shown —
// `saveToast.done()` stays quiet otherwise, so nothing flashes for a save that was
// instant.
import { ref } from "vue"

import { labels } from "@/utils/labels"

export const toasts = ref([])
let seq = 0

// id -> auto-dismiss timer, so replacing a toast can cancel the old one's countdown.
const timers = new Map()

// key -> a busy toast waiting out its `delay`, not painted yet: { timer, message, opts }.
// Cancelled if the work finishes first, which is the whole point.
const pending = new Map()

const SOUND_KEY = "oak_toast_sound"
const soundOn = ref(readSound())
function readSound() {
	try {
		return localStorage.getItem(SOUND_KEY) !== "off"
	} catch (e) {
		return true
	}
}

export function toastSoundOn() {
	return soundOn.value
}
export function setToastSound(on) {
	soundOn.value = !!on
	try {
		localStorage.setItem(SOUND_KEY, on ? "on" : "off")
	} catch (e) {
		/* ignore */
	}
}

// Short synthesized chime so we don't ship an audio file. Best-effort: browsers
// block audio until the first user gesture, which submits/taps already satisfy.
function play(type) {
	if (!soundOn.value) return
	try {
		const AudioCtx = window.AudioContext || window.webkitAudioContext
		if (!AudioCtx) return
		const ctx = new AudioCtx()
		const o = ctx.createOscillator()
		const g = ctx.createGain()
		o.connect(g)
		g.connect(ctx.destination)
		const now = ctx.currentTime
		o.type = "sine"
		if (type === "error") {
			o.frequency.setValueAtTime(330, now)
			o.frequency.setValueAtTime(247, now + 0.13)
		} else if (type === "success") {
			o.frequency.setValueAtTime(660, now)
			o.frequency.setValueAtTime(880, now + 0.11)
		} else {
			o.frequency.setValueAtTime(520, now)
		}
		g.gain.setValueAtTime(0.0001, now)
		g.gain.exponentialRampToValueAtTime(0.07, now + 0.02)
		g.gain.exponentialRampToValueAtTime(0.0001, now + 0.3)
		o.start(now)
		o.stop(now + 0.32)
		o.onended = () => ctx.close()
	} catch (e) {
		/* ignore audio failures */
	}
}

export function dismiss(id) {
	const timer = timers.get(id)
	if (timer) clearTimeout(timer)
	timers.delete(id)
	toasts.value = toasts.value.filter((t) => t.id !== id)
}

/** Clear whatever currently occupies `key`, if anything. Used to end a busy toast quietly. */
export function dismissKey(key) {
	cancelPending(key)
	const t = toasts.value.find((x) => x.key === key)
	if (t) dismiss(t.id)
}

function cancelPending(key) {
	const p = key && pending.get(key)
	if (!p) return
	clearTimeout(p.timer)
	pending.delete(key)
}

const visible = (key) => toasts.value.find((t) => t.key === key)

/**
 * A busy toast that holds back for `opts.delay` ms. Work that finishes inside the delay
 * never paints anything; work still running when it expires gets the card. While waiting,
 * later calls only update the message that WILL be shown, so the photo counter is already
 * at "3/5" by the time the operator sees it.
 */
function busyLater(message, opts) {
	const { key, delay } = opts
	// The delay is spent by the time we get here; hand the toast on without it, or `push`
	// would route it straight back into this function.
	const now = { ...opts, delay: 0 }
	const current = visible(key)
	// Already spinning: this is the same work moving on, so update it in place at once.
	// A stale success still sitting in the slot is left to expire on its own.
	if (current?.type === "busy") return push("busy", message, now)
	const waiting = pending.get(key)
	if (waiting) {
		waiting.message = message
		return null
	}
	const timer = setTimeout(() => {
		const p = pending.get(key)
		pending.delete(key)
		if (p) push("busy", p.message, now)
	}, delay)
	pending.set(key, { timer, message })
	return null
}

function push(type, message, opts = {}) {
	if (!message) return null
	const busy = type === "busy"
	if (busy && opts.key && opts.delay) return busyLater(message, opts)
	// Anything that lands in the slot wins over a busy toast still waiting to paint —
	// otherwise the delayed spinner would appear a moment AFTER the result it belongs to.
	cancelPending(opts.key)
	// A keyed toast reuses its card: same id, so the stack does not re-animate and the
	// operator reads one line changing rather than two cards arguing.
	const existing = opts.key ? toasts.value.find((t) => t.key === opts.key) : null
	const t = existing || { id: ++seq, key: opts.key || "" }
	t.type = type
	t.message = message
	t.title = opts.title || ""
	if (!existing) toasts.value.push(t)

	const timer = timers.get(t.id)
	if (timer) clearTimeout(timer)
	timers.delete(t.id)
	// A busy toast has no countdown: it ends when the work does.
	if (!busy) {
		const ttl = opts.duration ?? (type === "error" ? 5000 : 3500)
		timers.set(t.id, setTimeout(() => dismiss(t.id), ttl))
	}
	if (!busy && !opts.silent) play(type)
	return t.id
}

export const toast = {
	success: (message, opts) => push("success", message, opts),
	error: (message, opts) => push("error", message, opts),
	info: (message, opts) => push("info", message, opts),
	/**
	 * Work in flight. Never expires on its own — replace it by key, or dismissKey().
	 * With `{ key, delay }` it only paints if the work outlives the delay.
	 */
	busy: (message, opts) => push("busy", message, opts),
}

// --- autosave slot ----------------------------------------------------------

// Autosave fires on a debounce while the operator is still typing, so it gets ONE
// reserved slot, no chime, and a delay: a save that lands quickly says nothing at all,
// and the form's own inline "Menyimpan…/Tersimpan" line covers that case. Only a save
// that is actually dragging is worth a toast — and then its "Tersimpan" is worth
// showing, because the operator was left waiting for it.
const SAVE_KEY = "autosave"

// Longer than a healthy round trip on the depot's wifi (~200 ms) and longer than the
// forms' 700-1200 ms debounce is fast, so continuous typing on a link that is behaving
// paints nothing.
const SAVE_DELAY_MS = 900

export const saveToast = {
	start: (message) => toast.busy(message || labels.savingDraft, { key: SAVE_KEY, delay: SAVE_DELAY_MS }),
	/** Landed. Says "Tersimpan" only if the operator was ever told it was saving. */
	done(message) {
		if (!visible(SAVE_KEY)) {
			cancelPending(SAVE_KEY)
			return null
		}
		return toast.success(message || labels.draftSaved, { key: SAVE_KEY, silent: true, duration: 1500 })
	},
	/** Failed: show `message` in the same slot, or just clear it when there is nothing to say. */
	fail: (message) => (message ? toast.error(message, { key: SAVE_KEY }) : dismissKey(SAVE_KEY)),
	close: () => dismissKey(SAVE_KEY),
}
