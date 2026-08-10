// Minimal promise wrapper over IndexedDB — three stores, no dependency.
//
// IndexedDB rather than localStorage, and the difference is not a preference: localStorage
// caps at ~5 MB per origin, stores strings only (a photo has to be base64'd, +33%), and is
// synchronous, so writing a few MB visibly freezes the UI. One 12 MP phone photo is 3-8 MB
// — it would blow the whole localStorage budget on its own. IndexedDB takes Blobs natively,
// is async, and is allowed a share of free disk measured in hundreds of MB.
//
//   blobs   — the picked photos, kept as Blobs until they reach the server. Deleted the
//             moment an upload returns a file_url, because the URL is durable by then.
//   outbox  — queued work, one row per document save (see data/outbox.js).
//   drafts  — what the operator has typed, saved as they type. This one is not about the
//             network at all: it is what survives a killed tab or a flat battery.

const DB_NAME = "oak-depot"
const DB_VERSION = 1

export const STORE_BLOBS = "blobs"
export const STORE_OUTBOX = "outbox"
export const STORE_DRAFTS = "drafts"

let dbPromise = null

function open() {
	if (dbPromise) return dbPromise
	dbPromise = new Promise((resolve, reject) => {
		if (!("indexedDB" in window)) {
			reject(new Error("IndexedDB unavailable"))
			return
		}
		const req = indexedDB.open(DB_NAME, DB_VERSION)
		req.onupgradeneeded = () => {
			const db = req.result
			if (!db.objectStoreNames.contains(STORE_BLOBS)) db.createObjectStore(STORE_BLOBS, { keyPath: "id" })
			if (!db.objectStoreNames.contains(STORE_OUTBOX)) db.createObjectStore(STORE_OUTBOX, { keyPath: "id" })
			if (!db.objectStoreNames.contains(STORE_DRAFTS)) db.createObjectStore(STORE_DRAFTS, { keyPath: "key" })
		}
		req.onsuccess = () => resolve(req.result)
		req.onerror = () => reject(req.error)
	}).catch((e) => {
		// Do not memoise a failure: a private-mode window can refuse IndexedDB on one call
		// and allow it on the next, and a permanently poisoned promise would take the whole
		// offline queue down with it.
		dbPromise = null
		throw e
	})
	return dbPromise
}

function run(store, mode, fn) {
	return open().then(
		(db) =>
			new Promise((resolve, reject) => {
				const tx = db.transaction(store, mode)
				const req = fn(tx.objectStore(store))
				tx.onabort = () => reject(tx.error)
				// Resolve on the TRANSACTION, not the request: a write is only durable once
				// the transaction commits, and resolving early would let the caller delete a
				// blob whose queue row had not landed yet.
				tx.oncomplete = () => resolve(req ? req.result : undefined)
				tx.onerror = () => reject(tx.error)
			})
	)
}

export const idbGet = (store, key) => run(store, "readonly", (s) => s.get(key))
export const idbGetAll = (store) => run(store, "readonly", (s) => s.getAll())
export const idbPut = (store, value) => run(store, "readwrite", (s) => s.put(value))
export const idbDelete = (store, key) => run(store, "readwrite", (s) => s.delete(key))
export const idbClear = (store) => run(store, "readwrite", (s) => s.clear())

export function uid() {
	if (window.crypto?.randomUUID) return window.crypto.randomUUID()
	// Older WebViews — some depot handsets are not current. Random enough for a queue key.
	return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * Ask the browser to stop treating our storage as disposable.
 *
 * A "best-effort" origin can have its IndexedDB evicted when the device runs low on space —
 * exactly when the outbox is fullest and the work in it is least replaceable. Best-effort,
 * silent: Chrome grants it to installed PWAs, Firefox prompts, Safari ignores it.
 */
export async function requestPersistentStorage() {
	try {
		if (navigator.storage?.persist && !(await navigator.storage.persisted())) {
			await navigator.storage.persist()
		}
	} catch {
		/* storage stays best-effort; the queue still works, it is just evictable */
	}
}

/** Bytes still available to this origin, or null when the browser will not say. */
export async function storageHeadroom() {
	try {
		const { quota, usage } = (await navigator.storage?.estimate?.()) || {}
		if (typeof quota !== "number" || typeof usage !== "number") return null
		return Math.max(0, quota - usage)
	} catch {
		return null
	}
}
