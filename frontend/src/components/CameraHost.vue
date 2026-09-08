<!-- Literal white / black throughout, not theme tokens: the viewfinder chrome sits over a
     live camera feed, which is dark whatever the app's theme is. A shutter button that
     followed the surface colour would be a black circle on a black bar. -->
<template>
	<transition name="cam">
		<div v-if="cameraState.open" class="fixed inset-0 z-[70] flex flex-col bg-black" role="dialog" aria-modal="true">
			<!-- Viewfinder. object-cover so the frame fills a phone of any aspect ratio; the
			     capture below reads the raw video, never this element, so nothing is lost to
			     the crop the operator sees. -->
			<div class="relative flex-1 overflow-hidden">
				<video
					ref="video"
					class="h-full w-full object-cover"
					autoplay
					playsinline
					muted
				></video>

				<div
					v-if="starting"
					class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black px-8 text-center"
				>
					<Icon name="camera" :size="30" class="text-white/50" />
					<p class="text-sm text-white/70">{{ labels.camStarting }}</p>
				</div>

				<!-- Top bar: close, and the torch when the phone admits to having one. -->
				<div
					class="absolute inset-x-0 top-0 flex items-center justify-between p-3 pt-[max(0.75rem,env(safe-area-inset-top))]"
				>
					<button
						type="button"
						class="rounded-full bg-black/40 p-2 text-white backdrop-blur transition active:scale-95"
						:aria-label="labels.camClose"
						@click="done"
					>
						<Icon name="x" :size="22" />
					</button>
					<button
						v-if="hasTorch"
						type="button"
						class="rounded-full p-2 backdrop-blur transition active:scale-95"
						:class="torchOn ? 'bg-white text-black' : 'bg-black/40 text-white'"
						:aria-label="labels.camTorch"
						@click="toggleTorch"
					>
						<Icon :name="torchOn ? 'zap' : 'zap-off'" :size="20" />
					</button>
					<span v-else></span>
				</div>
			</div>

			<!-- Shutter bar -->
			<div
				class="flex items-center justify-between gap-4 bg-black px-6 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
			>
				<!-- Left: the last shot, as proof the tap did something. Tapping nothing:
				     deleting happens in the form behind, where the photo belongs to a row. -->
				<div class="flex h-14 w-14 items-center justify-center">
					<img
						v-if="cameraState.lastShot"
						:src="cameraState.lastShot"
						alt=""
						class="h-14 w-14 rounded-lg border border-white/25 object-cover"
					/>
				</div>

				<button
					type="button"
					class="flex h-[68px] w-[68px] items-center justify-center rounded-full border-4 border-white/80 transition active:scale-90 disabled:opacity-40"
					:aria-label="labels.camShutter"
					:disabled="starting"
					@click="shoot"
				>
					<span class="h-[52px] w-[52px] rounded-full bg-white"></span>
				</button>

				<div class="flex h-14 w-14 flex-col items-center justify-center gap-0.5">
					<button type="button" class="text-sm font-semibold text-white" @click="done">
						{{ labels.camDone }}
					</button>
					<span v-if="cameraState.count" class="text-[10px] leading-none text-white/50 tabular-nums">
						{{ cameraState.count }}
					</span>
				</div>
			</div>
		</div>
	</transition>
</template>

<script setup>
import { ref, watch } from "vue"
import { cameraState, closeCamera, noteShot } from "@/utils/camera"
import { useDismissOnBack } from "@/utils/backstack"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const video = ref(null)
const starting = ref(false)
const hasTorch = ref(false)
const torchOn = ref(false)
let stream = null

// Back is the only dismiss a handset has, and without this it would leave the EIR behind
// the camera instead of closing the camera.
useDismissOnBack(
	() => cameraState.open,
	() => done()
)

// `flush: "post"` matters: a pre-flush watcher runs BEFORE Vue paints the v-if above, so
// `video.value` would still be null when the stream is ready to attach — and on a second
// open, where the permission is already granted, getUserMedia resolves fast enough to lose
// that race.
watch(
	() => cameraState.open,
	(open) => (open ? start() : stop()),
	{ flush: "post" }
)

async function start() {
	starting.value = true
	hasTorch.value = false
	torchOn.value = false
	try {
		// `ideal`, never `exact`: a tablet with only a front camera must still be able to
		// take the picture rather than throw OverconstrainedError at the surveyor.
		stream = await navigator.mediaDevices.getUserMedia({
			video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
			audio: false,
		})
		// Closed again while the permission sheet was up — the operator changed their mind,
		// and a stream nobody is watching must not be left holding the camera.
		if (!cameraState.open || !video.value) return stop()
		video.value.srcObject = stream
		await video.value.play().catch(() => {})
		const track = stream.getVideoTracks()[0]
		hasTorch.value = !!track?.getCapabilities?.().torch
	} catch {
		// Denied, no device, or the camera is held by another app. Hand the caller back a
		// `false` so it opens the phone's own camera instead — see utils/camera.js. No error
		// screen here on purpose: the fallback camera opens in its place, and two things
		// telling the operator about one tap is one too many.
		closeCamera(false)
	} finally {
		starting.value = false
	}
}

function stop() {
	torchOn.value = false
	if (video.value) video.value.srcObject = null
	stream?.getTracks().forEach((t) => t.stop())
	stream = null
}

async function toggleTorch() {
	const track = stream?.getVideoTracks()[0]
	if (!track) return
	try {
		await track.applyConstraints({ advanced: [{ torch: !torchOn.value }] })
		torchOn.value = !torchOn.value
	} catch {
		hasTorch.value = false // it claimed the capability and then refused it
	}
}

function shoot() {
	const el = video.value
	if (!el?.videoWidth) return
	// Grabbed now, not inside the callback: toBlob is async, and tapping the shutter and
	// then "Selesai" in the same breath would otherwise find `_onShot` already nulled by
	// closeCamera and drop the photo without a word.
	const onShot = cameraState._onShot
	const canvas = document.createElement("canvas")
	canvas.width = el.videoWidth
	canvas.height = el.videoHeight
	canvas.getContext("2d").drawImage(el, 0, 0)
	canvas.toBlob(
		(blob) => {
			if (!blob) return
			const file = new File([blob], `eir-${Date.now()}.jpg`, { type: "image/jpeg" })
			// Thumbnail first, upload second: the corner has to answer the tap immediately,
			// and the upload takes as long as the yard's signal takes.
			if (cameraState.open) noteShot(URL.createObjectURL(blob))
			// Deliberately not awaited: the upload holds its own reference to the file and
			// finishes whether or not the viewfinder is still open, so "Selesai" never waits
			// on the yard's signal.
			onShot?.(file)
		},
		"image/jpeg",
		// Quality 0.92 here, not the 0.82 the uploader uses: this is the ORIGINAL frame, and
		// utils/photo.js re-encodes it once on the way out. Compressing twice at 0.82 shows.
		0.92
	)
}

function done() {
	closeCamera(true)
}
</script>

<style scoped>
.cam-enter-active,
.cam-leave-active {
	transition: opacity 0.15s ease;
}
.cam-enter-from,
.cam-leave-to {
	opacity: 0;
}
</style>
