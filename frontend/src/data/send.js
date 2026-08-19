// Saving from the PWA: one call, straight to the server, and the operator learns the outcome.
//
// This replaces the offline outbox (removed 2026-08-18). That queue held finished work in
// IndexedDB and sent it on its own schedule, and it lost work WITH a link, not without one:
// its `online` flag was a guess that any failed GET anywhere in the app could flip, and one
// row in the queue made every later save queue behind it — so a single blip parked a handset
// in queue mode while the operator kept working and kept reading "tersimpan". A depot that
// has signal never needed it, and a queue that quietly holds a day of sign-offs is worse than
// a save that fails out loud.
//
// So: `send` waits for the real answer. A refusal ("that tank still has open work") arrives
// while the operator is standing at the tank, not as a row in a panel an hour later. A
// failure throws, every caller already catches and toasts it, and nothing is written to
// IndexedDB — the form keeps its own state on screen and the operator presses send again.
//
// Photos go up the moment they are taken (`uploadPhoto`), so the autosave that follows a
// second later writes a real file_url into the draft and the server is never behind what the
// operator sees. Parking one locally is now only the FALLBACK: an upload that cannot reach
// the server hands back a `local:` ref instead of failing, the form carries it exactly as it
// carried a URL, and `send` retries it when the document is finally sent. The cost is a file
// left attached to a draft that is later abandoned — cheaper than an operator who photographs
// a dent, reloads the app, and finds the evidence was never anywhere but in the tab.

import { reactive } from "vue"

import { link, noteLinkDown, noteLinkUp, noteSessionExpired } from "@/data/link"
import { STORE_BLOBS, idbDelete, idbGet, idbPut, uid } from "@/utils/idb"
import { compressPhoto } from "@/utils/photo"
import { labels } from "@/utils/labels"
import { dismissKey, toast } from "@/utils/toast"

const LOCAL_PREFIX = "local:"

// --- stashed photos ---------------------------------------------------------

// Object URLs for the stashed photos, so a template renders a not-yet-uploaded photo with
// the same `:src` it uses for an uploaded one. Rebuilt by `hydratePreviews` after a reload,
// because object URLs die with the document that made them.
const previews = reactive({})

/** Park a picked photo locally and return the placeholder that stands in for its URL. */
export async function stashPhoto(file) {
	const id = uid()
	await idbPut(STORE_BLOBS, { id, blob: file, name: file.name || "photo.jpg", created_at: Date.now() })
	const ref = `${LOCAL_PREFIX}${id}`
	previews[ref] = URL.createObjectURL(file)
	return ref
}

/**
 * Shrink a picked photo and get it onto the server NOW, returning its file_url — which the
 * next autosave writes straight into the draft.
 *
 * Never throws for a link that is down: an upload that cannot land parks the photo instead
 * and returns a `local:` ref, so the operator keeps shooting and `send` carries the backlog
 * when the document is submitted. Only the operator's own picture matters here; losing it to
 * a red error message would be the one unrecoverable outcome.
 */
export async function uploadPhoto(file) {
	const small = await compressPhoto(file)
	const key = "photo-upload"
	try {
		// Held back 400 ms — a photo that lands quickly needs no announcement at all.
		toast.busy(labels.photoUploading, { key, delay: 400 })
		return await uploadBlob(small, small.name || file.name || "photo.jpg")
	} catch (e) {
		if (e?.name === "SessionExpired") noteSessionExpired()
		else noteLinkDown()
		// One toast however many photos are waiting: they all leave together on Kirim.
		toast.info(labels.photoParked, { key: "photo-parked" })
		return stashPhoto(small)
	} finally {
		dismissKey(key)
	}
}

export const isLocalRef = (url) => typeof url === "string" && url.startsWith(LOCAL_PREFIX)

/** Render a photo reference: a server file_url passes through, a stashed one resolves. */
export function photoSrc(ref) {
	if (!isLocalRef(ref)) return ref
	return previews[ref] || ""
}

/** Re-open object URLs for `refs` after a reload, so the form shows its photos again. */
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

const dropBlob = (ref) => idbDelete(STORE_BLOBS, ref.slice(LOCAL_PREFIX.length))

// --- the send ---------------------------------------------------------------

/** Is a save in flight? Screens use it to keep a button from being pressed twice. */
export const sending = reactive({ count: 0 })

// Names this send's toast slot, so two sends in flight own one card each.
let sendSeq = 0

/**
 * Upload whatever photos the payload still references locally, substitute their real URLs,
 * then post the document.
 *
 * Atomic on purpose: the photos go up first and the save goes out last, so a save that never
 * happens cannot leave the operator believing it did. Photos that DID land are dropped from
 * local storage (their bytes are on the server now); the ones still unsent stay stashed,
 * because the form still points at them and the retry needs them.
 *
 * Throws on any failure — a refusal from the server, a dead link, an expired session — and
 * the caller shows it. There is deliberately no fallback: silently keeping the work was the
 * whole failure this module was written to remove.
 */
export async function send({ url, payload }) {
	const uploadedRefs = []
	let body = payload
	sending.count += 1
	// One toast per send, replaced in place as the work moves: the photos, then the save.
	// It holds back 400 ms first — an action that answers straight away needs no spinner,
	// only its result, and the caller already toasts that. A send carrying photos always
	// outlives the delay, which is exactly the wait worth narrating. Cleared in `finally`,
	// so no spinner is ever left hanging beside the caller's success or error toast.
	const key = `send-${++sendSeq}`
	const step = (message) => toast.busy(message, { key, delay: 400 })
	try {
		const refs = collectLocalRefs(body)
		let done = 0
		for (const ref of refs) {
			step(`${labels.sendUploadingPhoto} ${++done}/${refs.length}`)
			const fileUrl = await uploadStashed(ref)
			body = substitute(body, ref, fileUrl)
			uploadedRefs.push(ref)
		}
		step(labels.sendSaving)
		const answer = await post(url, body)
		noteLinkUp() // proof, not a guess: something just got through
		for (const ref of uploadedRefs) await dropBlob(ref)
		return answer
	} catch (e) {
		if (e?.name === "SessionExpired") noteSessionExpired()
		else if (e?.name === "Offline") noteLinkDown()
		// Whatever went wrong, a photo already on the server is not coming back down.
		for (const ref of uploadedRefs) await dropBlob(ref)
		throw e
	} finally {
		sending.count -= 1
		dismissKey(key)
	}
}

// --- transport --------------------------------------------------------------

// Photos this session has already put on the server, `local:` ref -> file_url. A send the
// server then REFUSES leaves the form holding its original `local:` refs; the operator fixes
// the complaint and presses send again, and without this every photo would go up the wire a
// second time. On the yard's 3G that is a correction taking seconds rather than another
// minute.
const uploaded = new Map()

async function uploadStashed(ref) {
	if (uploaded.has(ref)) return uploaded.get(ref)
	const id = ref.slice(LOCAL_PREFIX.length)
	const stored = await idbGet(STORE_BLOBS, id)
	if (!stored) {
		// The blob is gone (evicted, or already uploaded and the substitution lost). Nothing
		// can bring it back, so fail loudly rather than saving an EIR with a dangling
		// `local:` reference in it.
		throw named("Rejected", "Foto tidak ditemukan di penyimpanan lokal.")
	}
	const fileUrl = await uploadBlob(stored.blob, stored.name)
	uploaded.set(ref, fileUrl)
	return fileUrl
}

/** Put one blob on the server and hand back its file_url. Throws like any other request. */
async function uploadBlob(blob, name) {
	const fd = new FormData()
	fd.append("file", blob, name)
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
		// fetch only rejects on a transport failure — exactly the dropped-signal case.
		// Anything the server answered, however badly, lands below.
		throw named("Offline", e?.message || "Tidak ada koneksi ke server.")
	}
	if (res.ok) return res
	if (res.status === 401 || res.status === 403) throw named("SessionExpired", "Sesi berakhir, login lagi.")
	if (res.status >= 500) throw named("Offline", `Server tidak merespons (${res.status}).`)
	const { message } = await readError(res)
	throw named("Rejected", message)
}

async function readError(res) {
	try {
		const body = await res.json()
		const message = body._server_messages
			? JSON.parse(body._server_messages).map(safeMsg).join(" ")
			: body.exception || res.statusText
		return { message }
	} catch {
		return { message: res.statusText || `HTTP ${res.status}` }
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

/** Every `local:` photo reference anywhere in a payload, in the order they appear. */
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

/** A copy of `value` with every occurrence of `ref` replaced by `replacement`. */
function substitute(value, ref, replacement) {
	if (value === ref) return replacement
	if (Array.isArray(value)) return value.map((v) => substitute(v, ref, replacement))
	if (value && typeof value === "object") {
		return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, substitute(v, ref, replacement)]))
	}
	return value
}

export { link }
