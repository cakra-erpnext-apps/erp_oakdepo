// Autosave for what the operator has typed.
//
// Nothing to do with the network — this is the answer to a tab the OS killed to reclaim
// memory, a browser closed by accident, a flat battery. An EIR checklist is a hundred small
// decisions taken in a hot yard; asking for them twice is the fastest way to lose the
// operator's trust in the app.
//
// Kept apart from the outbox on purpose. A draft is disposable (its contents are still on
// screen), so it is safe to prune on age. An outbox row is work the operator believes is
// already sent, and is never dropped by a timer.

import { STORE_DRAFTS, idbDelete, idbGet, idbPut, idbGetAll } from "@/utils/idb"

const SAVE_DEBOUNCE_MS = 800
const MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000

const timers = new Map()

/** Save `data` under `key`, coalescing the bursts a form emits while someone types. */
export function saveDraft(key, data) {
	clearTimeout(timers.get(key))
	timers.set(
		key,
		setTimeout(() => {
			timers.delete(key)
			idbPut(STORE_DRAFTS, { key, data, saved_at: Date.now() }).catch(() => {
				/* best effort: a failed autosave must never interrupt the form */
			})
		}, SAVE_DEBOUNCE_MS)
	)
}

/** The stored draft for `key`, or null. */
export async function loadDraft(key) {
	try {
		const row = await idbGet(STORE_DRAFTS, key)
		return row?.data ?? null
	} catch {
		return null
	}
}

export async function clearDraft(key) {
	clearTimeout(timers.get(key))
	timers.delete(key)
	try {
		await idbDelete(STORE_DRAFTS, key)
	} catch {
		/* nothing to clean up */
	}
}

/** Drop drafts nobody came back to. Cheap, and keeps the store from growing for ever. */
export async function pruneDrafts() {
	try {
		const cutoff = Date.now() - MAX_AGE_MS
		for (const row of (await idbGetAll(STORE_DRAFTS)) || []) {
			if ((row.saved_at || 0) < cutoff) await idbDelete(STORE_DRAFTS, row.key)
		}
	} catch {
		/* best effort */
	}
}
