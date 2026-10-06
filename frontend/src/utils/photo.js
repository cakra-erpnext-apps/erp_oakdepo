// Shrink a picked photo before it is queued or uploaded.
//
// A depot handset shoots 12 MP: roughly 4-8 MB a frame. That is hostile on both ends of the
// trip — it fills the offline queue after a handful of shots, and on the yard's 3G it can
// take a minute to upload, which is how a surveyor ends up pressing the button twice.
//
// EIR photos are evidence of a dent, a valve, a seal. 1600 px on the long edge at quality
// 0.82 lands around 250-400 kB and still shows all three plainly. Roughly a 15x saving for
// no loss the inspector can act on.

const MAX_EDGE = 1600
const QUALITY = 0.82

/**
 * Return a downscaled JPEG version of `file`, or the original when shrinking is not
 * possible or not worth it.
 *
 * `stamp: true` burns the current date and time into the bottom-right corner, the way a
 * timestamp camera does: the moment the photo is shot or picked in the app. Deliberately not
 * the file's own date — a gallery file's date is unreliable and can be old.
 *
 * Never throws: a photo that will not decode (an odd HEIC on an old WebView, a corrupt
 * frame) is passed through untouched, even unstamped. Losing the evidence to a compression
 * step would be a far worse outcome than uploading a large file.
 */
export async function compressPhoto(file, { stamp = false } = {}) {
	if (!file || !file.type?.startsWith("image/")) return file
	try {
		const bitmap = await loadBitmap(file)
		const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height))
		// Already small enough — re-encoding would only cost quality for nothing.
		if (!stamp && scale === 1 && file.size < 600 * 1024) {
			bitmap.close?.()
			return file
		}
		const canvas = document.createElement("canvas")
		canvas.width = Math.round(bitmap.width * scale)
		canvas.height = Math.round(bitmap.height * scale)
		const ctx = canvas.getContext("2d")
		ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
		bitmap.close?.()
		if (stamp) drawStamp(ctx, canvas, new Date())

		const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", QUALITY))
		// Re-encoding can inflate an already-optimised JPEG. Keep whichever is smaller —
		// unless it carries the stamp, which the original does not.
		if (!blob || (!stamp && blob.size >= file.size)) return file
		return new File([blob], jpegName(file.name), { type: "image/jpeg", lastModified: Date.now() })
	} catch {
		return file
	}
}

const pad = (n) => String(n).padStart(2, "0")

/** "05/06/2026 13:48" in the handset's local time, white on a dark outline: readable on sky and on rust. */
function drawStamp(ctx, canvas, d) {
	const text = `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
	const size = Math.max(14, Math.round(Math.min(canvas.width, canvas.height) * 0.045))
	const margin = Math.round(size * 0.6)
	ctx.font = `600 ${size}px sans-serif`
	ctx.textAlign = "right"
	ctx.textBaseline = "bottom"
	ctx.lineJoin = "round"
	ctx.lineWidth = Math.max(2, size / 6)
	ctx.strokeStyle = "rgba(0,0,0,0.75)"
	ctx.strokeText(text, canvas.width - margin, canvas.height - margin)
	ctx.fillStyle = "#fff"
	ctx.fillText(text, canvas.width - margin, canvas.height - margin)
}

function loadBitmap(file) {
	if (window.createImageBitmap) return createImageBitmap(file)
	// Safari < 15 and older Android WebViews.
	return new Promise((resolve, reject) => {
		const url = URL.createObjectURL(file)
		const img = new Image()
		img.onload = () => {
			URL.revokeObjectURL(url)
			resolve(img)
		}
		img.onerror = (e) => {
			URL.revokeObjectURL(url)
			reject(e)
		}
		img.src = url
	})
}

function jpegName(name) {
	const base = (name || "photo").replace(/\.[^.]+$/, "")
	return `${base}.jpg`
}
