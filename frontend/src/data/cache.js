// The read half of working offline.
//
// Saving is online-only now (data/send.js), and this is what keeps the app usable anyway:
// every screen in the PWA starts with a worklist fetched from the server, and without a
// cached answer an operator standing in a dead spot sees an empty list and cannot even read
// what they were working on. Showing the last known list is not a promise that anything can
// be saved — the banner says exactly that — it is the difference between a usable screen and
// a blank one.
//
// So each successful worklist / detail GET is kept, and replayed when the same call cannot
// reach the server. Deliberately last-answer-wins per (endpoint, params) rather than a
// general HTTP cache: these are a handful of small JSON documents, and the store stays
// readable and prunable.
//
// Two rules this file will not bend:
//
//   * Only a request that got NO answer is served from cache. A server that replied "you may
//     not do that" is a real answer and must reach the operator — quietly showing yesterday's
//     data instead would turn a permission error into a silent wrong screen.
//   * Cache entries are scoped to the logged-in user. Depot handsets get passed between
//     shifts, and one operator's branch-scoped worklist must never surface under another's
//     login.

import { createResource } from "frappe-ui"

import { STORE_READS, idbDelete, idbGet, idbGetAll, idbPut } from "@/utils/idb"
import { sessionUser } from "@/data/session"
import { noteLinkDown, noteLinkUp } from "@/data/link"

// A worklist is worth showing a day later ("these are the tanks I was working"). A week later
// it is fiction. Pruned on startup.
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000
// Paged and searched lists mint a key per (page, search term), so the store would otherwise
// grow with every distinct query an operator ever typed. Newest kept.
const MAX_ENTRIES = 300

const keyFor = (name, params) => `${sessionUser() || "?"}|${name}|${JSON.stringify(params || {})}`

/**
 * Did this request fail without ever reaching the application?
 *
 * frappe-ui hands back a bare fetch TypeError when the transport failed, and an error with
 * `.response` attached when the server replied. That distinction is the whole test.
 *
 * The gateway statuses count as "never reached it": 502/503/504 come from the proxy, meaning
 * the app itself never got the request. A plain **500 does not** — that is the application
 * answering, badly, and it is a bug someone needs to see. Papering over it with yesterday's
 * worklist would hide the bug from the operator and from whoever has to fix it.
 */
const GATEWAY = new Set([502, 503, 504])

export function looksOffline(err) {
	const status = err?.response?.status
	if (status === undefined) return true
	return GATEWAY.has(status)
}

export async function readCached(name, params) {
	try {
		const row = await idbGet(STORE_READS, keyFor(name, params))
		return row ? { data: row.data, saved_at: row.saved_at } : null
	} catch {
		return null
	}
}

export async function writeCached(name, params, data) {
	try {
		await idbPut(STORE_READS, { key: keyFor(name, params), data, saved_at: Date.now() })
	} catch {
		/* best effort: a read that cannot be cached still rendered fine just now */
	}
}

/**
 * `createResource` for a GET, with its last good answer kept and replayed when offline.
 *
 * Drop-in: same options, same object back, and `onSuccess` is what runs in both cases — the
 * page fills its refs from cached data exactly as it does from fresh data, so there is no
 * second rendering path that only executes on the worst day.
 *
 * `res.fromCache` says which one the operator is looking at.
 */
export function cachedResource(options) {
	const name = options.offlineKey || options.url
	const { onSuccess, onError, onFetch, ...rest } = options
	// frappe-ui runs onSuccess INSIDE the same try/catch as the request, so an exception
	// thrown by page code while rendering the response arrives at onError looking exactly
	// like a transport failure. Without this flag the cache would answer a bug in our own
	// code by quietly re-running that code over older data — hiding the bug and applying the
	// same payload twice. Reset per fetch by onFetch, which frappe-ui calls before the
	// request goes out.
	let responded = false
	let res

	res = createResource({
		...rest,
		onFetch(params) {
			responded = false
			onFetch?.call(this, params)
		},
		onSuccess(data) {
			responded = true
			res.fromCache = false
			res.cachedAt = null
			noteLinkUp() // a GET that landed is the cheapest proof the link is back
			writeCached(name, res.params, data)
			onSuccess?.call(this, data)
		},
		async onError(err) {
			const offline = !responded && looksOffline(err)
			// Tell the app before anything else. A screen serving yesterday's worklist under a
			// header that says everything is fine is worse than an error message.
			if (offline) noteLinkDown()
			const cached = offline ? await readCached(name, res.params) : null
			if (!cached) {
				onError?.call(this, err)
				return
			}
			res.fromCache = true
			res.cachedAt = cached.saved_at
			// Clear the error: the screen is not in a failed state, it is showing older data,
			// and leaving `res.error` set makes every `v-if="res.error"` in the app lie.
			res.error = null
			onSuccess?.call(this, cached.data)
		},
	})

	// Public, for a screen that wants to say which one the operator is looking at. The
	// app-wide offline banner in App.vue covers the common case, so most pages ignore these.
	res.fromCache = false
	res.cachedAt = null
	return res
}

/** Drop cached answers nobody came back to, and everything belonging to a previous login. */
export async function pruneReads() {
	try {
		const cutoff = Date.now() - MAX_AGE_MS
		const mine = `${sessionUser() || "?"}|`
		const kept = []
		for (const row of (await idbGetAll(STORE_READS)) || []) {
			const expired = (row.saved_at || 0) < cutoff
			const someoneElse = !String(row.key).startsWith(mine)
			if (expired || someoneElse) await idbDelete(STORE_READS, row.key)
			else kept.push(row)
		}
		// Then the count cap, newest kept. This store is a convenience — nothing here is
		// work the operator is waiting on, so pruning it can never lose anything.
		kept.sort((a, b) => (b.saved_at || 0) - (a.saved_at || 0))
		for (const row of kept.slice(MAX_ENTRIES)) await idbDelete(STORE_READS, row.key)
	} catch {
		/* best effort */
	}
}
