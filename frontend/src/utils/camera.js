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
	 * Object URL of the LAST shot only, and how many were taken. Not the whole roll: each
	 * frame is a full-resolution JPEG held in memory, and a tank inspection runs to dozens —
	 * a strip of them would cost a cheap handset a hundred megabytes to show a row of
	 * thumbnails nobody taps. The roll the operator actually reviews is the one in the form
	 * behind the viewfinder, where each photo already belongs to a checklist row.
	 */
	lastShot: "",
	count: 0,
	_onShot: null,
	_resolve: null,
})

/** Record a shot's preview, dropping the one it replaces. */
export function noteShot(url) {
	if (cameraState.lastShot) URL.revokeObjectURL(cameraState.lastShot)
	cameraState.lastShot = url
	cameraState.count += 1
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
		cameraState.lastShot = ""
		cameraState.count = 0
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
	if (cameraState.lastShot) URL.revokeObjectURL(cameraState.lastShot)
	cameraState.lastShot = ""
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
