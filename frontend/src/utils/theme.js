// Light / dark, and the third option that is neither: follow the phone.
//
// A depot handset is used at 06:00 in a yard and at 23:00 in a dim office by the same
// operator, and Android/iOS already switch themselves on a schedule the operator set once.
// So "Otomatis" is the default and it TRACKS — a system flip repaints the app live, with no
// reload — while an explicit choice sticks until it is changed back.
//
// The one attribute this file writes, `data-theme` on <html>, is the same one frappe-ui's
// components read, so the imported dialogs/buttons flip with everything else. The colour
// values themselves live in main.css; nothing here knows a single hex.

import { reactive } from "vue"

const KEY = "oak-theme" // "system" | "light" | "dark"
const MODES = ["system", "light", "dark"]

// Kept in step with the pre-paint snippet in index.html: the two must agree, or the app
// repaints a different theme than the one that covered the boot splash. Both read the same
// key and resolve `system` the same way.
const prefersDark = () =>
	typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches

function read() {
	try {
		const saved = localStorage.getItem(KEY)
		return MODES.includes(saved) ? saved : "system"
	} catch {
		// Private mode / storage blocked. Following the OS is the safe answer.
		return "system"
	}
}

export const theme = reactive({
	mode: read(), // what the operator chose
	resolved: "light", // what is actually painted
})

function apply() {
	const dark = theme.mode === "dark" || (theme.mode === "system" && prefersDark())
	theme.resolved = dark ? "dark" : "light"
	document.documentElement.dataset.theme = theme.resolved
	// The browser chrome around the PWA — status bar on Android, the strip behind a notch —
	// is painted from this, and a white bar over a dark app is the most visible way to get a
	// theme half-applied. Values mirror --c-paper in main.css.
	const meta = document.querySelector('meta[name="theme-color"]')
	if (meta) meta.setAttribute("content", dark ? "#17191d" : "#ffffff")
}

export function setTheme(mode) {
	theme.mode = MODES.includes(mode) ? mode : "system"
	try {
		localStorage.setItem(KEY, theme.mode)
	} catch {
		/* best effort: the theme still applies for this session */
	}
	apply()
}

export function initTheme() {
	apply()
	// Only meaningful while the mode is "system", but the listener is registered once and
	// left alone: it is one callback, and re-registering it on every mode change is more
	// moving parts than the branch inside it.
	window.matchMedia?.("(prefers-color-scheme: dark)")?.addEventListener?.("change", () => {
		if (theme.mode === "system") apply()
	})
}
