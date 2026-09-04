// The photos that are on their way up, each holding its own preview.
//
// A grid used to have nothing to show between the shutter and the upload landing, so it
// showed an anonymous grey spinner — which answers "something is happening" but not the
// question the operator actually has, which is "where is the picture I just took?". The
// queue keeps an object URL of the frame itself, so the picture appears in the grid the
// instant it is taken and simply STOPS being marked as pending once it is on the server.
// Camera and gallery go through the same queue: to the operator they are one action with
// one answer.
//
// Deliberately separate from the form's own photo array. Nothing in here can be saved by
// accident — a preview is not a file_url, and the payload builders never see it.
import { reactive } from "vue"

export function usePhotoQueue() {
	/** `{ id, preview, state: "uploading" | "failed" }`, oldest first. */
	const items = reactive([])
	let seq = 0

	/** Put a picked file on the queue and return its id. */
	function add(file) {
		const id = ++seq
		items.push({ id, preview: URL.createObjectURL(file), state: "uploading" })
		return id
	}

	/** It landed (on the server, or parked on the handset) — the real thumbnail takes over. */
	function done(id) {
		const i = items.findIndex((x) => x.id === id)
		if (i === -1) return
		URL.revokeObjectURL(items[i].preview)
		items.splice(i, 1)
	}

	/** It went nowhere at all. The tile stays, in red, because this one has to be retaken. */
	function fail(id) {
		const it = items.find((x) => x.id === id)
		if (it) it.state = "failed"
	}

	/** Wipe the previous round's failures — called when the operator shoots again. */
	function clearFailed() {
		for (let i = items.length - 1; i >= 0; i--) {
			if (items[i].state !== "failed") continue
			URL.revokeObjectURL(items[i].preview)
			items.splice(i, 1)
		}
	}

	return { items, add, done, fail, clearFailed }
}
