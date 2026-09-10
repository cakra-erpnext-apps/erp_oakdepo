// In-app camera for the Depot PWA. Import `shootPhotos` anywhere a photo is taken and it
// pops a fullscreen viewfinder: every tap of the shutter hands the frame straight to the
// caller's upload, and the viewfinder stays open for the next shot.
//
// Why not `<input type="file" capture="environment">` — which is what every photo button
// used before: that hands the phone's own camera app the job, and the camera app insists on
// a review screen ("Retake / Use Photo", or the tick on Android) before it will give the
// frame back. That screen exists to let you check the shot, but the operator already sees
// every shot as a thumbnail in the form a second later, and can delete it there. So it buys
// nothing and costs an extra tap on every single photo — of which a tank inspection has
// dozens. Owning the viewfinder removes it: shutter IS the decision.
//
// The old input stays in the markup as the fallback (see `cameraSupported`), because
// getUserMedia is not always there to be had — an insecure origin, a browser that does not
// implement it, a phone whose owner denied the camera permission. Losing the ability to
// photograph a dent would be far worse than an extra confirm tap.
import { reactive } from "vue"

export const cameraState = reactive({
	open: false,
	/**
	 * Every shot of this session, oldest first: `{ id, thumb, state }` with `state` one of
	 * `uploading` / `sent` / `parked` / `failed`.
	 *
	 * It used to keep the LAST frame only, on the grounds that a full-resolution JPEG per
	 * shot would cost a cheap handset a hundred megabytes over a tank inspection. That is
	 * true of full frames and not of these: `thumb` is a ~96 px re-encode (a few kB), so
	 * forty of them are cheaper than one of the originals.
	 *
	 * Keeping them is what lets the viewfinder answer the two questions an operator taking
	 * twenty photos in a row actually has — how many have I taken, and did they get out of
	 * my hand — without leaving the camera to go and look at the form.
	 */
	roll: [],
	_onShot: null,
	_resolve: null,
})

let seq = 0

/** Record a shot and return its id, for :func:`markShot` to settle later. */
export function noteShot(thumb) {
	const id = ++seq
	cameraState.roll.push({ id, thumb, state: "uploading" })
	return id
}

/** Settle one shot: `sent` (on the server), `parked` (on the handset), or `failed`. */
export function markShot(id, state) {
	const shot = cameraState.roll.find((x) => x.id === id)
	if (shot) shot.state = state
}

/** How many of the roll are in each state — the counter over the strip. */
export function rollTally() {
	const tally = { total: cameraState.roll.length, uploading: 0, sent: 0, parked: 0, failed: 0 }
	for (const s of cameraState.roll) tally[s.state] += 1
	return tally
}

function emptyRoll() {
	// Only a blob: url owns anything to release — the thumbnails are data: urls (encoded
	// synchronously, so the strip answers the shutter in the same frame) and revoking one of
	// those is a no-op the code should not pretend to be doing.
	for (const shot of cameraState.roll) {
		if (typeof shot.thumb === "string" && shot.thumb.startsWith("blob:")) {
			URL.revokeObjectURL(shot.thumb)
		}
	}
	cameraState.roll = []
}

/**
 * Whether the in-app viewfinder can run at all. `isSecureContext` is the one that bites in
 * practice: getUserMedia is defined on http:// origins but rejects, so testing for the
 * function alone would send the operator into a viewfinder that can never start.
 */
export function cameraSupported() {
	return !!(window.isSecureContext && navigator.mediaDevices?.getUserMedia)
}

/**
 * Open the viewfinder. `onShot(file)` is called with a full-resolution JPEG `File` the
 * instant the shutter is tapped — do the upload there; it runs while the operator lines up
 * the next shot.
 *
 * RETURN THE PHOTO REFERENCE from `onShot` (the `file_url`, or the `local:` ref a parked
 * photo gets): the strip in the viewfinder marks that shot from it — green tick for a real
 * URL, amber clock for a parked one — and a rejected promise or a falsy answer marks it
 * failed. A caller that swallows its own upload error therefore reports a success, which is
 * the one answer the operator must never be given about a photo.
 *
 * Resolves when the viewfinder closes: `true` if it ran, `false` if the camera could not be
 * started at all (no permission, no device, taken by another app). On `false` the caller
 * should fall back to its hidden file input.
 */
export function shootPhotos(onShot) {
	return new Promise((resolve) => {
		if (!cameraSupported()) {
			resolve(false)
			return
		}
		emptyRoll()
		cameraState._onShot = onShot
		cameraState._resolve = resolve
		cameraState.open = true
	})
}

/** Close the viewfinder. `started` is false only when the stream never came up. */
export function closeCamera(started = true) {
	if (!cameraState.open) return
	cameraState.open = false
	cameraState._onShot = null
	emptyRoll()
	const r = cameraState._resolve
	cameraState._resolve = null
	if (r) r(started)
}

/**
 * The whole photo button in one call: open the in-app viewfinder, and if it cannot run,
 * click the hidden `<input type="file" capture>` in `inputRef` so the phone's own camera
 * takes over. `onShot` receives one `File` per shutter tap.
 */
export async function shootOrFallback(inputRef, onShot) {
	const ran = await shootPhotos(onShot)
	if (!ran) inputRef.value?.click()
}
