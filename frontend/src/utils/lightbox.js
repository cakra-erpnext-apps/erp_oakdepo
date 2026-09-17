// Tiny global image-lightbox bus for the Depot PWA. Import `openLightbox` anywhere
// and call `openLightbox(urls, index)` to pop a fullscreen viewer (instead of opening
// the photo in a new browser tab). The single <LightboxHost> mounted in App.vue renders
// it. Supports a gallery (prev/next) when more than one image is passed.
import { reactive } from "vue"

export const lightbox = reactive({
	open: false,
	images: [],
	index: 0,
})

// Each entry may be a bare url or a `{photo|src, caption}` row — the same shape the
// server hands back for every photo table it owns. A caption typed at the tank is invisible
// wherever the photo is shown without it, and full-screen is where the photo is actually
// read, so the viewer carries it rather than every caller drawing its own.
export function openLightbox(images, index = 0) {
	const list = (Array.isArray(images) ? images : [images])
		.map((it) =>
			typeof it === "string"
				? { src: it, caption: "" }
				: { src: it?.src || it?.photo || "", caption: it?.caption || "" }
		)
		.filter((it) => it.src)
	if (!list.length) return
	lightbox.images = list
	lightbox.index = Math.min(Math.max(0, index), list.length - 1)
	lightbox.open = true
}

export function closeLightbox() {
	lightbox.open = false
}

export function nextImage() {
	if (lightbox.images.length) lightbox.index = (lightbox.index + 1) % lightbox.images.length
}

export function prevImage() {
	if (lightbox.images.length) {
		lightbox.index = (lightbox.index - 1 + lightbox.images.length) % lightbox.images.length
	}
}
