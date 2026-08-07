import { computed, reactive } from "vue"

// Which of the nine PWA menus this user may open, resolved server-side from their
// DocPerms (container_depot.ess.context.get_menu). Fetched once per app load and cached
// here so the router guard can decide synchronously on every navigation instead of
// awaiting a round-trip per route.
//
// No role name appears anywhere in this file, and none should: the server answers with
// menu keys, so adding a role or re-pointing a permission never touches the frontend.
// This is presentation only — every endpoint re-checks on its own (ess/guard.py).

const state = reactive({
	keys: null, // null = not fetched yet; [] = fetched, nothing allowed
	deskAccess: false, // may this user open /desk? drives the "Buka Desk" shortcut
	loading: false,
	error: null,
})

let inflight = null

export function fetchMenu() {
	if (state.keys !== null) return Promise.resolve(state.keys)
	if (inflight) return inflight
	state.loading = true
	inflight = fetch("/api/method/container_depot.ess.context.get_menu", {
		headers: { Accept: "application/json" },
	})
		.then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
		.then((body) => {
			state.keys = body?.message?.menu || []
			state.deskAccess = !!body?.message?.desk_access
			state.error = null
			return state.keys
		})
		.catch((e) => {
			// Fail closed on the UI side: an unreadable menu shows the empty state rather
			// than every tile. The tiles would 403 on tap anyway; a wrong menu is worse
			// than an empty one because it looks like the app is broken, not restricted.
			// desk_access stays false for the same reason — /desk would just bounce them.
			state.keys = []
			state.deskAccess = false
			state.error = e
			return state.keys
		})
		.finally(() => {
			state.loading = false
			inflight = null
		})
	return inflight
}

export const menu = reactive({
	keys: computed(() => state.keys || []),
	ready: computed(() => state.keys !== null),
	loading: computed(() => state.loading),
	error: computed(() => state.error),
	isEmpty: computed(() => state.keys !== null && state.keys.length === 0),
	deskAccess: computed(() => state.deskAccess),
	has: (key) => (state.keys || []).includes(key),
})
