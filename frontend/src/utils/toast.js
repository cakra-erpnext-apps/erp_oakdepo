// Tiny global toast bus for the Depot PWA — ephemeral feedback for submits/saves
// and errors. Import `toast` anywhere and call `toast.success("…")`; the single
// <ToastHost> mounted in App.vue renders the stack. An optional short beep (Web
// Audio, no asset) plays per toast; the preference is remembered in localStorage.
import { ref } from "vue"

export const toasts = ref([])
let seq = 0

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
	toasts.value = toasts.value.filter((t) => t.id !== id)
}

function push(type, message, opts = {}) {
	if (!message) return null
	const id = ++seq
	toasts.value.push({ id, type, message, title: opts.title || "" })
	const ttl = opts.duration ?? (type === "error" ? 5000 : 3500)
	setTimeout(() => dismiss(id), ttl)
	play(type)
	return id
}

export const toast = {
	success: (message, opts) => push("success", message, opts),
	error: (message, opts) => push("error", message, opts),
	info: (message, opts) => push("info", message, opts),
}
