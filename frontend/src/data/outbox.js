// The offline outbox: work the operator has finished, waiting for a network to leave on.
//
// ONLINE FIRST. With a link, a save goes straight to the server and the operator waits for
// the real answer — that is a few hundred milliseconds, and it is what makes a rejection
// ("that tank still has open work") arrive while they are still standing at the tank rather
// than as a failed row in a panel an hour later. The queue only takes over when the send
// actually fails on the network. It used to be the other way round — everything went into
// IndexedDB and left on the flusher's schedule — and with signal that bought nothing but
// latency, a worklist that reloaded twice per action, and errors that surfaced far too late.
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

import { computed, reactive, watch } from "vue"

import { clearDraft } from "@/data/drafts"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
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

let loaded = false

const state = reactive({
	rows: [],          // queued jobs, oldest first
	sending: false,
	online: navigator.onLine !== false,
	sessionExpired: false,
	lastError: null,
	sent: 0,           // rows that have actually landed on the server (see onOutboxSent)
})

export const outbox = reactive({
	pending: computed(() => state.rows.filter((r) => r.state !== "failed").length),
	failed: computed(() => state.rows.filter((r) => r.state === "failed").length),
	// Of those, the ones refused because the job was already done elsewhere. Counted apart
	// because it changes what the badge should say: news to acknowledge, not a breakage.
	settled: computed(() => state.rows.filter((r) => r.settled).length),
	rows: computed(() => state.rows),
	sending: computed(() => state.sending),
	online: computed(() => state.online),
	sessionExpired: computed(() => state.sessionExpired),
	lastError: computed(() => state.lastError),
	// The documents this queue is still going to act on. Worklists filter on it so a tank the
	// operator just signed off does not sit there looking untouched — which is how the same
	// job gets done twice.
	//
	// Parked (`failed`) rows are deliberately NOT in here. That work is not on its way
	// anywhere, so hiding the job would leave the operator with an order missing from the
	// worklist and no way to redo it — the queue panel would be the only trace. Let it come
	// back into the list; the draft it was made from is still there (see `draft` below), so
	// reopening the form brings the photos and the remarks back with it.
	refs: computed(() => new Set(state.rows.filter((r) => r.state !== "failed").map((r) => r.ref).filter(Boolean))),
})

/** Is there already queued work against this document? */
export const isQueued = (ref) => !!ref && outbox.refs.has(ref)

/**
 * Run `cb` every time a queued row actually lands on the server.
 *
 * Worklists need this. Finishing a job sends the operator back to the list, which refetches
 * immediately — but the queue is still holding the save, so the server answers with the job
 * still open. `outbox.refs` papers over that gap by hiding the row while it is queued; the
 * moment the row drains, the filter stops hiding it and the job the operator just finished
 * pops back into the list looking untouched. That is the same bug the filter exists to
 * prevent, arriving a few seconds later.
 *
 * So the list is refetched when the queue drains, not when it is filled. Called from `setup`,
 * the watcher stops with the component.
 */
export function onOutboxSent(cb) {
	return watch(() => state.sent, cb)
}

// `online` means "we have no evidence the link is down", and every part of the app that
// touches the network reports what it saw. It has to work this way: `navigator.onLine` only
// knows whether the device is attached to a network, which on depot wifi is regularly true
// while nothing can actually be reached — and a screen quietly serving cached data while the
// header insists everything is fine is the exact lie this whole feature exists to avoid.

/** A request found nothing at the other end. Called by the read cache as well as the queue. */
export function noteLinkDown() {
	state.online = false
}

/** Something got through. Any success clears the flag, whoever observed it. */
export function noteLinkUp() {
	if (!state.online && navigator.onLine !== false) {
		state.online = true
		state.sessionExpired = false
		flush()
	}
}

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
 *
 * `ref` names the document being acted on (a Cleaning Order, a container). It is only used to
 * keep worklists honest — see `outbox.refs` — and never reaches the server.
 *
 * `title` is what the queue panel shows the operator. "Cleaning · TANK0000123" is something
 * they can act on; an endpoint path is not.
 *
 * `draft` names the autosaved draft this work came from. The queue clears it once the save
 * has actually landed — never before. A draft dropped at queue time looked tidy right up to
 * the day a row came back refused ("Cleaning Order sudah selesai", closed by someone else
 * while the handset was in a dead spot): the operator's photos and remarks then existed
 * nowhere a screen could reach them.
 */
export async function enqueue({ kind, url, payload, ref = null, title = null, draft = null }) {
	await load()
	const row = {
		id: uid(),
		kind,
		title,
		ref,
		draft,
		url,
		payload,
		refs: collectLocalRefs(payload),
		attempts: 0,
		state: "pending",
		error: null,
		created_at: Date.now(),
	}

	// The fast path, and with signal the only one anybody sees: send it now, wait for the
	// answer, store nothing. Queueing first would mean an IndexedDB write of the whole
	// payload, a worklist that hides the row and then refetches it twice, and — worst of the
	// three — a server refusal the operator does not learn about until later.
	let attempted = false
	if (canSendNow()) {
		const uploadedRefs = []
		attempted = true
		state.sending = true
		try {
			await deliver(row, { persist: false, uploadedRefs })
			await settleDraft(row)
			state.online = true // proof, not a guess: something just got through
			state.lastError = null
			// The server's answer has changed; whatever list is on screen is now stale.
			state.sent += 1
			return row.id
		} catch (e) {
			// A refusal is the server talking, and it will say the same thing on every
			// retry. Hand it to the form, which still has everything on screen and can put
			// it right — queueing a doomed row instead is how these ended up being read an
			// hour later in a panel.
			if (e?.name === "Rejected") throw e
			if (e?.name === "SessionExpired") state.sessionExpired = true
			else state.online = false
			// Anything else means the link went down mid-send. Fall through: the row keeps
			// whatever progress `deliver` made (photos already uploaded are real URLs in the
			// payload now, so their blobs are dead weight) and the queue carries the rest.
			for (const r of uploadedRefs) await dropBlob(r)
			state.lastError = e?.message || String(e)
		} finally {
			state.sending = false
		}
	}

	if (state.rows.length >= MAX_ROWS) {
		throw new Error(`Antrean penuh (${MAX_ROWS} item). Sambungkan internet dulu untuk mengirimnya.`)
	}
	await idbPut(STORE_OUTBOX, row)
	state.rows.push(row)
	requestPersistentStorage()
	// Force the attempt unless one was just made and failed. `online` is a guess held by
	// whatever last touched the network — a GET on another screen may have set it false
	// minutes ago — and with the queue empty nothing else was going to test it. Letting the
	// new row probe the link itself is the difference between going out now and waiting out
	// the retry timer for something that was never actually down.
	flush({ force: !attempted })
	return row.id
}

/**
 * May a new save skip the queue and go straight out?
 *
 * Only with no evidence the link is down, and only with an empty queue: a row that jumped
 * ahead of work already waiting would land out of order, and a later document may depend on
 * an earlier one. Parked (`failed`) rows are not waiting for anything, so they do not block.
 */
function canSendNow() {
	return state.online && !state.sending && !state.rows.some((r) => r.state !== "failed")
}

async function load() {
	if (loaded) return
	loaded = true
	try {
		const rows = await idbGetAll(STORE_OUTBOX)
		state.rows = (rows || []).sort((a, b) => a.created_at - b.created_at)
	} catch {
		state.rows = []
	}
}

/**
 * Send everything queued, oldest first. Safe to call at any time; re-entrant calls no-op.
 *
 * `force` ignores the `online` flag — that flag is a hint, and something has to actually try
 * the network for it ever to be cleared. The retry timer is the one caller that forces.
 */
export async function flush({ force = false } = {}) {
	if (state.sending || (!state.online && !force)) return
	await load()
	if (!state.rows.some((r) => r.state !== "failed")) return

	state.sending = true
	try {
		// Strictly in order. A later EIR may reference a file the earlier one uploaded, and
		// jumping the queue on a flaky link produces the confusing case where work lands out
		// of sequence.
		//
		// The queue is re-read each turn rather than iterated as a snapshot: a row enqueued
		// while this loop was running used to be invisible to it — and its own `flush()` call
		// no-opped on `state.sending` — so it sat untouched until the 30s retry timer came
		// round. On a good link that was a queue that looked broken for half a minute at a
		// time. A sent row leaves the list and a parked one is `failed`, so this always
		// advances.
		for (;;) {
			const row = state.rows.find((r) => r.state !== "failed")
			if (!row) break
			if (!(await sendRow(row))) break
		}
	} finally {
		state.sending = false
	}
}

/**
 * Upload the row's stashed photos, substitute the real URLs into its payload, and post it.
 *
 * `persist` writes the row back to IndexedDB after every photo, which is what lets a
 * connection that dies after two of three uploads resume instead of starting over. A row
 * being sent straight from `enqueue` is not in IndexedDB at all and has nothing to resume —
 * it skips the writes, and its uploaded refs are collected in `uploadedRefs` so the caller
 * can clean up the blobs whichever way the send ends.
 */
async function deliver(row, { persist, uploadedRefs = [] }) {
	for (const ref of [...row.refs]) {
		const fileUrl = await uploadStashed(ref)
		row.payload = substitute(row.payload, ref, fileUrl)
		row.refs = row.refs.filter((r) => r !== ref)
		uploadedRefs.push(ref)
		if (persist) {
			// Persist after EVERY photo: this is what makes a half-finished upload set
			// survive the connection dropping.
			await idbPut(STORE_OUTBOX, { ...row, state: "pending" })
			await dropBlob(ref)
		}
	}
	await post(row.url, { ...row.payload, request_id: row.id })
	// Only now, for a direct send: a blob dropped before the save landed would leave a
	// rejected form holding a `local:` reference to a photo that no longer exists anywhere.
	if (!persist) for (const ref of uploadedRefs) await dropBlob(ref)
}

const dropBlob = (ref) => idbDelete(STORE_BLOBS, ref.slice(LOCAL_PREFIX.length))

/** The save landed, so what the operator typed is on the server now and the draft can go. */
const settleDraft = (row) => (row.draft ? clearDraft(row.draft) : Promise.resolve())

async function sendRow(row) {
	row.state = "sending"
	try {
		await deliver(row, { persist: true })
		await settleDraft(row)
		await idbDelete(STORE_OUTBOX, row.id)
		state.rows = state.rows.filter((r) => r.id !== row.id)
		state.lastError = null
		state.online = true // proof, not a guess: something just got through
		// The server's answer has changed; whatever list is on screen is now stale.
		state.sent += 1
		return true
	} catch (e) {
		return await handleFailure(row, e)
	}
}

async function handleFailure(row, e) {
	row.attempts += 1
	row.error = e?.message || String(e)
	// "Already settled" is not a failure to retry, it is news: the job was finished on the
	// Desk while this row was waiting for a signal. The panel presents it as such.
	row.settled = !!e?.settled
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
	// A validation error will fail identically forever — a settled one most of all. Park it
	// as `failed` so it stops blocking the rows behind it, and show it: a queue that
	// silently retries a poison row for ever looks exactly like a queue that is working.
	const poison = e?.name === "Rejected" || row.attempts >= MAX_ATTEMPTS
	row.state = poison ? "failed" : "pending"
	await idbPut(STORE_OUTBOX, { ...row })
	if (poison) {
		// Interrupt them. The operator has already walked away believing this was sent, and
		// the whole design leans on a rejection being noticed — a badge quietly changing
		// colour in the header is not noticing.
		//
		// A settled row is interrupted just as loudly but not dressed as a failure: nothing
		// broke, somebody else finished the job first. The server's own sentence ("Cleaning
		// Order sudah selesai.") is the clearest thing to show; the panel carries the rest.
		const title = row.title || (row.settled ? labels.queueSettledTitle : labels.queueFailedTitle)
		if (row.settled) toast.info(row.error, { title })
		else toast.error(row.error, { title })
	}
	// Parked rows step aside so the queue behind them still moves; anything else means the
	// link is unhealthy, so stop and let the retry timer try the whole queue again later.
	return poison
}

/** Put a failed row back in the queue — the operator's manual retry. */
export async function retryRow(id) {
	const row = state.rows.find((r) => r.id === id)
	// A settled row cannot be retried into existence; the panel does not offer the button,
	// and this is the guard behind it.
	if (!row || row.settled) return
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
		for (const ref of row.refs || []) await dropBlob(ref)
	}
	await idbDelete(STORE_OUTBOX, id)
	state.rows = state.rows.filter((r) => r.id !== id)
}

// --- transport --------------------------------------------------------------

// Photos this session has already put on the server, `local:` ref -> file_url. A direct
// send that the server then REFUSES leaves the form holding its original `local:` refs; the
// operator fixes the complaint and presses send again, and without this every photo would go
// up the wire a second time. On the yard's 3G that is the difference between a correction
// taking seconds and taking another minute.
const uploaded = new Map()

async function uploadStashed(ref) {
	if (uploaded.has(ref)) return uploaded.get(ref)
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
	uploaded.set(ref, data.message.file_url)
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
	const { message, type } = await readError(res)
	const e = named("Rejected", message)
	// The server names the exception class in `exc_type`. `AlreadySettled` (see
	// container_depot/exceptions.py) means the document has moved past this request for
	// good — the one refusal where retrying is not just useless but misleading.
	e.settled = type === "AlreadySettled"
	throw e
}

async function readError(res) {
	try {
		const body = await res.json()
		const message = body._server_messages
			? JSON.parse(body._server_messages).map(safeMsg).join(" ")
			: body.exception || res.statusText
		return { message, type: body.exc_type || null }
	} catch {
		return { message: res.statusText || `HTTP ${res.status}`, type: null }
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
	//
	// It forces rather than clearing `online` first. Optimistically flipping the flag true
	// every 30s made the header blink "connected" on a link that had been dead for an hour;
	// forcing a real send and letting the outcome set the flag says only what is true.
	setInterval(() => {
		if (navigator.onLine !== false) flush({ force: true })
	}, RETRY_MS)
}

export { storageHeadroom }
