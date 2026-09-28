// PWA display language: Indonesian (default) or English.
//
// Read ONCE at startup and never changed in place. Switching reloads the app instead of
// trying to re-render: dozens of screens copy `labels` values into constants at import or
// mount time, and a reload is the only switch that reaches every one of them.
//
// Stored per user on the server (container_depot/depot_lang.py) and handed over in the page
// boot, so it follows the operator across handsets and notifications use it too.
// localStorage is only the fallback for `vite dev`, where there is no server-rendered boot.
// The server learns it per request through the `X-Depot-Lang` header on every /api call
// (see installLangHeader), so error messages and master data (EIR checklist, damage/repair
// codes…) come back in the same language. The Desk is not affected: it never sends it.

const KEY = "oak-lang"

function read() {
	const boot = window.frappe?.boot?.depot_lang
	if (boot) return boot === "en" ? "en" : "id"
	try {
		return localStorage.getItem(KEY) === "en" ? "en" : "id"
	} catch {
		return "id"
	}
}

export const LANG = read()
// BCP-47 tag for Intl / toLocale*String.
export const LOCALE = LANG === "en" ? "en-GB" : "id-ID"

export async function setLang(lang) {
	if (lang === LANG) return
	try {
		localStorage.setItem(KEY, lang)
	} catch {
		// Private mode / blocked storage: the server copy below still carries it.
	}
	const res = await fetch("/api/method/container_depot.ess.profile.set_language", {
		method: "POST",
		headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": window.csrf_token || "" },
		body: JSON.stringify({ lang }),
	})
	if (!res.ok) throw new Error((await res.json().catch(() => ({})))._server_messages || res.statusText)
	location.reload()
}

// ponytail: one fetch wrapper instead of a header at each of the ~9 call paths
// (frappe-ui resources, send.js, raw fetches). Same-origin /api only.
export function installLangHeader() {
	document.documentElement.lang = LANG
	const orig = window.fetch.bind(window)
	window.fetch = (input, init = {}) => {
		const url = new URL(input instanceof Request ? input.url : String(input), location.href)
		if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return orig(input, init)
		const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined))
		headers.set("X-Depot-Lang", LANG)
		return orig(input, { ...init, headers })
	}
}
