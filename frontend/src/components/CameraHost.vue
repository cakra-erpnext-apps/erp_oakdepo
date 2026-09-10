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

				<!-- Satu kedip putih tiap jepretan. Bukan hiasan: di halaman yang shutter-nya
				     tidak berbunyi dan tidak bergetar, kedipan inilah satu-satunya tanda
				     seketika bahwa ketukan tadi benar-benar mengambil gambar — sisanya
				     (petak baru di strip) muncul sepersekian detik kemudian. -->
				<div v-if="flash" class="pointer-events-none absolute inset-0 bg-white flash"></div>

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

			<!-- The roll: every shot of this session with what became of it. The operator is
			     INSIDE the camera while twenty photos go up, and the thumbnails in the form
			     behind — which is where upload state used to be shown — are exactly what they
			     cannot see. Without this, "sudah berapa" and "terkirim atau tidak" could only
			     be answered by closing the viewfinder. -->
			<div v-if="cameraState.roll.length" class="bg-black px-3 pt-2">
				<div class="mb-1.5 flex items-center justify-between gap-2 text-[11px] tabular-nums">
					<span class="font-semibold text-white/80">{{ tally.total }} {{ labels.camCount }}</span>
					<span class="flex items-center gap-2">
						<span v-if="tally.uploading" class="text-white/60">{{ tally.uploading }} {{ labels.camShotUploading }}</span>
						<span v-if="tally.sent" class="text-leaf-400">{{ tally.sent }} {{ labels.camShotSent }}</span>
						<span v-if="tally.parked" class="text-amber-400">{{ tally.parked }} {{ labels.camShotParked }}</span>
						<span v-if="tally.failed" class="text-red-400">{{ tally.failed }} {{ labels.camShotFailed }}</span>
					</span>
				</div>
				<!-- Scrolls, newest last and scrolled to: the strip has to stay one row tall on a
				     phone whichever way it grows. -->
				<div ref="strip" class="flex gap-1.5 overflow-x-auto pb-2">
					<div
						v-for="shot in cameraState.roll"
						:key="shot.id"
						class="shot relative h-12 w-12 shrink-0 overflow-hidden rounded-md border"
						:class="shot.state === 'failed' ? 'border-red-400' : 'border-white/25'"
					>
						<img :src="shot.thumb" alt="" class="h-full w-full object-cover" :class="shot.state === 'failed' ? 'opacity-40' : ''" />
						<!-- `key` on the state so the badge is REPLACED when the shot settles: the
						     pop-in below only plays on mount, and a badge that quietly swaps its
						     icon is the change most likely to be missed. -->
						<span
							:key="shot.state"
							class="mark absolute bottom-0.5 right-0.5 flex h-4 w-4 items-center justify-center rounded-full text-white"
							:class="badgeClass(shot.state)"
							:title="badgeTitle(shot.state)"
						>
							<Icon :name="badgeIcon(shot.state)" :size="9" :stroke="3" :class="shot.state === 'uploading' ? 'animate-spin' : ''" />
						</span>
					</div>
				</div>
				<p v-if="tally.failed" class="pb-1 text-[11px] text-red-400">{{ labels.camRetakeHint }}</p>
			</div>

			<!-- Shutter bar -->
			<div
				class="flex items-center justify-between gap-4 bg-black px-6 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
			>
				<div class="h-14 w-14"></div>

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
					<span v-if="tally.total" class="text-[10px] leading-none text-white/50 tabular-nums">
						{{ tally.total }}
					</span>
				</div>
			</div>
		</div>
	</transition>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { cameraState, closeCamera, markShot, noteShot, rollTally } from "@/utils/camera"
import { isLocalRef } from "@/data/send"
import { useDismissOnBack } from "@/utils/backstack"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const video = ref(null)
const strip = ref(null)
const starting = ref(false)
const flash = ref(false)
const hasTorch = ref(false)
const torchOn = ref(false)
let stream = null

const tally = computed(() => rollTally())

// Same vocabulary as the badge on a form thumbnail (components/PhotoMark.vue): green tick =
// on the server, amber clock = still only on this handset, red = has to be retaken. Two
// surfaces telling one story two ways would be worse than either alone.
const BADGE = {
	uploading: { icon: "loader", cls: "bg-gray-900/80", title: labels.photoMarkUploading },
	sent: { icon: "check", cls: "bg-leaf-600", title: labels.photoMarkSent },
	parked: { icon: "clock", cls: "bg-amber-500", title: labels.photoMarkParked },
	failed: { icon: "alert-triangle", cls: "bg-red-500", title: labels.photoMarkFailedHint },
}
const badgeIcon = (state) => BADGE[state].icon
const badgeClass = (state) => BADGE[state].cls
const badgeTitle = (state) => BADGE[state].title

// The newest shot is the one being asked about, so the strip follows it. `nextTick` because
// the tile it scrolls to does not exist until Vue has painted the push.
watch(
	() => cameraState.roll.length,
	() => nextTick(() => strip.value && (strip.value.scrollLeft = strip.value.scrollWidth))
)

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
	blink()
	// Encoded from the frame that was just grabbed, not from the upload: the tile has to be
	// on the strip before the first byte leaves, and a 96 px JPEG costs a few kB, so a whole
	// inspection's worth of them is cheaper than one full frame.
	// On the strip BEFORE the encode, not after it: `toBlob` is asynchronous, and a shutter
	// whose answer waits even a tenth of a second is a shutter the operator taps twice.
	const id = cameraState.open ? noteShot(thumbnail(canvas)) : null
	canvas.toBlob(
		(blob) => {
			// The frame never encoded — nothing to upload, and the tile must say so rather
			// than sit there spinning for the rest of the session.
			if (!blob) return id && markShot(id, "failed")
			const file = new File([blob], `eir-${Date.now()}.jpg`, { type: "image/jpeg" })
			// Deliberately not awaited: the upload holds its own reference to the file and
			// finishes whether or not the viewfinder is still open, so "Selesai" never waits
			// on the yard's signal. What IS tracked is its answer — see utils/camera.js for
			// the contract, and why a caller that swallows its error lies to the operator.
			Promise.resolve(onShot?.(file))
				.then((ref) => id && markShot(id, !ref ? "failed" : isLocalRef(ref) ? "parked" : "sent"))
				.catch(() => id && markShot(id, "failed"))
		},
		"image/jpeg",
		// Quality 0.92 here, not the 0.82 the uploader uses: this is the ORIGINAL frame, and
		// utils/photo.js re-encodes it once on the way out. Compressing twice at 0.82 shows.
		0.92
	)
}

/** A ~96 px data: url of the frame, for the strip. Synchronous, so the tile lands at once. */
function thumbnail(canvas) {
	const scale = Math.min(1, 96 / Math.max(canvas.width, canvas.height))
	const small = document.createElement("canvas")
	small.width = Math.max(1, Math.round(canvas.width * scale))
	small.height = Math.max(1, Math.round(canvas.height * scale))
	small.getContext("2d").drawImage(canvas, 0, 0, small.width, small.height)
	return small.toDataURL("image/jpeg", 0.6)
}

let flashTimer = null
function blink() {
	flash.value = true
	clearTimeout(flashTimer)
	flashTimer = setTimeout(() => (flash.value = false), 120)
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

/* Kedip rana. Cepat dan sekali — lebih lama dari ini dan ia menutupi bidikan berikutnya. */
.flash {
	animation: flash 0.12s ease-out;
}
@keyframes flash {
	from {
		opacity: 0.85;
	}
	to {
		opacity: 0;
	}
}

/* Petaknya masuk dari arah rana: itulah yang membuat "ketukan tadi jadi foto" terbaca sebagai
   satu gerakan, bukan sebagai kotak yang tiba-tiba ada. */
.shot {
	animation: shot-in 0.18s ease-out;
}
@keyframes shot-in {
	from {
		opacity: 0;
		transform: scale(0.8);
	}
}

/* Dan tandanya memantul begitu nasibnya diketahui — satu ketukan waktu setelah petaknya
   muncul, yang justru itulah pesannya: ia bergerak, dan ia sampai. */
.mark {
	animation: mark-in 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes mark-in {
	from {
		opacity: 0;
		transform: scale(0.4);
	}
}

@media (prefers-reduced-motion: reduce) {
	.flash,
	.shot,
	.mark {
		animation: none;
	}
}
</style>
