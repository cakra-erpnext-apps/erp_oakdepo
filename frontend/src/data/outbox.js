// The offline outbox: work the operator has finished, waiting for a network to leave on.
//
// One row per document save. A row is an ATOMIC unit — its photos upload first, their real
// file_urls are substituted into the payload, and only then does the document save go out.
// Splitting photos and save into separate queue entries would let the uploads succeed while
// the save never does, leaving orphan files on the server and a form the operator believes
// was sent.
//
// Progress inside a row is durable: each photo's URL is written back into the stored payload
// as soon as it lands, so a connection that dies after two of three photos does not re-upload
// those two on the next attempt. On the yard's 3G that is the difference between finishing
// and never finishing.
//
// Every row carries a `request_id`, and the server remembers it (ess/idempotency.py). This
// is not belt-and-braces — it is the whole reason a retry queue is safe. The dangerous case
// is not being offline, it is LAG: the save reaches the server, the response is lost on the
// way back, and a naive retry raises a second EIR. The id is what makes the retry return the
// first result instead.

import { computed, reactive } from "vue"

import {
	STORE_BLOBS,
	STORE_OUTBOX,
	idbDelete,
	idbGet,
	idbGetAll,
	idbPut,
	requestPersistentStorage,
	storageHeadroom,
	uid,
} from "@/utils/idb"

const LOCAL_PREFIX = "local:"
const MAX_ATTEMPTS = 8
const RETRY_MS = 30_000
// Keep the queue well inside any plausible quota. Hitting a QuotaExceededError mid-write is
// how a queue loses work; refusing early with a message the operator can act on is not.
const MAX_ROWS = 60

const state = reactive({
	rows: [],          // queued jobs, oldest first
	sending: false,
	online: navigator.onLine !== false,
	sessionExpired: false,
	lastError: null,
})

export const outbox = reactive({
	pending: computed(() => state.rows.filter((r) => r.state !== "failed").length),
	failed: computed(() => state.rows.filter((r) => r.state === "failed").length),
	rows: computed(() => state.rows),
	sending: computed(() => state.sending),
	online: computed(() => state.online),
	sessionExpired: computed(() => state.sessionExpired),
	lastError: computed(() => state.lastError),
})

// --- blobs ------------------------------------------------------------------

// Object URLs for the stashed photos, so a template can render a queued photo with the same
// `:src` it uses for an uploaded one. Rebuilt from IndexedDB by `hydratePreviews` after a
// reload, because object URLs die with the document that made them.
const previews = reactive({})

/** Park a picked photo locally and return the placeholder that stands in for its URL. */
export async function stashPhoto(file) {
	const id = uid()
	await idbPut(STORE_BLOBS, { id, blob: file, name: file.name || "photo.jpg", created_at: Date.now() })
	const ref = `${LOCAL_PREFIX}${id}`
	previews[ref] = URL.createObjectURL(file)
	return ref
}

export const isLocalRef = (url) => typeof url === "string" && url.startsWith(LOCAL_PREFIX)

/** Render a photo reference: a server file_url passes through, a stashed one resolves. */
export function photoSrc(ref) {
	if (!isLocalRef(ref)) return ref
	return previews[ref] || ""
}

/** Re-open object URLs for `refs` after a reload, so a restored draft shows its photos. */
export async function hydratePreviews(refs) {
	for (const ref of refs || []) {
		if (!isLocalRef(ref) || previews[ref]) continue
		try {
			const row = await idbGet(STORE_BLOBS, ref.slice(LOCAL_PREFIX.length))
			if (row) previews[ref] = URL.createObjectURL(row.blob)
		} catch {
			/* a blob that will not load simply renders as a gap */
		}
	}
}

// --- queue ------------------------------------------------------------------

/**
 * Queue a document save. Returns the row id.
 *
 * `payload` may contain `local:<id>` placeholders anywhere; they are replaced with real
 * file_urls at flush time.
 */
export async function enqueue({ kind, url, payload }) {
	await load()
	if (state.rows.length >= MAX_ROWS) {
		throw new Error(`Antrean penuh (${MAX_ROWS} item). Sambungkan internet dulu untuk mengirimnya.`)
	}
	const row = {
		id: uid(),
		kind,
		url,
		payload,
		refs: collectLocalRefs(payload),
		attempts: 0,
		state: "pending",
		error: null,
		created_at: Date.now(),
	}
	await idbPut(STORE_OUTBOX, row)
	state.rows.push(row)
	requestPersistentStorage()
	flush()
	return row.id
}

async function load() {
	if (state.rows.length) return
	try {
		const rows = await idbGetAll(STORE_OUTBOX)
		state.rows = (rows || []).sort((a, b) => a.created_at - b.created_at)
	} catch {
		state.rows = []
	}
}

/** Send everything queued, oldest first. Safe to call at any time; re-entrant calls no-op. */
export async function flush() {
	if (state.sending || !state.online) return
	await load()
	const due = state.rows.filter((r) => r.state !== "failed")
	if (!due.length) return

	state.sending = true
	try {
		for (const row of due) {
			// Strictly in order. A later EIR may reference a file the earlier one uploaded,
			// and jumping the queue on a flaky link produces the confusing case where work
			// lands out of sequence.
			const ok = await sendRow(row)
			if (!ok) break
		}
	} finally {
		state.sending = false
	}
}

async function sendRow(row) {
	row.state = "sending"
	try {
		for (const ref of [...row.refs]) {
			const fileUrl = await uploadStashed(ref)
			row.payload = substitute(row.payload, ref, fileUrl)
			row.refs = row.refs.filter((r) => r !== ref)
			// Persist after EVERY photo: this is what makes a half-finished upload set
			// survive the connection dropping.
			await idbPut(STORE_OUTBOX, { ...row, state: "pending" })
			await idbDelete(STORE_BLOBS, ref.slice(LOCAL_PREFIX.length))
		}

		await post(row.url, { ...row.payload, request_id: row.id })
		await idbDelete(STORE_OUTBOX, row.id)
		state.rows = state.rows.filter((r) => r.id !== row.id)
		state.lastError = null
		return true
	} catch (e) {
		return await handleFailure(row, e)
	}
}

async function handleFailure(row, e) {
	row.attempts += 1
	row.error = e?.message || String(e)
	state.lastError = row.error

	if (e?.name === "SessionExpired") {
		// Do NOT burn an attempt budget on this: the work is fine, the credential is not.
		// Silently dropping the queue here would lose a day's inspections.
		row.attempts -= 1
		row.state = "pending"
		state.sessionExpired = true
		await idbPut(STORE_OUTBOX, { ...row })
		return false
	}
	if (e?.name === "Offline") {
		row.attempts -= 1
		row.state = "pending"
		state.online = false
		await idbPut(STORE_OUTBOX, { ...row })
		return false
	}
	// A validation error will fail identically forever. Park it as `failed` so it stops
	// blocking the rows behind it, and show it — a queue that silently retries a poison
	// row for ever looks exactly like a queue that is working.
	const poison = e?.name === "Rejected" || row.attempts >= MAX_ATTEMPTS
	row.state = poison ? "failed" : "pending"
	await idbPut(STORE_OUTBOX, { ...row })
	// Parked rows step aside so the queue behind them still moves; anything else means the
	// link is unhealthy, so stop and let the retry timer try the whole queue again later.
	return poison
}

/** Put a failed row back in the queue — the operator's manual retry. */
export async function retryRow(id) {
	const row = state.rows.find((r) => r.id === id)
	if (!row) return
	row.state = "pending"
	row.attempts = 0
	row.error = null
	await idbPut(STORE_OUTBOX, { ...row })
	flush()
}

/** Give up on a row, and on its un-uploaded photos with it. */
export async function discardRow(id) {
	const row = state.rows.find((r) => r.id === id)
	if (row) {
		for (const ref of row.refs || []) await idbDelete(STORE_BLOBS, ref.slice(LOCAL_PREFIX.length))
	}
	await idbDelete(STORE_OUTBOX, id)
	state.rows = state.rows.filter((r) => r.id !== id)
}

// --- transport --------------------------------------------------------------

async function uploadStashed(ref) {
	const id = ref.slice(LOCAL_PREFIX.length)
	const stored = await idbGet(STORE_BLOBS, id)
	if (!stored) {
		// The blob is gone (evicted, or already uploaded and the substitution lost). Nothing
		// can bring it back, so fail the row loudly rather than saving an EIR with a dangling
		// `local:` reference in it.
		throw named("Rejected", "Foto tidak ditemukan di penyimpanan lokal.")
	}
	const fd = new FormData()
	fd.append("file", stored.blob, stored.name)
	fd.append("is_private", 1)
	fd.append("folder", "Home")
	const res = await request("/api/method/upload_file", { method: "POST", body: fd })
	const data = await res.json()
	return data.message.file_url
}

async function post(url, args) {
	const res = await request(`/api/method/${url}`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(args),
	})
	return res.json()
}

async function request(url, opts) {
	let res
	try {
		res = await fetch(url, {
			...opts,
			headers: { Accept: "application/json", "X-Frappe-CSRF-Token": window.csrf_token || "", ...(opts.headers || {}) },
		})
	} catch (e) {
		// fetch only rejects on a transport failure — exactly the offline / dropped-signal
		// case. Anything the server answered, however badly, lands below.
		throw named("Offline", e?.message || "network unreachable")
	}
	if (res.ok) return res
	if (res.status === 401 || res.status === 403) throw named("SessionExpired", "Sesi berakhir, login lagi.")
	if (res.status >= 500) throw named("Offline", `server ${res.status}`) // transient — keep retrying
	throw named("Rejected", await readError(res))
}

async function readError(res) {
	try {
		const body = await res.json()
		return body._server_messages ? JSON.parse(body._server_messages).map(safeMsg).join(" ") : body.exception || res.statusText
	} catch {
		return res.statusText || `HTTP ${res.status}`
	}
}

function safeMsg(m) {
	try {
		return JSON.parse(m).message
	} catch {
		return m
	}
}

function named(name, message) {
	const e = new Error(message)
	e.name = name
	return e
}

// --- payload helpers --------------------------------------------------------

function collectLocalRefs(value, found = []) {
	if (isLocalRef(value)) {
		if (!found.includes(value)) found.push(value)
	} else if (Array.isArray(value)) {
		value.forEach((v) => collectLocalRefs(v, found))
	} else if (value && typeof value === "object") {
		Object.values(value).forEach((v) => collectLocalRefs(v, found))
	}
	return found
}

function substitute(value, ref, replacement) {
	if (value === ref) return replacement
	if (Array.isArray(value)) return value.map((v) => substitute(v, ref, replacement))
	if (value && typeof value === "object") {
		return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, substitute(v, ref, replacement)]))
	}
	return value
}

// --- lifecycle --------------------------------------------------------------

export function startOutbox() {
	load().then(flush)
	window.addEventListener("online", () => {
		state.online = true
		state.sessionExpired = false
		flush()
	})
	window.addEventListener("offline", () => {
		state.online = false
	})
	// A timer as well as the events: `online` fires when the OS reattaches to a network,
	// which on a depot yard is not the same thing as the network working. The retry is what
	// actually gets the queue out.
	setInterval(() => {
		if (navigator.onLine !== false) state.online = true
		flush()
	}, RETRY_MS)
}

export { storageHeadroom }
